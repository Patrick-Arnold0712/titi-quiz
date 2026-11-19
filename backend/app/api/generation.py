from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Question, SourceType, Subject
from app.schemas.dto import GenerateRequest, QuestionOut
from app.services.generation import build_generation_prompt, parse_generated_questions
from app.services.llm import get_llm_client

router = APIRouter(prefix="/generate", tags=["generation"])


@router.post("", response_model=list[QuestionOut])
def generate(req: GenerateRequest, persist: bool = True, db: Session = Depends(get_db)):
    subject = db.get(Subject, req.subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="学科不存在")

    llm = get_llm_client()
    messages = build_generation_prompt(db, req)
    raw = llm.chat_json(messages)
    items = parse_generated_questions(raw)

    created: list[Question] = []
    for item in items:
        stem = str(item.get("stem", "")).strip()
        if not stem:
            continue
        options = item.get("options")
        if options is not None and not isinstance(options, list):
            options = None
        obj = Question(
            subject_id=req.subject_id,
            chapter_id=req.chapter_id,
            kp_id=req.kp_id,
            qtype=req.qtype,
            stem=stem,
            options=options,
            answer=str(item.get("answer", "")),
            explanation=item.get("explanation"),
            difficulty=float(item.get("difficulty", req.difficulty) or req.difficulty),
            source_type=SourceType.generated,
            tags=item.get("tags"),
        )
        db.add(obj)
        created.append(obj)

    if persist and created:
        db.commit()
        for obj in created:
            db.refresh(obj)
    else:
        db.rollback()
    return created
