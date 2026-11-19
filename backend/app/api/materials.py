"""上传先预览，显式确认后才写题库。"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models.entities import Chunk, DocStatus, Document, SourceType, Subject
from app.services import search
from app.services.ingest.materials import (
    IMPORT_MARK, MAX_BYTES, MAX_CHARS, MAX_PAGES, MAX_PDF_BYTES, book_questions, extract_pages,
    parse_workbook, textbook_chunks, validate_pages,
)
from app.services.ingest.parsers import IMAGE_SUFFIXES, SUPPORTED, chunk_text

router = APIRouter(prefix="/material-import", tags=["material-import"])
log = logging.getLogger(__name__)
Kind = Literal["textbook", "workbook"]
TTL = 24 * 3600
_extract_lock = threading.Lock()
_commit_lock = threading.Lock()


class Review(BaseModel):
    pages: list[Annotated[str, StringConstraints(max_length=MAX_CHARS)]] = Field(min_length=1, max_length=MAX_PAGES)
    chapter: str = Field(default="", max_length=120)
    make_paper: bool = False


def _drafts() -> Path:
    path = get_settings().upload_dir / "material-drafts"
    path.mkdir(exist_ok=True)
    return path


def _load(token: UUID) -> tuple[Path, dict]:
    folder = _drafts() / token.hex
    manifest = folder / "manifest.json"
    try:
        if time.time() - manifest.stat().st_mtime <= TTL:
            return folder, json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    raise HTTPException(404, "导入草稿不存在或已过期，请重新上传")


def _review(kind: Kind, pages: list[str]) -> tuple[dict, list[dict]]:
    try:
        validate_pages(pages)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    rows = parse_workbook(pages) if kind == "workbook" else []
    valid = [r for r in rows if not r["issues"]]
    invalid = [r for r in rows if r["issues"]]
    return {
        "candidate_count": len(rows), "usable_count": len(valid), "invalid_count": len(invalid),
        "issues": [{k: r[k] for k in ("number", "page", "issues")} for r in invalid[:30]],
        "sample": [{**r, "stem": r["stem"][:400], "answer": r["answer"][:200],
                    "explanation": r["explanation"][:300],
                    "options": [{**o, "text": o["text"][:200]} for o in r["options"][:8]]}
                   for r in valid[:5]],
    }, rows


@router.post("/preview")
def preview(
    subject_id: Annotated[int, Form()], kind: Annotated[Kind, Form()],
    file: Annotated[UploadFile, File()], force_ocr: Annotated[bool, Form()] = False,
    db: Session = Depends(get_db),
):
    if db.get(Subject, subject_id) is None:
        raise HTTPException(404, "学科不存在")
    db.rollback()
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(415, "不支持的资料格式")
    byte_limit = MAX_PDF_BYTES if suffix == ".pdf" else MAX_BYTES
    size_error = f"单份{' PDF' if suffix == '.pdf' else '资料'}不能超过 {byte_limit // (1024 * 1024)} MiB，请拆分后再上传"
    if file.size is not None and file.size > byte_limit:
        raise HTTPException(413, size_error)
    root = _drafts()
    if not _extract_lock.acquire(blocking=False):
        raise HTTPException(429, "已有资料正在识别，请稍后重试")
    token = uuid4()
    folder = root / token.hex
    try:
        # 路径只用服务器生成的 ID；同名文件不会相互覆盖。
        for entry in root.iterdir():
            if (re.fullmatch(r"[0-9a-f]{32}", entry.name) and entry.is_dir()
                    and not entry.is_symlink() and time.time() - entry.stat().st_mtime > TTL):
                shutil.rmtree(entry, ignore_errors=True)
        folder.mkdir()
        source = folder / f"source{suffix}"
        total, digest = 0, hashlib.sha256()
        with source.open("xb") as out:
            while data := file.file.read(1024 * 1024):
                total += len(data)
                if total > byte_limit:
                    raise HTTPException(413, size_error)
                digest.update(data)
                out.write(data)
        if not total:
            raise HTTPException(422, "文件为空")
        try:
            pages, scanned = extract_pages(source, force_ocr)
        except ImportError as exc:
            raise HTTPException(503, "服务端缺少 OCR/PDF 依赖，请安装 backend/requirements-ocr.txt") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            log.exception("资料识别失败")
            raise HTTPException(422, "资料识别失败，请检查文件是否损坏，或转成 UTF-8 文本后重试") from exc
        report, _ = _review(kind, pages)
        meta = dict(subject_id=subject_id, kind=kind, filename=filename[:255], suffix=suffix,
                    sha256=digest.hexdigest(), page_count=len(pages), ocr_pages=scanned)
        (folder / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return {"draft_id": token, "pages": pages, **meta, **report}
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        _extract_lock.release()


@router.post("/{draft_id}/check")
def check(draft_id: UUID, payload: Review):
    _, meta = _load(draft_id)
    if len(payload.pages) != meta["page_count"]:
        raise HTTPException(422, "请保留原有页数，以便追溯来源")
    report, _ = _review(meta["kind"], payload.pages)
    return report


@router.post("/{draft_id}/commit")
def commit(draft_id: UUID, payload: Review, db: Session = Depends(get_db)):
    with _commit_lock:
        folder, meta = _load(draft_id)
        if len(payload.pages) != meta["page_count"]:
            raise HTTPException(422, "请保留原有页数，以便追溯来源")
        report, rows = _review(meta["kind"], payload.pages)
        sid = meta["subject_id"]
        if db.get(Subject, sid) is None:
            raise HTTPException(404, "学科不存在")
        for existing in db.query(Document).filter_by(subject_id=sid).all():
            info = existing.meta or {}
            if info.get("pipeline") == IMPORT_MARK and (info.get("sha256"), info.get("kind")) == (meta["sha256"], meta["kind"]):
                return {"document_id": existing.id, "already_imported": True, **info["result"]}
        if meta["kind"] == "workbook" and not report["usable_count"]:
            raise HTTPException(422, "没有可入库的题，请先补齐题型、选项和答案，再重新检查")

        suffix = meta["suffix"]
        originals = get_settings().upload_dir / "materials"
        originals.mkdir(exist_ok=True)
        dest = originals / f"{draft_id.hex}{suffix}"
        title = Path(meta["filename"]).stem or "导入资料"
        doc = Document(subject_id=sid, filename=meta["filename"], title=title,
                       path=str(dest), doc_type="img" if suffix in IMAGE_SUFFIXES else suffix[1:],
                       status=DocStatus.indexed, source_type=SourceType.own_material)
        db.add(doc)
        db.flush()
        result = dict(chunk_count=0, question_count=0, duplicates=0, paper_id=None,
                      skipped=report["invalid_count"])
        if meta["kind"] == "textbook":
            result["chunk_count"] = textbook_chunks(db, doc, payload.pages, payload.chapter.strip(), suffix == ".pdf")
        else:
            result.update(book_questions(db, doc, rows, payload.chapter.strip(), payload.make_paper))
            index = 0
            for pno, page in enumerate(payload.pages, 1):
                for part in chunk_text(page):
                    db.add(Chunk(document_id=doc.id, order_index=index, content=part, char_count=len(part),
                                 page_no=pno if suffix == ".pdf" else None))
                    index += 1
            result["chunk_count"] = index
        doc.meta = {"pipeline": IMPORT_MARK, **meta, "result": result}
        doc_id = doc.id
        try:
            shutil.copyfile(folder / f"source{suffix}", dest)
            db.commit()
        except BaseException:
            db.rollback()
            dest.unlink(missing_ok=True)
            raise
        search.invalidate()
        return {"document_id": doc_id, "already_imported": False, **result}
