"""考前速查：零碎知识 + 考点教材原文。

两个用途：
1. `GET /bits`   —— 教材知识链接、年份、法律、著作速查表
2. `GET /kp/{id}` —— 某个考点的教材原文（错题本里「看教材」用）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Chapter, KnowledgeBit, KnowledgePoint, Subject
from app.services import search as search_svc
from app.services.ingest.material_tags import textbook_excerpt_rows
from app.services.ingest.textnorm import strip_running_header

router = APIRouter(tags=["bits"])

KINDS = ("link", "year", "law", "work")


@router.get("/bits")
def list_bits(
    kind: str | None = None,
    q: str | None = None,
    subject_id: int = 1,
    limit: int = Query(300, le=1000),
    db: Session = Depends(get_db),
):
    """零碎知识速查。按提及次数降序 —— 提得越多越可能考。"""
    query = db.query(KnowledgeBit).filter(KnowledgeBit.subject_id == subject_id)
    if kind:
        if kind not in KINDS:
            raise HTTPException(400, f"kind 必须是 {KINDS} 之一")
        query = query.filter(KnowledgeBit.kind == kind)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (KnowledgeBit.key.like(like)) | (KnowledgeBit.detail.like(like))
        )
    rows = query.order_by(KnowledgeBit.hits.desc(), KnowledgeBit.id).limit(limit).all()
    return [
        {
            "id": r.id, "kind": r.kind, "key": r.key, "detail": r.detail,
            "page_no": r.page_no, "kp_id": r.kp_id, "kp_name": r.kp_name, "hits": r.hits,
        }
        for r in rows
    ]


@router.get("/bits/stats")
def bits_stats(subject_id: int = 1, db: Session = Depends(get_db)):
    """各类条目数，给前端做标签上的计数。"""
    out = {k: 0 for k in KINDS}
    for (kind, n) in (
        db.query(KnowledgeBit.kind, __import__("sqlalchemy").func.count())
        .filter(KnowledgeBit.subject_id == subject_id)
        .group_by(KnowledgeBit.kind)
    ):
        out[kind] = n
    return out


@router.get("/kp/{kp_id}")
def kp_detail(kp_id: int, db: Session = Depends(get_db)):
    """考点详情：所属章、教材页码、以及该考点名下的教材原文。

    错题本用它做「这道题考的是哪一段教材」—— 错的题必须能立刻回到原文，
    否则订正就是抄答案，没有意义。
    """
    kp = db.get(KnowledgePoint, kp_id)
    if kp is None:
        raise HTTPException(404, "考点不存在")

    sec = db.get(Chapter, kp.chapter_id) if kp.chapter_id else None
    root = db.get(Chapter, sec.parent_id) if sec and sec.parent_id else None

    # 摘录范围：当前考点 + **同节内前后相邻考点**。
    #
    # 为什么要带相邻考点：考点的粒度是「三级目」，但一道题考的往往横跨相邻小节。
    # 实测例子：题目问「传统安全 / 非传统安全」，教材把「(四)经济安全 (五)文化安全」
    # 编在「三、传统领域的国家安全」里，而「科技/信息/生态/生物/海外利益」在
    # 「四、新兴领域的国家安全」里 —— 只看当前考点，就会觉得原文「缺了几项」。
    siblings: list[KnowledgePoint] = []
    if sec is not None:
        siblings = (
            db.query(KnowledgePoint)
            .filter(KnowledgePoint.chapter_id == sec.id)
            .order_by(KnowledgePoint.page_start, KnowledgePoint.id)
            .all()
        )
    idx = next((i for i, k in enumerate(siblings) if k.id == kp.id), None)
    window: list[KnowledgePoint] = []
    if idx is not None:
        for j in (idx - 1, idx, idx + 1):
            if 0 <= j < len(siblings):
                window.append(siblings[j])
    if not window:
        window = [kp]

    # 该考点下有多少题、其中错题多少
    from app.models.entities import Attempt, Question
    qids = [q.id for q in db.query(Question.id).filter(Question.kp_id == kp_id)]
    total_q = len(qids)
    wrong_ids = set()
    if qids:
        for (qid,) in (
            db.query(Attempt.question_id)
            .filter(Attempt.question_id.in_(qids), Attempt.is_correct.is_(False))
            .distinct()
        ):
            wrong_ids.add(qid)

    # 正文要先剥页眉：教材每页顶部有「第二章 国家安全 57」，
    # 混在正文中间读起来是「重要手段。第二章国家安全57它们利用…」。
    # 用「章名 + 本页页码」精确匹配，页码对不上就不动。
    chap_name = (root.name if root else (sec.name if sec else "")) or ""

    return {
        "id": kp.id,
        "name": kp.name,
        "importance": kp.importance,
        "page_start": kp.page_start,
        "page_end": kp.page_end,
        "section": sec.name if sec else None,
        "chapter": root.name if root else (sec.name if sec else None),
        "total_questions": total_q,
        "wrong_count": len(wrong_ids),
        # 按页码排序，每段标出属于哪个考点，前端好分组
        #
        "excerpts": [
            {
                "page_no": c.page_no,
                "file_page": imported and c.page_no is not None,
                "kp_id": c.kp_id,
                "kp_name": next((k.name for k in window if k.id == c.kp_id), None),
                "is_current": c.kp_id == kp.id,
                "text": c.content if imported else strip_running_header(c.content or "", chap_name, c.page_no),
            }
            for c, imported in textbook_excerpt_rows(db, window)
        ],
        # 同节有哪些考点，前端用来提示「还有哪些相关小节」
        "siblings": [
            {"id": k.id, "name": k.name, "page_start": k.page_start,
             "page_end": k.page_end, "is_current": k.id == kp.id,
             "included": any(w.id == k.id for w in window)}
            for k in siblings
        ],
    }


@router.get("/search")
def do_search(
    q: str,
    subject_id: int = 1,
    per_kind: int = Query(6, le=20),
    db: Session = Depends(get_db),
):
    """站内搜索：一个关键词同时搜出考点、教材原文、题目、速查条目。

    用 BM25 排序（不是 LIKE 字面匹配），所以搜「航母」时
    「山东舰」那类真正相关的教材段落会排在前面。
    """
    if not q.strip():
        raise HTTPException(400, "搜索词不能为空")
    return search_svc.search(db, subject_id, q, per_kind)
