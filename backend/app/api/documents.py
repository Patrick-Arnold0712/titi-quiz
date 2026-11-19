from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models.entities import Chapter, Chunk, DocStatus, Document, Question, SourceType
from app.schemas.dto import DocumentOut
from app.services.extract import parse_questions, stitch_chunks
from app.services.ingest import chunk_text, extract_text
from app.services.ingest.materials import IMPORT_MARK, MAX_BYTES
from app.services.ingest.parsers import IMAGE_SUFFIXES, SUPPORTED

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
def list_documents(subject_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Document)
    if subject_id is not None:
        q = q.filter(Document.subject_id == subject_id)
    return q.order_by(Document.id.desc()).all()


@router.post("/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    subject_id: int | None = Form(None),
    source_type: str = Form("own_material"),
    year: str | None = Form(None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    filename = (file.filename or "unnamed").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(415, "不支持的资料格式")
    try:
        st = SourceType(source_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"非法 source_type：{source_type}")

    dest = settings.upload_dir / f"{uuid4().hex}{suffix}"
    doc = Document(
        subject_id=subject_id,
        title=Path(filename).stem,
        filename=filename,
        path=str(dest),
        doc_type="img" if suffix in IMAGE_SUFFIXES else suffix.lstrip("."),
        source_type=st,
        year=year,
        status=DocStatus.uploaded,
    )
    try:
        with dest.open("xb") as out:
            total = 0
            while data := await file.read(1024 * 1024):
                total += len(data)
                if total > MAX_BYTES:
                    raise HTTPException(413, "单份资料不能超过 30 MiB")
                out.write(data)
        if not total:
            raise HTTPException(422, "文件为空")
        db.add(doc)
        db.commit()
    except BaseException:
        db.rollback()
        dest.unlink(missing_ok=True)
        raise
    db.refresh(doc)
    return doc


@router.post("/{doc_id}/parse", response_model=DocumentOut)
def parse_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    if (doc.meta or {}).get("pipeline") == IMPORT_MARK:
        raise HTTPException(409, "分科导入资料已校对入库，不能通过旧接口覆盖")
    try:
        text = extract_text(doc.path)
        pieces = chunk_text(text)
        db.query(Chunk).filter(Chunk.document_id == doc.id).delete()
        for i, c in enumerate(pieces):
            db.add(Chunk(document_id=doc.id, order_index=i, content=c, char_count=len(c)))
        doc.status = DocStatus.parsed
        doc.meta = {"char_count": len(text), "chunk_count": len(pieces)}
        db.commit()
        db.refresh(doc)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        doc = db.get(Document, doc_id)
        if doc is not None:
            doc.status = DocStatus.failed
            doc.meta = {"error": str(exc)[:300]}
            db.commit()
        raise HTTPException(status_code=400, detail=f"解析失败：{exc}")
    return doc


@router.get("/{doc_id}/chunks")
def get_chunks(doc_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(Chunk)
        .filter(Chunk.document_id == doc_id)
        .order_by(Chunk.order_index)
        .all()
    )
    return [{"id": r.id, "order_index": r.order_index, "content": r.content} for r in rows]


@router.post("/{doc_id}/extract-questions")
def extract_questions(doc_id: int, subject_id: int | None = None, db: Session = Depends(get_db)):
    """从资料文本中结构化抽取题目入库。"""

    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    if (doc.meta or {}).get("pipeline") == IMPORT_MARK:
        raise HTTPException(409, "分科导入资料已校对入库，不能通过旧接口重复抽题")
    sid = subject_id or doc.subject_id

    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == doc_id)
        .order_by(Chunk.order_index)
        .all()
    )
    if not chunks:
        raise HTTPException(status_code=400, detail="请先解析该资料")

    text = stitch_chunks([c.content for c in chunks])
    parsed = parse_questions(text)

    chapters = (
        db.query(Chapter).filter(Chapter.subject_id == sid).all() if sid is not None else []
    )
    existing = {
        "".join(q.stem.split())
        for q in db.query(Question).filter(Question.subject_id == sid).all()
    }

    created = 0
    for item in parsed:
        stem = item["stem"].strip()
        key = "".join(stem.split())
        if not key or key in existing:
            continue
        chapter_id = None
        if item.get("chapter"):
            for ch in chapters:
                if item["chapter"] in ch.name:
                    chapter_id = ch.id
                    break
        db.add(
            Question(
                subject_id=sid,
                chapter_id=chapter_id,
                qtype=item["qtype"],
                stem=stem,
                options=item["options"] or None,
                answer=item.get("answer") or "",
                source_type=doc.source_type,
                year=doc.year,
                document_id=doc.id,
            )
        )
        existing.add(key)
        created += 1
    db.commit()
    return {"parsed": len(parsed), "created": created, "skipped": len(parsed) - created}
