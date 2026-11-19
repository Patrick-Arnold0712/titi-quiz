from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Chapter, KnowledgePoint, Question, Subject
from app.schemas.dto import AnalysisOut, ChapterCoverage, KnowledgePointOut

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/{subject_id}", response_model=AnalysisOut)
def analyze_subject(subject_id: int, db: Session = Depends(get_db)):
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="学科不存在")

    chapters = (
        db.query(Chapter)
        .filter(Chapter.subject_id == subject_id)
        .order_by(Chapter.order_index)
        .all()
    )
    kps = db.query(KnowledgePoint).filter(KnowledgePoint.subject_id == subject_id).all()
    questions = db.query(Question).filter(Question.subject_id == subject_id).all()

    q_by_kp: dict[int, int] = {}
    for q in questions:
        if q.kp_id is not None:
            q_by_kp[q.kp_id] = q_by_kp.get(q.kp_id, 0) + 1

    by_chapter: list[ChapterCoverage] = []
    for ch in chapters:
        ch_kps = [k for k in kps if k.chapter_id == ch.id]
        qcount = sum(q_by_kp.get(k.id, 0) for k in ch_kps)
        by_chapter.append(
            ChapterCoverage(
                chapter_id=ch.id,
                chapter_name=ch.name,
                kp_count=len(ch_kps),
                question_count=qcount,
                covered=qcount > 0,
            )
        )

    kp_total = len(kps)
    kp_covered = sum(1 for k in kps if q_by_kp.get(k.id, 0) > 0)
    coverage_rate = (kp_covered / kp_total) if kp_total else 0.0
    top = sorted(kps, key=lambda k: (q_by_kp.get(k.id, 0), k.frequency), reverse=True)[:10]

    return AnalysisOut(
        subject_id=subject_id,
        total_knowledge_points=kp_total,
        total_questions=len(questions),
        coverage_rate=round(coverage_rate, 4),
        by_chapter=by_chapter,
        top_knowledge_points=[KnowledgePointOut.model_validate(k) for k in top],
    )
