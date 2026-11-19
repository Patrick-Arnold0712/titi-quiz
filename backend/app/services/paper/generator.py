"""组卷引擎：按考试蓝图从**可信题源**生成一套押题卷。

蓝图来自真实试卷（见 docs/08-试卷建模.md）：
    单选 20×2 + 不定项 10×3 + 简答 2×5 + 论述 1×20 = 100 分，60 分钟

## 选题策略

1. **只从可信题源取题**（`sources.py`）：真题 / 参考站章节题 / 自出题；
   自有资料那 861 道**整体排除** —— 里面混着跟教材无关的题，
   之前用户反馈「有非课本内容、偏难怪」就是从这里来的。
2. **每个大题按题源配额取**：真题占大头，章节题与自出题补齐。
   某个桶不够时，按「真题 → 章节题 → 自出题」的顺序顺延，保证题量不缩水。
3. **章节配比对齐真题**：以真题客观题的章节分布为目标，
   某章抽得超出目标越多，后续权重越低（见 `_chapter_weight`）。
4. **判断题并入单选池**：参考站那 125 道判断题在接口层会被整形为
   A=正确 / B=错误 两个选项，本质就是单选题，所以可以进「一、单项选择题」，
   卷面上按单选题呈现（`display_qtype`）。
5. **可判分优先**：客观题必须有答案；题面残缺的一律不进候选池（quality.py）。
6. **尽量落到考点上**：有考点映射的题硬优先，否则掌握度和复习建议算不出来。

给定 seed 时结果完全可复现，便于回归测试。
组完卷会把「实际题源构成 + 章节分布」写进 `Paper.note`，可核对。
"""

from __future__ import annotations

import collections
import random
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.entities import (
    Chapter,
    KnowledgePoint,
    Paper,
    PaperItem,
    Question,
    QuestionType,
    SourceType,
)
from app.services.paper.cloze import ensure_pool as ensure_cloze_pool
from app.services.paper.sources import (
    BUCKET_LABEL,
    BUCKET_PREDICT,
    BUCKET_PRIORITY,
    bucket_of,
    chapter_spread,
    exam_chapter_shares,
    format_mix,
    in_exam_pool,
    root_chapter_map,
    source_mix_of,
)
from app.services.quality import check as quality_check

# 官方蓝图。`mix` 是每个大题的题源配额（题数），不是比例。
# 每次组卷现造几道「教材挖空」自出题（见 cloze.py）。
# 用户的要求是「每次点组卷都生成几题依据教材和考情预测的自出题」，
# 所以默认 > 0 —— 但造出来的题会**落库并复用**（tags 里带稳定 hash），
# 反复组卷不会把题库撑爆，只是每次拿到不同的组合。
DEFAULT_AUTO_CLOZE = 3

# 只从重要度不低于这个值的考点里挖空。0 表示全都要。
# 调高 = 更贴高频考点，但候选变少。
DEFAULT_MIN_KP_IMPORTANCE = 0.0

DEFAULT_BLUEPRINT: list[dict] = [
    {"section": "一、单项选择题", "qtype": "single_choice", "count": 20, "score_per": 2.0,
     "mix": {"real_exam": 9, "refsite_chapter": 7, "predict": 4}},
    {"section": "二、不定项选择题", "qtype": "multi_choice", "count": 10, "score_per": 3.0,
     "mix": {"real_exam": 5, "refsite_chapter": 3, "predict": 2}},
    {"section": "三、简答题", "qtype": "short_answer", "count": 2, "score_per": 5.0,
     "mix": {"real_exam": 1, "predict": 1}},
    {"section": "四、论述题", "qtype": "essay", "count": 1, "score_per": 20.0,
     "mix": {"real_exam": 1}},
]

OBJECTIVE = {QuestionType.single_choice, QuestionType.multi_choice, QuestionType.true_false}

# 某个大题除了本题型，还允许从哪些题型里取。
# 判断题有选项（A=正确/B=错误），卷面按单选题呈现，所以并进单选池。
SECTION_EXTRA_QTYPE: dict[QuestionType, list[QuestionType]] = {
    QuestionType.single_choice: [QuestionType.true_false],
}

W_KP = 2.0            # 考点重要度的放大系数
W_UNMAPPED = 0.35     # 没挂考点的题降权（押题卷要能落回考点才好做复习建议）
W_SUSPECT = 0.4       # 题面可疑的降权
# 教材课后「思考题」（tags = predict:hw*）加权。
# 主观题配额里只要有它，就优先用它 —— 题干是教材原话，比人工自出题更贴课本。
W_HOMEWORK = 1.6
W_CHAPTER = 2.5       # 章节配比的对齐强度，越大越贴近真题分布。
# 2.5 是实测出来的：拿 8 个种子跑一遍，量各章实际题数与真题目标占比的偏差，
# 1.5 时平均偏差 1.36 题、2.5 时 1.02 题、4.0 时反而回升到 1.18 题（压制过强，
# 反过来把高权重章节的题抽没了）。

# 题面残缺的题**根本不进候选池**。
# 为什么必须硬过滤：残缺题（设空丢了、选项没拆出来）用户根本做不了，
# 而交卷时「没作答」会被判成错 —— 白白往错题本和掌握度里灌脏数据。


def _chapter_weight(
    root: int | None,
    target_shares: dict[int, float],
    picked: collections.Counter,
    expected_total: float,
) -> float:
    """章节配比权重：某章抽得超出目标越多，权重越低。

    用「整卷期望题数」当分母，而不是「已抽总数」——
    后者在第 1、2 题时会剧烈跳动（抽一道就占 50%），把权重压到地板值。
    """
    if root is None or not target_shares:
        return 1.0
    expected = max(target_shares.get(root, 0.0) * expected_total, 0.5)
    return 1.0 / (1.0 + W_CHAPTER * picked[root] / expected)


def _weights(
    q: Question,
    kp_by_id: dict[int, KnowledgePoint],
    roots: dict[int, int],
    target_shares: dict[int, float],
    picked_chapters: collections.Counter,
    expected_total: float,
    verdict_level: str = "ok",
) -> float:
    w = 1.0
    if verdict_level == "suspect":
        w *= W_SUSPECT

    kp = kp_by_id.get(q.kp_id) if q.kp_id else None
    if kp is None:
        w *= W_UNMAPPED
    else:
        w *= 1.0 + W_KP * (kp.importance or 0.0)

    if (q.tags or "").startswith("predict:hw"):
        w *= W_HOMEWORK

    root = roots.get(q.chapter_id) if q.chapter_id else None
    w *= _chapter_weight(root, target_shares, picked_chapters, expected_total)
    return w


def _weighted_pick(pool: list[Question], weights: list[float], rng: random.Random) -> int:
    total = sum(weights)
    if total <= 0:
        return rng.randrange(len(pool))
    r = rng.random() * total
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if r <= acc:
            return i
    return len(pool) - 1


def _take(
    pool: list[Question],
    need: int,
    rng: random.Random,
    weights_of,
    picked_chapters: collections.Counter,
    roots: dict[int, int],
) -> list[Question]:
    """从 pool 里加权不重复地抽 need 道，就地消费 pool。"""
    chosen: list[Question] = []
    for _ in range(need):
        if not pool:
            break
        weights = [weights_of(q) for q in pool]
        i = _weighted_pick(pool, weights, rng)
        q = pool.pop(i)
        chosen.append(q)
        root = roots.get(q.chapter_id) if q.chapter_id else None
        if root is not None:
            picked_chapters[root] += 1
    return chosen


def generate_paper(
    db: Session,
    subject_id: int,
    *,
    name: str,
    blueprint: Iterable[dict] | None = None,
    duration_min: int = 60,
    seed: int | None = None,
    persist: bool = True,
    note: str | None = None,
    auto_cloze: int | None = None,
    min_kp_importance: float = DEFAULT_MIN_KP_IMPORTANCE,
) -> tuple[Paper, list[str]]:
    """按蓝图组卷。返回 (试卷, 警告列表)。

    persist=False 时只返回未落库的对象（用于预览）。

    `auto_cloze`：这次现造几道教材挖空自出题（None 用默认值）。
    造出来的题会**强制进卷**——不然「生成了题」却没出现在卷子上，等于没生成。
    """
    blueprint = list(blueprint or DEFAULT_BLUEPRINT)
    rng = random.Random(seed)

    # ---------- 现造自出题（教材挖空）----------
    # 放在最前面：题目要先进库拿到 id，后面 PaperItem 才能引用它。
    fresh: list[Question] = []
    want_auto = DEFAULT_AUTO_CLOZE if auto_cloze is None else int(auto_cloze)
    if want_auto > 0:
        try:
            fresh, made_n = ensure_cloze_pool(
                db, subject_id, want=want_auto, seed=seed or 0,
                min_importance=min_kp_importance,
            )
            if made_n:
                db.flush()
        except Exception as exc:          # 出题器坏了不能拖垮整张卷
            warnings_pre = [f"教材挖空出题器出错，本次跳过：{exc}"]
        else:
            warnings_pre = []
    else:
        warnings_pre = []

    kp_by_id = {k.id: k for k in db.query(KnowledgePoint).all()}
    chapters = {c.id: c for c in db.query(Chapter).all()}
    roots = root_chapter_map(db)
    target_shares = exam_chapter_shares(db, subject_id)

    # 必须按学科过滤题库。漏掉这一步，接了第二门课之后组卷会把别的科目的题混进来。
    all_questions = (
        db.query(Question)
        .filter((Question.subject_id == subject_id) | (Question.subject_id.is_(None)))
        .all()
    )

    # 体检只做一次，别在选题循环里反复算
    verdicts = {q.id: quality_check(q) for q in all_questions}
    skipped_defective = sum(1 for v in verdicts.values() if not v.usable)
    skipped_low_trust = sum(
        1 for q in all_questions
        if verdicts[q.id].usable and not in_exam_pool(q)
    )

    by_type: dict[QuestionType, list[Question]] = collections.defaultdict(list)
    for q in all_questions:
        if not verdicts[q.id].usable:
            continue          # 题面残缺，不参与组卷
        if not in_exam_pool(q):
            continue          # 信度不够的题源（自有资料），不进押题卷
        by_type[q.qtype].append(q)

    used_ids: set[int] = set()
    picked_chapters: collections.Counter = collections.Counter()
    warnings: list[str] = list(warnings_pre)
    rows: list[tuple[dict, Question]] = []
    fresh_ids = {q.id for q in fresh}
    fresh_used: list[Question] = []

    # 整卷（客观题部分）的期望题数，用于章节配比的归一化
    expected_total = float(sum(
        int(s["count"]) for s in blueprint
        if QuestionType(s["qtype"]) in OBJECTIVE
    )) or 1.0

    for sec in blueprint:
        sec_qtype = QuestionType(sec["qtype"])
        qtypes = [sec_qtype] + SECTION_EXTRA_QTYPE.get(sec_qtype, [])
        need = int(sec["count"])

        pool = [q for qt in qtypes for q in by_type.get(qt, []) if q.id not in used_ids]

        # 客观题必须可判分（有答案）
        if sec_qtype in OBJECTIVE:
            with_ans = [q for q in pool if (q.answer or "").strip()]
            if len(with_ans) < need:
                warnings.append(
                    f"{sec['section']}：有答案的题只有 {len(with_ans)} 道，蓝图需要 {need} 道，已用可用的全部"
                )
            pool = with_ans or pool

        # 押题卷要能落到考点上，否则「掌握度 / 复习建议」没法算。
        # 所以硬优先：有考点映射的先用，不够才补无考点的。
        mapped = [q for q in pool if q.kp_id and q.kp_id in kp_by_id]
        if len(mapped) >= need:
            pool = mapped
        elif mapped:
            warnings.append(
                f"{sec['section']}：有考点的题只有 {len(mapped)} 道 < 需要 {need} 道，其余用未映射的补"
            )
            pool = mapped + [q for q in pool if q not in mapped]

        if len(pool) < need:
            warnings.append(f"{sec['section']}：候选 {len(pool)} 道 < 需要 {need} 道")
            need = len(pool)

        def weights_of(q: Question, _pool=pool) -> float:
            return _weights(
                q, kp_by_id, roots, target_shares,
                picked_chapters, expected_total, verdicts[q.id].level,
            )

        mix = dict(sec.get("mix") or {})
        chosen: list[Question] = []

        # 本次现造的自出题**强制进卷**（只挑题型对得上的）
        fresh_in_section = 0
        if fresh_ids:
            forced = [q for q in pool if q.id in fresh_ids][:need]
            for q in forced:
                pool.remove(q)
                chosen.append(q)
                fresh_used.append(q)
                fresh_in_section += 1
                root = roots.get(q.chapter_id) if q.chapter_id else None
                if root is not None:
                    picked_chapters[root] += 1

        # ① 先按配额分桶取
        for bucket in BUCKET_PRIORITY:
            quota = int(mix.get(bucket, 0))
            if quota <= 0:
                continue
            # 强制进卷的自出题已经占掉了 predict 的一部分名额。
            # **必须只算本大题用掉的那几道**：写成 len(fresh_used) 是跨大题累加的，
            # 于是简答/论述的 predict 配额会被单选的 3 道挖空题一起清成 0，
            # 结果主观题永远抽不到课后习题（实测 seed=33 两道简答全成了真题）。
            if bucket == BUCKET_PREDICT:
                quota = max(0, quota - fresh_in_section)
            room = need - len(chosen)
            if room <= 0:
                break
            bucket_pool = [q for q in pool if bucket_of(q) == bucket]
            take = min(quota, len(bucket_pool), room)
            if take < quota:
                warnings.append(
                    f"{sec['section']}：{BUCKET_LABEL.get(bucket, bucket)}可用 {len(bucket_pool)} 道 "
                    f"< 配额 {quota} 道，差额由其他题源补"
                )
            got = _take(bucket_pool, take, rng, weights_of, picked_chapters, roots)
            chosen += got
            for q in got:
                pool.remove(q)

        # ② 配额没填满（题源不够）就用剩下的补足
        room = need - len(chosen)
        if room > 0:
            chosen += _take(pool, min(room, len(pool)), rng, weights_of, picked_chapters, roots)

        for q in chosen:
            used_ids.add(q.id)
            rows.append((sec, q))

    total = sum(float(s["score_per"]) * int(s["count"]) for s in blueprint)

    paper = Paper(
        subject_id=subject_id,
        name=name,
        source_type=SourceType.generated,
        duration_min=duration_min,
        total_score=total,
        blueprint=[
            {"section": s["section"], "qtype": s["qtype"], "count": int(s["count"]),
             "score_per": float(s["score_per"]),
             "total": round(float(s["score_per"]) * int(s["count"]), 2),
             "mix": dict(s.get("mix") or {})}
            for s in blueprint
        ],
        note=note,
    )

    if skipped_defective:
        warnings.append(f"题库里有 {skipped_defective} 道题因题面残缺被排除在候选之外")
    if skipped_low_trust:
        warnings.append(f"有 {skipped_low_trust} 道题因题源信度不足（自有资料）未参与组卷")

    # ---------- 命题规律报告 ----------
    # 组完卷把「实际长什么样」写出来，可核对。不写的话，
    # 「这卷子像不像真题」就只能靠感觉 —— 用户反馈过这种卷子「偏难怪」。
    picked_qs = [q for _, q in rows]
    mix_txt = format_mix(source_mix_of(picked_qs))
    spread = chapter_spread(picked_qs, roots, chapters)
    spread_txt = "、".join(f"{k.replace('第', '').replace('章', '')} {v}" for k, v in spread.items())
    lines = [f"题源构成：{mix_txt}", f"章节分布：{spread_txt}"]
    if fresh_used:
        lines.append(f"本次新造自出题 {len(fresh_used)} 道（教材原文挖空）")
    elif want_auto > 0:
        lines.append("本次没有新造自出题（候选已用尽或重要度门槛过高）")
    if target_shares:
        target_txt = "、".join(
            f"{chapters[cid].name.replace('第', '').replace('章', '')} {round(sh * 100)}%"
            for cid, sh in sorted(target_shares.items(), key=lambda x: -x[1]) if cid in chapters
        )
        lines.append(f"真题章节参考：{target_txt}")
    report = "押题卷；" + "；".join(lines)

    paper.note = (note + "；" + report) if note else report
    if warnings:
        paper.note += "；" + "；".join(warnings)

    if persist:
        db.add(paper)
        db.flush()
        # section_index 是**大题在蓝图里的序号（1 起）**，不是 0。
        # 它存在的意义是给「卷面题 → 蓝图大题」一条结构化链接：
        # 拿 section_name（自由文本，各套卷写法都不一样）去查蓝图，
        # 查不中就会静默回退，真题卷「不定项变单选」就是这么来的。
        sec_index = {id(s): i for i, s in enumerate(blueprint, 1)}
        for order, (sec, q) in enumerate(rows, 1):
            db.add(PaperItem(
                paper_id=paper.id, question_id=q.id, order_index=order,
                section_index=sec_index.get(id(sec), 0),
                section_name=sec["section"],
                score_per=float(sec["score_per"]),
            ))
        db.commit()
        db.refresh(paper)
    return paper, warnings
