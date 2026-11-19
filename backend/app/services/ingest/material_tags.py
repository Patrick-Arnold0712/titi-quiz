"""资料来源标记也用于区分原文展示与可信题源。"""
from sqlalchemy import or_

from app.models.entities import Chunk

IMPORT_MARK = "material_import"
SECTION_TAG = "material_section"


def textbook_excerpt_rows(db, points):
    imported = {kp.id for kp in points if kp.tags == SECTION_TAG}
    # 原军理按印刷页码筛教材；分科导入的 Word/文本没有页码，也是真实教材摘录。
    rows = (
        db.query(Chunk)
        .filter(Chunk.kp_id.in_([kp.id for kp in points]),
                or_(Chunk.page_no.isnot(None), Chunk.kp_id.in_(imported)))
        .order_by(Chunk.page_no, Chunk.order_index, Chunk.id)
    )
    return ((chunk, chunk.kp_id in imported) for chunk in rows)
