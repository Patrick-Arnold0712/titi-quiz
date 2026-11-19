"""判分：客观题自动批改，主观题按既定策略登记待人工。

判分口径（来自官方考试说明与真题卷面）：
- 单选 / 判断：答案完全一致得分
- **不定项选择：错选、漏选均不得分**，即必须与标准答案完全一致
- 简答 / 论述：**不做自动批改**（决策 5C），只登记满分与参考答案，供人工确认

主观题不批分是有意为之：自动打分一旦不准，会让「掌握度」和「复习建议」整体失真。
宁可留空并标注待人工，也不给一个看起来像分数、其实是猜的数字。
"""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy.orm import Session

from app.services.ingest.textnorm import normalize_bool
from app.services.quality import check as quality_check

from app.models.entities import (
    Attempt,
    Paper,
    PaperAttempt,
    PaperItem,
    Question,
    QuestionType,
)

OBJECTIVE = {QuestionType.single_choice, QuestionType.multi_choice, QuestionType.true_false}
SUBJECTIVE = {QuestionType.short_answer, QuestionType.essay}

LETTERS = re.compile(r"[A-H]")


def normalize_letters(text: str) -> str:
    """把 A,B,C / abc / a b c 统一成排序后的 'ABC'。"""
    return "".join(sorted(set(LETTERS.findall((text or "").upper()))))


def judge_objective(question: Question, user_answer: str) -> bool:
    """判断客观题对错。主观题调用会抛 ValueError。"""
    if question.qtype not in OBJECTIVE:
        raise ValueError(f"非客观题，不能自动判分：{question.qtype}")

    if question.qtype == QuestionType.true_false:
        ua = normalize_bool(user_answer)
        ca = normalize_bool(question.answer or "")
        return ua is not None and ca is not None and ua == ca

    ua = normalize_letters(user_answer)
    ca = normalize_letters(question.answer or "")
    return bool(ca) and ua == ca


def score_paper_attempt(db: Session, pa: PaperAttempt) -> dict:
    """给一份答卷判分，写回 Attempt.awarded_score / is_correct，并汇总。"""
    paper: Paper = pa.paper
    items = (
        db.query(PaperItem)
        .filter(PaperItem.paper_id == paper.id)
        .order_by(PaperItem.order_index)
        .all()
    )
    qids = [it.question_id for it in items]
    qmap = {q.id: q for q in db.query(Question).filter(Question.id.in_(qids)).all()}
    anspool = {a.question_id: a for a in pa.answers}

    per_section: dict[str, dict] = defaultdict(
        lambda: {"section": "", "total": 0.0, "got": 0.0, "right": 0, "count": 0,
                 "pending": 0, "defective": 0, "defective_total": 0.0}
    )
    score = obj_total = sub_total = defective_total = 0.0
    right = wrong = pending = defective = 0

    for it in items:
        q = qmap.get(it.question_id)
        if q is None:
            continue
        a: Attempt | None = anspool.get(it.question_id)
        sec = per_section[it.section_name or "未分大题"]
        sec["section"] = it.section_name or "未分大题"
        sec["count"] += 1

        # 题面残缺：用户根本没法作答（选项没拆出来、设空丢了）。
        # 这种题既不能算对，也**不能算错** —— 算错会把它塞进错题本，
        # 用户明明会做，却因为题本身的毛病被记成薄弱点，反过来污染掌握度。
        # 所以单独计数，并且从「可判分总分」里剔除（连分段满分也要扣掉，
        # 否则会出现「18/40」这种分母里混着 12 分不可能拿到的分）。
        verdict = quality_check(q)
        if not verdict.usable:
            defective += 1
            defective_total += it.score_per
            sec["defective"] += 1
            sec["defective_total"] += it.score_per
            if a is not None:
                a.is_correct = None
                a.awarded_score = 0.0
            continue

        sec["total"] += it.score_per

        if q.qtype in SUBJECTIVE:
            sub_total += it.score_per
            sec["pending"] += 1
            pending += 1
            if a is not None:
                a.is_correct = None
                a.awarded_score = 0.0
            continue

        obj_total += it.score_per
        got = 0.0
        answered = a is not None and (a.user_answer or "").strip() != ""
        if not answered:
            # 未作答：按错计，不参与正确数
            wrong += 1
            if a is not None:
                a.is_correct = False
                a.awarded_score = 0.0
            continue
        try:
            ok = judge_objective(q, a.user_answer or "")
        except ValueError:
            ok = False
        a.is_correct = ok
        if ok:
            got = it.score_per
            sec["right"] += 1
            right += 1
        else:
            wrong += 1
        a.awarded_score = got
        sec["got"] += got
        score += got

    detail = {
        "sections": list(per_section.values()),
        "objective_total": round(obj_total, 2),
        "subjective_total": round(sub_total, 2),
        "objective_score": round(score, 2),
        "right": right,
        "wrong": wrong,
        "pending_manual": pending,
        # 题面残缺、无法判分的题数与分值 —— 必须让用户看见，
        # 否则他会以为这些分是自己丢的
        "defective": defective,
        "defective_total": round(defective_total, 2),
    }
    pa.score = round(score, 2)
    pa.objective_total = round(obj_total, 2)
    pa.subjective_total = round(sub_total, 2)
    pa.detail = detail
    return detail
