from __future__ import annotations

import tempfile
from pathlib import Path

_ENGINE = None


def get_engine():
    """懒加载 OCR 引擎（首次调用会载入模型）。"""

    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _run(engine, image_path: str) -> list[str]:
    result = engine(image_path)
    data = result[0] if isinstance(result, tuple) else result
    if not data:
        return []
    return [str(item[1]) for item in data]


def ocr_image(path: str | Path) -> list[str]:
    """识别单张图片，返回文本行。"""

    return _run(get_engine(), str(path))


def ocr_pdf(path: str | Path, *, dpi: int = 200, max_pages: int | None = None) -> str:
    """把 PDF 每页渲染成图片后逐页 OCR，返回拼接文本。"""

    import pymupdf

    engine = get_engine()
    doc = pymupdf.open(str(path))
    lines: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        total = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
        for i in range(total):
            pix = doc[i].get_pixmap(dpi=dpi)
            tmp = Path(tmpdir) / f"page_{i}.png"
            pix.save(str(tmp))
            lines.extend(_run(engine, str(tmp)))
    doc.close()
    return "\n".join(lines)
