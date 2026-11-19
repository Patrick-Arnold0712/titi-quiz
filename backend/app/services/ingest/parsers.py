from __future__ import annotations

from pathlib import Path

from app.services.ingest.ocr import ocr_image, ocr_pdf

SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".bmp", ".webp"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def sanitize(text: str) -> str:
    """去掉非法 Unicode（如 OCR 产生的孤立代理字符），保证可写库。"""

    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("utf-8", "ignore").decode("utf-8", "ignore")


def extract_text(
    path: str | Path,
    *,
    ocr_fallback: bool = True,
    min_chars: int = 20,
) -> str:
    """按扩展名抽取纯文本；图片型 PDF / 图片自动走 OCR。"""

    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".pdf":
        text = _extract_pdf(p)
        if ocr_fallback and len(text.strip()) < min_chars:
            ocr_text = _safe_ocr_pdf(p)
            if len(ocr_text.strip()) > len(text.strip()):
                return sanitize(ocr_text)
        return sanitize(text)
    if suffix == ".docx":
        return sanitize(_extract_docx(p))
    if suffix in IMAGE_SUFFIXES:
        return sanitize("\n".join(ocr_image(p)))
    if suffix in (".txt", ".md"):
        return sanitize(p.read_text(encoding="utf-8", errors="ignore"))
    raise ValueError(f"暂不支持的格式：{suffix}（支持 {', '.join(sorted(SUPPORTED))}）")


def _safe_ocr_pdf(p: Path) -> str:
    try:
        return ocr_pdf(p)
    except Exception:  # noqa: BLE001   OCR 失败不应阻断，退回空文本
        return ""


def _extract_pdf(p: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(p))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _extract_docx(p: Path) -> str:
    import docx

    document = docx.Document(str(p))
    return "\n".join(par.text for par in document.paragraphs)


def chunk_text(text: str, *, size: int = 800, overlap: int = 100) -> list[str]:
    """按字符切块，带重叠，避免句子被硬切断带来的语义损失。"""

    text = sanitize(text).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text)
    step = max(1, size - overlap)
    while start < n:
        end = min(start + size, n)
        chunks.append(text[start:end])
        if end >= n:
            break
        start += step
    return chunks
