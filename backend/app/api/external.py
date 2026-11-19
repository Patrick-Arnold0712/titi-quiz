"""供外部程序接入的只读题库接口。

和站内 `/api/questions` 的区别：

- 只返回通过 quality 检查的题；
- 固定返回题目所属学科、单元、课文、考点和选项文本，外部程序不用自己拼；
- 默认允许局域网/本机访问；设置 `TTK_EXTERNAL_API_KEY` 后要求 `X-API-Key`；
- 另提供 `/api/external/export/sqlite`，可直接下载只读 SQLite 文件。
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.core.db import get_db
from app.models.entities import (
    Chapter,
    KnowledgePoint,
    Question,
    QuestionType,
    Subject,
    canon_qtype,
)
from app.services.external_export import ensure_export
from app.services.ingest.textnorm import shape_true_false
from app.services.quality import check as quality_check

router = APIRouter(prefix="/external", tags=["external"])

EXPORT_PATH = PROJECT_ROOT / "exports" / "ttk_quiz.db"


def require_external_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected = os.getenv("TTK_EXTERNAL_API_KEY", "").strip()
    if expected and not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="缺少或错误的 X-API-Key")


def _unit_map(chapters: list[Chapter]) -> tuple[dict[int, Chapter], dict[int, Chapter]]:
    by_id = {c.id: c for c in chapters}
    units = {c.id: c for c in chapters if c.parent_id is None}
    return by_id, units


def _unit_of(chapter: Chapter | None, by_id: dict[int, Chapter], units: dict[int, Chapter]) -> Chapter | None:
    if chapter is None:
        return None
    return units.get(chapter.parent_id) if chapter.parent_id else chapter


def _options(q: Question) -> list[dict]:
    raw = q.options or []
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    out = []
    for i, item in enumerate(raw if isinstance(raw, list) else []):
        if isinstance(item, dict):
            out.append({"key": str(item.get("key") or chr(65 + i)), "text": str(item.get("text") or "")})
        else:
            out.append({"key": chr(65 + i), "text": str(item)})
    return out


def _shape(q: Question) -> tuple[list[dict], str]:
    opts, answer = _options(q), q.answer or ""
    if canon_qtype(q.qtype) == "true_false":
        opts, answer = shape_true_false(opts, answer)
    return opts, answer


def _answer_text(q: Question, opts: list[dict], answer: str) -> str:
    qtype = canon_qtype(q.qtype)
    if qtype == "fill_blank" or not opts:
        return answer
    mapping = {o["key"]: o["text"] for o in opts}
    letters = "".join(sorted(set(ch for ch in answer.upper() if "A" <= ch <= "H")))
    return "  ".join(f"{k}. {mapping[k]}" for k in letters if k in mapping)


def _question_payload(q: Question, subject: Subject | None, by_id: dict[int, Chapter],
                      units: dict[int, Chapter], kp: KnowledgePoint | None) -> dict:
    chapter = by_id.get(q.chapter_id)
    unit = _unit_of(chapter, by_id, units)
    opts, answer = _shape(q)
    return {
        "id": q.id,
        "subject": {"id": subject.id, "code": subject.code, "name": subject.name} if subject else None,
        "unit": {"id": unit.id, "name": unit.name} if unit else None,
        "lesson": {"id": chapter.id, "name": chapter.name} if chapter else None,
        "knowledge_point": {"id": kp.id, "name": kp.name} if kp else None,
        "qtype": canon_qtype(q.qtype),
        "stem": q.stem,
        "options": opts,
        "answer": answer,
        "answer_text": _answer_text(q, opts, answer),
        "explanation": q.explanation,
        "source_type": q.source_type.value if hasattr(q.source_type, "value") else q.source_type,
        "year": q.year,
        "tags": q.tags,
    }


@router.get("/meta")
def external_meta(db: Session = Depends(get_db), _: None = Depends(require_external_key)):
    total = 0
    for q in db.query(Question).all():
        if quality_check(q).usable:
            total += 1
    return {
        "name": "题题的库 · 外部题库",
        "schema_version": 1,
        "subjects": db.query(Subject).count(),
        "questions": total,
        "export": "/api/external/export/sqlite",
        "auth": "设置 TTK_EXTERNAL_API_KEY 后，请求头加 X-API-Key",
    }


@router.get("/subjects")
def external_subjects(db: Session = Depends(get_db), _: None = Depends(require_external_key)):
    return [
        {"id": s.id, "code": s.code, "name": s.name, "exam_name": s.exam_name,
         "description": s.description}
        for s in db.query(Subject).order_by(Subject.id)
    ]


@router.get("/chapters")
def external_chapters(
    subject_id: int | None = None,
    level: int | None = Query(default=None, ge=1, le=2),
    db: Session = Depends(get_db),
    _: None = Depends(require_external_key),
):
    q = db.query(Chapter)
    if subject_id is not None:
        q = q.filter(Chapter.subject_id == subject_id)
    rows = q.order_by(Chapter.order_index, Chapter.id).all()
    if level == 1:
        rows = [c for c in rows if c.parent_id is None]
    elif level == 2:
        rows = [c for c in rows if c.parent_id is not None]
    return [
        {"id": c.id, "subject_id": c.subject_id, "parent_id": c.parent_id,
         "level": 1 if c.parent_id is None else 2, "name": c.name,
         "order_index": c.order_index, "summary": c.summary, "page_start": c.page_start}
        for c in rows
    ]


@router.get("/knowledge-points")
def external_kps(
    subject_id: int | None = None,
    chapter_id: int | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_external_key),
):
    q = db.query(KnowledgePoint)
    if subject_id is not None:
        q = q.filter(KnowledgePoint.subject_id == subject_id)
    if chapter_id is not None:
        q = q.filter(KnowledgePoint.chapter_id == chapter_id)
    return [
        {"id": k.id, "subject_id": k.subject_id, "chapter_id": k.chapter_id,
         "name": k.name, "description": k.description, "importance": k.importance,
         "page_start": k.page_start, "page_end": k.page_end}
        for k in q.order_by(KnowledgePoint.page_start, KnowledgePoint.id)
    ]


@router.get("/questions")
def external_questions(
    subject_id: int | None = None,
    chapter_id: int | None = None,
    kp_id: int | None = None,
    qtype: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: None = Depends(require_external_key),
):
    q = db.query(Question)
    if subject_id is not None:
        q = q.filter(Question.subject_id == subject_id)
    if chapter_id is not None:
        q = q.filter(Question.chapter_id == chapter_id)
    if kp_id is not None:
        q = q.filter(Question.kp_id == kp_id)
    if qtype:
        try:
            qt = QuestionType(canon_qtype(qtype))
        except ValueError:
            raise HTTPException(400, f"未知 qtype：{qtype}")
        q = q.filter(Question.qtype == qt)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Question.stem.like(like), Question.explanation.like(like)))

    rows = q.order_by(Question.id).all()
    usable = [x for x in rows if quality_check(x).usable]
    total = len(usable)
    page = usable[offset:offset + limit]
    subjects = {s.id: s for s in db.query(Subject).all()}
    chapters = db.query(Chapter).all()
    by_id, units = _unit_map(chapters)
    kps = {k.id: k for k in db.query(KnowledgePoint).all()}
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            _question_payload(x, subjects.get(x.subject_id), by_id, units,
                              kps.get(x.kp_id) if x.kp_id else None)
            for x in page
        ],
    }


@router.get("/questions/{question_id}")
def external_question(question_id: int, db: Session = Depends(get_db),
                      _: None = Depends(require_external_key)):
    q = db.get(Question, question_id)
    if q is None or not quality_check(q).usable:
        raise HTTPException(404, "题目不存在或不可用")
    subject = db.get(Subject, q.subject_id) if q.subject_id else None
    chapters = db.query(Chapter).all()
    by_id, units = _unit_map(chapters)
    kp = db.get(KnowledgePoint, q.kp_id) if q.kp_id else None
    return _question_payload(q, subject, by_id, units, kp)


@router.get("/export/sqlite")
def export_sqlite(_: None = Depends(require_external_key)):
    info = ensure_export(EXPORT_PATH)
    if not Path(info["path"]).exists():
        raise HTTPException(500, "导出失败")
    return FileResponse(
        info["path"],
        media_type="application/vnd.sqlite3",
        filename="ttk_quiz.db",
    )
