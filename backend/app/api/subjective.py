"""主观题易考清单接口。

前端页面 `/subjective`（导航里叫「简答」）用这一个接口渲染全部内容。

## 这个清单是按什么排的

不是按「我觉得重要」，是按库里已有的两个排序依据：

1. **考点权重** —— `analyze_subject()` 算出的 `est_score`（该考点在 100 分卷里的预估
   占分，由 knowledge_points.importance 归一化得到）。权重高的考点出简答的概率也高。
2. **知识体系** —— 考点表里的 `chapter_id` 指向「节」，节的 parent 才是「章」。
   所以每条都能还原出「章 → 节 → 考点」的路径，页面可以直接按章分组。

排序键 `priority = est_score × 题型系数`（S 1.0 / A 0.6 / B 0.3）——
既要权重高、也要它本身适合出简答。系数写在返回值里，前端会如实标出来。

另外还给一份 `gaps`：**权重高、但清单没覆盖**的考点。清单是人写的，难免漏；
用权重扫一遍能把漏掉的挑出来，附教材页码和现有题数，直接补齐复习盲区。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Chapter, KnowledgePoint, Question, Subject
from app.services.advice.analyzer import analyze_subject
from app.services.quality import check as quality_check
from app.services.subjective import load as load_checklist

router = APIRouter(tags=["subjective"])

# 题型系数：同样是高权重考点，S 级条目比 B 级更可能出成简答。
TIER_FACTOR = {"S": 1.0, "A": 0.6, "B": 0.3}


@router.get("/subjective/checklist")
def subjective_checklist(
    subject_id: int = 1,
    gap_limit: int = Query(10, le=30, description="权重盲区最多返回多少条"),
    db: Session = Depends(get_db),
):
    data = load_checklist()
    items = data["items"]

    if db.get(Subject, subject_id) is None:
        subject_id = 1

    # ---------- 1. 考点权重 / 掌握度（复用备考建议的同一套口径） ----------
    analysis = analyze_subject(db, subject_id, 100.0)
    stats = analysis["knowledge_points"]
    stat_by_kp: dict[int, dict] = {s["kp_id"]: s for s in stats}
    # 一条作答记录都没有时（例如分享包里个人数据被清空），掌握度算不出来。
    # 前端据此显示「—」而不是 0% —— 0% 会被读成「掌握度为零」。
    has_records = bool(analysis["kpi"]["attempts"])

    # ---------- 2. 知识体系路径：章 → 节 ----------
    kp_ids = {it["kp_id"] for it in items if it.get("kp_id")}
    kps = db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(kp_ids)).all()
    sec_ids = {k.chapter_id for k in kps if k.chapter_id}
    secs = {c.id: c for c in db.query(Chapter).filter(Chapter.id.in_(sec_ids)).all()}
    root_ids = {c.parent_id for c in secs.values() if c.parent_id}
    roots = {c.id: c for c in db.query(Chapter).filter(Chapter.id.in_(root_ids)).all()}
    sec_of = {k.id: secs.get(k.chapter_id) for k in kps}

    # ---------- 3. 该考点能做的题数（残缺题不算，与刷题页口径一致） ----------
    usable: dict[int, int] = {kp_id: 0 for kp_id in kp_ids}
    for q in db.query(Question).filter(Question.kp_id.in_(kp_ids)).all():
        if quality_check(q).usable:
            usable[q.kp_id] = usable.get(q.kp_id, 0) + 1

    out_items = []
    for it in items:
        row = dict(it)
        kp_id = it.get("kp_id")
        st = stat_by_kp.get(kp_id or -1, {})
        sec = sec_of.get(kp_id) if kp_id else None
        root = roots.get(sec.parent_id) if sec and sec.parent_id else None
        est = float(st.get("est_score") or 0.0)
        row.update(
            kp_name=st.get("name"),
            section=(sec.name if sec else None),
            root_chapter=(root.name if root else it.get("chapter")),
            importance=st.get("importance"),
            est_score=round(est, 2),
            mastery=st.get("mastery"),
            page_start=st.get("page_start"),
            q_total=usable.get(kp_id, 0) if kp_id else 0,
            priority=round(est * TIER_FACTOR.get(it["tier"], 0.3), 2),
        )
        out_items.append(row)

    # ---------- 4. 权重盲区：高权重但清单没覆盖的考点 ----------
    covered = {it.get("kp_id") for it in items}
    gaps = sorted(
        (s for s in stats if s["kp_id"] not in covered and (s["total_q"] or 0) > 0),
        key=lambda s: s["est_score"],
        reverse=True,
    )[:gap_limit]
    gap_rows = [
        {
            "kp_id": s["kp_id"], "name": s["name"], "chapter": s["chapter_name"],
            "est_score": s["est_score"], "mastery": s["mastery"],
            "total_q": s["total_q"], "page_start": s["page_start"],
        }
        for s in gaps
    ]

    return {
        "meta": data["meta"],
        "chapters": data["chapters"],
        "items": out_items,
        "essay": data["essay"],
        "gaps": gap_rows,
        "has_records": has_records,
        "weights": {
            "total_score": 100.0,
            "tier_factor": TIER_FACTOR,
            "note": "优先分 = 该考点预估占分 × 题型系数；预估占分由考点权重（importance）归一化到 100 分卷得到。",
        },
    }
