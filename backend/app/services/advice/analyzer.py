"""考点掌握度分析。

三线阈值沿用 question-bank-exam-coach 的方法论（该 skill 见 docs 的调研记录）：
    及格线 70%  —— 低于此线视为「未就绪」
    安全线 80%  —— 及格到安全之间是「能过但缓冲弱」
    掌握线 90%  —— 达到即「维持」即可

每个考点算四个量：
    覆盖率 coverage  —— 做过的题 / 该考点题库总量
    正确率 accuracy  —— 答对次数 / 作答次数
    最近状态 last_ok —— 最近一次是否答对（新错的比早先改对的更紧急）
    掌握度 mastery   —— 上面三者的加权合成（0~1）
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.entities import Attempt, Chapter, KnowledgePoint, Paper, PaperItem, Question
from app.services.ingest.material_tags import SECTION_TAG
from app.services.quality import check as quality_check

PASS_LINE = 0.70
SAFE_LINE = 0.80
MASTERY_LINE = 0.90

W_COVERAGE = 0.30
W_ACCURACY = 0.55
W_RECENCY = 0.15


@dataclass
class KPStat:
    kp_id: int
    name: str
    chapter_name: str
    page_start: int | None
    pages: int
    importance: float          # 考点权重（0~1）
    total_q: int               # 题库里该考点的题数
    attempted: int             # 做过的不同题数
    attempts: int              # 作答次数
    correct: int
    last_ok: bool | None
    coverage: float
    accuracy: float
    mastery: float
    est_score: float           # 本卷预估占分
    risk_score: float          # 失分风险 = est_score × (1 - mastery)
    roi_per_page: float        # 每页教材的收益，衡量复习性价比
    weak_questions: list[int] = field(default_factory=list)   # 做错过的题 id


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def analyze_subject(db: Session, subject_id: int, total_score: float = 100.0) -> dict:
    kps = db.query(KnowledgePoint).filter(KnowledgePoint.subject_id == subject_id).all()
    chapters = {c.id: c for c in db.query(Chapter).all()}

    # 每个考点的题库总量。
    # **只数「能做的题」** —— 题面残缺的题刷题页根本不显示，
    # 算进来的话「还有 70 道没做」就是个虚数：用户做完剩下所有能做的题，
    # 进度也永远到不了 100%。
    total_by_kp: dict[int, int] = defaultdict(int)
    usable_qids: set[int] = set()
    for q in db.query(Question).filter(
        Question.subject_id == subject_id, Question.kp_id.isnot(None)
    ).all():
        if not quality_check(q).usable:
            continue
        total_by_kp[q.kp_id] += 1
        usable_qids.add(q.id)

    # 作答记录（按考点聚合）
    agg: dict[int, dict] = defaultdict(
        lambda: {"attempts": 0, "correct": 0, "qids": set(), "wrong_qids": set(), "last": None}
    )
    rows = (
        db.query(Attempt, Question.kp_id)
        .join(Question, Question.id == Attempt.question_id)
        .filter(Question.subject_id == subject_id, Question.kp_id.isnot(None))
        .order_by(Attempt.created_at)
        .all()
    )

    # 作答记录的来源分布。用来区分「实测」和「推算」——
    # reconstructed 是由「做过 N 题、错 M 题」反推的答对记录，不是逐题实测，
    # 必须让用户知道，否则会把推算结果当成真实水平。
    by_source: dict[str, int] = defaultdict(int)
    for src, qid in (
        db.query(Attempt.source, Attempt.question_id)
        .join(Question, Question.id == Attempt.question_id)
        .filter(Question.subject_id == subject_id, Question.kp_id.isnot(None))
    ):
        # 与下面的聚合口径一致：残缺题上的历史作答不算数
        if qid not in usable_qids:
            continue
        by_source[src or "manual"] += 1
    for att, kp_id in rows:
        # 以前答过的残缺题（体检规则上线之前记下的）不能算进度：
        # 那几道题现在既不在 total_q 里、也不在刷题页里，
        # 却还在扣 coverage/accuracy 的分母，口径对不上。
        if att.question_id not in usable_qids:
            continue
        a = agg[kp_id]
        a["attempts"] += 1
        a["qids"].add(att.question_id)
        if att.is_correct:
            a["correct"] += 1
        else:
            a["wrong_qids"].add(att.question_id)
        a["last"] = bool(att.is_correct)

    weights = {k.id: (k.importance or 0.0) for k in kps}
    practice_weights = bool(kps) and all(k.tags == SECTION_TAG for k in kps) and not any(weights.values())
    if practice_weights:
        # 新学科没有历年考情，只给每章等权的复习排序，不写入考点重要度或考频。
        weights = dict.fromkeys(weights, 1.0)
    wsum = sum(weights.values()) or 1.0

    stats: list[KPStat] = []
    for kp in kps:
        sec = chapters.get(kp.chapter_id)
        root = chapters.get(sec.parent_id) if sec and sec.parent_id else None
        a = agg.get(kp.id)
        total_q = total_by_kp.get(kp.id, 0)

        if a is None:
            # 完全没做过：掌握度为 0，但也不能算「已掌握」
            coverage = accuracy = mastery = 0.0
            last_ok = None
            attempts = correct = 0
            weak: list[int] = []
        else:
            attempts = a["attempts"]
            correct = a["correct"]
            attempted = len(a["qids"])
            coverage = _clamp(attempted / total_q) if total_q else 0.0
            accuracy = correct / attempts if attempts else 0.0
            last_ok = a["last"]
            recency = 1.0 if last_ok else 0.0
            mastery = _clamp(
                W_COVERAGE * coverage + W_ACCURACY * accuracy + W_RECENCY * recency
            )
            weak = sorted(a["wrong_qids"])

        pages = ((kp.page_end or kp.page_start or 0) - (kp.page_start or 0) + 1) if kp.page_start else 0
        est = total_score * (weights.get(kp.id, 0.0) / wsum)
        risk = est * (1.0 - mastery)

        stats.append(KPStat(
            kp_id=kp.id, name=kp.name,
            chapter_name=(root.name if root else (sec.name if sec else "未归章")),
            page_start=kp.page_start, pages=pages,
            importance=round(weights.get(kp.id, 0.0), 4),
            total_q=total_q, attempted=len(a["qids"]) if a else 0,
            attempts=attempts, correct=correct, last_ok=last_ok,
            coverage=round(coverage, 4), accuracy=round(accuracy, 4),
            mastery=round(mastery, 4), est_score=round(est, 2),
            risk_score=round(risk, 2),
            roi_per_page=round(risk / pages, 3) if pages else 0.0,
            weak_questions=weak,
        ))

    # 总体就绪度
    tot_attempts = sum(s.attempts for s in stats)
    tot_correct = sum(s.correct for s in stats)
    overall_acc = (tot_correct / tot_attempts) if tot_attempts else 0.0

    # 数据完整性：如果一条「答对」记录都没有，说明数据只来自错题夹，
    # 这时正确率和掌握度都无法反映真实水平 —— 不能显示成 0%，那是误导。
    # 错题夹只有错题，正确率的分母有、分子天生是 0。
    has_correct_records = tot_correct > 0
    manual_n = by_source.get("manual", 0)
    recon_n = by_source.get("reconstructed", 0)
    data_note = ""
    if tot_attempts and not has_correct_records:
        data_note = (
            f"当前 {tot_attempts} 条作答记录全部来自错题夹（没有答对记录），"
            "所以「正确率」和「掌握度」无法反映真实水平 —— "
            "它们的分母有、分子天生是 0。覆盖率仍然有效。"
            "要拿到真实数据，请在系统里刷题，或提供完整答题历史。"
        )
    elif recon_n and not manual_n:
        data_note = (
            f"当前共 {tot_attempts} 条作答记录：错题 {by_source.get('import_jlq', 0)} 条来自外部刷题记录，"
            f"另外 {recon_n} 条答对记录是按「每章做满 100 题、错题共 107 题」反推出来的，"
            "不是逐题实测。正确率可以据此估算，但如果当时的错题清单不完整、"
            "或有跳题没做完，这个数会偏高。"
            "想要完全可信的数据，请在系统里刷题 —— 新作答会记成 source=manual，优先级最高。"
        )
    if practice_weights:
        data_note = (data_note + " 新学科没有历年考情；占分仅表示按章节等权分配的复习权重，不是考试分值预测。").strip()
    attempted_kps = sum(1 for s in stats if s.attempted > 0)
    overall_cov = attempted_kps / len(stats) if stats else 0.0
    overall_mastery = (
        sum(s.mastery * s.importance for s in stats) / wsum if wsum else 0.0
    )

    if tot_attempts == 0:
        stage, readiness = "未开始", "还没有作答记录，先做一套卷摸底"
    elif not has_correct_records:
        stage = "仅错题数据"
        readiness = (
            "只有错题记录，暂时算不出真实水平 —— 先按「错题分布」挑高频考点补，"
            "同时在系统里正常刷题把答对记录攒起来"
        )
    elif overall_acc < PASS_LINE:
        stage, readiness = "建覆盖/稳正确率", "低于及格线，未就绪——先补高权重章节的覆盖"
    elif overall_acc < SAFE_LINE:
        stage, readiness = "稳正确率", "能过但缓冲弱——优先消灭反复错的题"
    elif overall_acc < MASTERY_LINE:
        stage, readiness = "模考", "可行——用限时模考检验稳定性"
    else:
        stage, readiness = "考前收窄", "已达掌握线——维持节奏，别再扩张新内容"

    return {
        "subject_id": subject_id,
        "total_score": total_score,
        "kpi": {
            "kp_total": len(stats),
            "kp_attempted": attempted_kps,
            "coverage": round(overall_cov, 4),
            "attempts": tot_attempts,
            "accuracy": round(overall_acc, 4),
            "mastery": round(overall_mastery, 4),
            "correct_records": tot_correct,
            "has_correct_records": has_correct_records,
            "by_source": dict(by_source),
            "manual_records": manual_n,
            "reconstructed_records": recon_n,
        },
        "data_note": data_note,
        "lines": {"pass": PASS_LINE, "safe": SAFE_LINE, "mastery": MASTERY_LINE},
        "stage": stage,
        "readiness": readiness,
        "knowledge_points": [s.__dict__ for s in stats],
    }
