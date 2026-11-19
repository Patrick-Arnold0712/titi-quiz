from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Subject
from app.schemas.dto import SubjectCreate, SubjectDetail, SubjectOut

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.get("", response_model=list[SubjectOut])
def list_subjects(db: Session = Depends(get_db)):
    return db.query(Subject).order_by(Subject.id).all()


@router.post("", response_model=SubjectOut, status_code=201)
def create_subject(payload: SubjectCreate, db: Session = Depends(get_db)):
    if db.query(Subject).filter(Subject.code == payload.code).one_or_none():
        raise HTTPException(status_code=400, detail="code 已存在")
    obj = Subject(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{subject_id}", response_model=SubjectDetail)
def get_subject(subject_id: int, db: Session = Depends(get_db)):
    obj = db.get(Subject, subject_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="学科不存在")
    return obj
