"""刷题记录导入 API。

从参考站把 `jlq_v1` 记录导进来：要么粘贴 JSON，要么粘贴「导出」下载的文本。
安装器会自动识别格式。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Subject
from app.services.imports.jlq import (
    detect_format,
    import_export_text,
    import_jlq,
    import_qnum_list,
    import_wrong_page,
    parse_export_text,
    parse_qnum_list,
    parse_wrong_page,
)

router = APIRouter(prefix="/import", tags=["import"])


class JlqImportRequest(BaseModel):
    subject_id: int = 1
    payload: str
    replace: bool = False
    apply: bool = False


@router.post("/jlq")
def api_import_jlq(req: JlqImportRequest, db: Session = Depends(get_db)):
    """导入刷题记录。apply=False（默认）只做预览。"""
    if db.get(Subject, req.subject_id) is None:
        raise HTTPException(404, "学科不存在")
    if not req.payload.strip():
        raise HTTPException(400, "内容为空")

    fmt = detect_format(req.payload)
    try:
        if not req.apply:
            if fmt == "json":
                import json
                d = json.loads(req.payload)
                return {
                    "format": "json", "applied": False,
                    "counts": {k: len(d.get(k) or {}) for k in ("answers", "wrong", "fav", "notes")},
                }
            if fmt == "wrongpage":
                items = parse_wrong_page(req.payload)
                return {"format": "wrongpage", "applied": False,
                        "counts": {"题目": len(items),
                                   "收藏": sum(1 for i in items if i["favored"])}}
            if fmt == "qnums":
                items = parse_qnum_list(req.payload) or []
                return {"format": "qnums", "applied": False,
                        "counts": {"题号": len(items)}}
            wrong, fav = parse_export_text(req.payload)
            return {"format": "text", "applied": False,
                    "counts": {"wrong": len(wrong), "fav": len(fav)}}

        if fmt == "json":
            rep = import_jlq(db, req.subject_id, req.payload, replace=req.replace)
        elif fmt == "wrongpage":
            rep = import_wrong_page(db, req.subject_id, req.payload, replace=req.replace)
        elif fmt == "qnums":
            rep = import_qnum_list(db, req.subject_id, req.payload, replace=req.replace)
        else:
            rep = import_export_text(db, req.subject_id, req.payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"导入失败：{exc}") from exc

    return {"format": fmt, "applied": True, **rep.as_dict()}
