from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Attempt, Question, QuestionType, SourceType
from app.schemas.dto import AttemptCreate, AttemptOut, QuestionCreate, QuestionOut, question_out
from app.services.paper.scoring import OBJECTIVE, judge_objective

router = APIRouter(prefix="/questions", tags=["questions"])


def judge(question: Question, user_answer: str) -> bool:
    """单题判分。

    **不要在这里再写一套比较逻辑** —— 这里原先自己实现了一份，没有做判断题的
    A/B 归一化，导致判断题怎么答都判错（答案写作 √ / 正确 时永远比不上 "A"）。
    现在客观题一律走 `judge_objective`，与交卷判分共用同一个口径。
    """
    if question.qtype in OBJECTIVE:
        return judge_objective(question, user_answer)
    # 非客观题（简答 / 论述）：不自动判分，这里只做字符串级兜底比较
    return (user_answer or "").strip().upper() == (question.answer or "").strip().upper()


@router.get("", response_model=list[QuestionOut])
def list_questions(
    subject_id: int | None = None,
    chapter_id: int | None = None,
    kp_id: int | None = None,
    qtype: QuestionType | None = None,
    source_type: SourceType | None = None,
    wrong_only: bool = False,
    has_answer: bool | None = None,
    shuffle: bool = False,
    limit: int = 100,
    offset: int = 0,
    # 题面残缺的题（设空丢了、选项没拆出来）**默认根本不返回**。
    # 以前是「返回 + 前端标红提示跳过」，但用户的实际反馈是：
    # 出现在列表里就是污染 —— 一屏 15 道里混进 1 道坏题，用户得自己分辨，
    # 而且「还有 N 道没做」那个数还把它算进去了。
    # 需要看它们做质检时传 include_defective=true。
    include_defective: bool = False,
    db: Session = Depends(get_db),
):
    q = db.query(Question)
    if subject_id is not None:
        q = q.filter(Question.subject_id == subject_id)
    if chapter_id is not None:
        q = q.filter(Question.chapter_id == chapter_id)
    if kp_id is not None:
        q = q.filter(Question.kp_id == kp_id)
    if qtype is not None:
        q = q.filter(Question.qtype == qtype)
    if source_type is not None:
        q = q.filter(Question.source_type == source_type)
    if has_answer is not None:
        if has_answer:
            q = q.filter(Question.answer.isnot(None), Question.answer != "")
        else:
            q = q.filter((Question.answer.is_(None)) | (Question.answer == ""))
    if wrong_only:
        # 只要「错过且最近一次仍是错的」题 —— 比「曾经错过」更紧急
        last = (
            db.query(
                Attempt.question_id.label("qid"),
                func.max(Attempt.created_at).label("last_at"),
            )
            .group_by(Attempt.question_id)
            .subquery()
        )
        q = (
            q.join(last, last.c.qid == Question.id)
            .join(
                Attempt,
                (Attempt.question_id == Question.id)
                & (Attempt.created_at == last.c.last_at)
                & (Attempt.is_correct.is_(False)),
            )
        )
    if shuffle:
        q = q.order_by(func.random())
    else:
        q = q.order_by(Question.id.desc())

    from app.services.quality import check as quality_check

    if include_defective and not wrong_only:
        rows = q.offset(offset).limit(limit).all()
    else:
        # 体检结论是**运行时算的**（quality 不是数据库列），只能在 Python 侧过滤。
        # 所以要多取几倍再截断 —— 否则 limit=100 可能只回来 60 道，
        # 「这次刷 15 道」会莫名其妙变少。实测残缺率约 21%，4 倍足够。
        rows = q.offset(offset).limit(max(limit * 4, limit + 200)).all()
        # 错题本同样要滤：那不是用户做错，是题有毛病。
        # 判分那边已经把这类题排除在计分外了，这里口径必须一致。
        rows = [x for x in rows if quality_check(x).usable][:limit]
    return [question_out(x) for x in rows]


@router.post("", response_model=QuestionOut, status_code=201)
def create_question(payload: QuestionCreate, db: Session = Depends(get_db)):
    obj = Question(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return question_out(obj)


@router.get("/{question_id}", response_model=QuestionOut)
def get_question(question_id: int, db: Session = Depends(get_db)):
    obj = db.get(Question, question_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return question_out(obj)


@router.post("/{question_id}/attempt", response_model=AttemptOut, status_code=201)
def submit_attempt(question_id: int, payload: AttemptCreate, db: Session = Depends(get_db)):
    obj = db.get(Question, question_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    att = Attempt(
        question_id=question_id,
        user_answer=payload.user_answer,
        is_correct=judge(obj, payload.user_answer),
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att
