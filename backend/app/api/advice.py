"""备考建议 API（功能 4）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Subject
from app.services.advice import analyze_subject, build_advice

router = APIRouter(prefix="/advice", tags=["advice"])


@router.get("/{subject_id}/analysis")
def api_analysis(subject_id: int, total_score: float = 100.0, db: Session = Depends(get_db)):
    """考点掌握度矩阵（事实层，不含建议）。"""
    if db.get(Subject, subject_id) is None:
        raise HTTPException(404, "学科不存在")
    return analyze_subject(db, subject_id, total_score)


@router.get("/{subject_id}")
def api_advice(
    subject_id: int,
    total_score: float = 100.0,
    days: int = 7,
    daily_minutes: int = 90,
    db: Session = Depends(get_db),
):
    """完整备考建议：ROI 冲刺清单 + 章节风险 + 必背清单 + 时间计划。"""
    if db.get(Subject, subject_id) is None:
        raise HTTPException(404, "学科不存在")
    return build_advice(db, subject_id, total_score, days, daily_minutes)
