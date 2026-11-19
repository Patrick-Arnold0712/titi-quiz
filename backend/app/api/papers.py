"""试卷与答卷 API：组卷、答题卡、交卷判分。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import (
    Attempt,
    canon_qtype,
    Paper,
    PaperAttempt,
    PaperItem,
    Question,
    Subject,
)
from app.schemas.dto import (
    question_out,
    PaperAttemptOut,
    PaperDetail,
    PaperItemOut,
    PaperOut,
    SubmitRequest,
    GeneratePaperRequest,
)
from app.services.ingest.textnorm import shape_true_false
from app.services.quality import check_fields
from app.services.paper import DEFAULT_BLUEPRINT, generate_paper, score_paper_attempt
from app.services.paper.sources import (
    BUCKET_CHAPTER,
    BUCKET_PREDICT,
    BUCKET_REAL_EXAM,
    source_mix_of,
)

router = APIRouter(prefix="/papers", tags=["papers"])


def _section_maps(paper: Paper) -> tuple[dict[int, str], dict[str, str]]:
    """把蓝图的「大题 → 题型」做成两张表：按序号、按大题名。

    两个都要，是因为要**优先按序号查**：
    `section_name` 是自由文本，各套真题卷的写法都不一样
    （「一、单项选择题」/「一、单项选择题(共20题,每题2分)」/「单项选择题 $20 \times 2$ 分」，实测 19 种），
    拿它当 key 查表会静默落空 —— 真题卷「不定项变单选」就是这么来的。
    序号是结构化的，查不中才退回名字。

    两张表的值都过 `canon_qtype`：蓝图里既可能是 `multi_choice`，
    也可能是早先写的短名 `multi`，直接透传前端判不中。
    """
    bp = paper.blueprint or []
    by_index = {i: canon_qtype(b.get("qtype")) for i, b in enumerate(bp, 1)}
    by_name = {b.get("section"): canon_qtype(b.get("qtype")) for b in bp}
    return by_index, by_name


def _decorate(db: Session, papers: list[Paper]) -> list[PaperOut]:
    """给试卷补上「题源构成」和「做过没有」。

    这两样都**不落库**，每次现算：
      - 题源构成要看 PaperItem 指向的题，题目被清理后库里的值会变；
      - 完成状态要看 PaperAttempt，落库必然不同步。
    """
    if not papers:
        return []
    ids = [p.id for p in papers]

    items = (
        db.query(PaperItem.paper_id, Question)
        .join(Question, Question.id == PaperItem.question_id)
        .filter(PaperItem.paper_id.in_(ids))
        .all()
    )
    by_paper: dict[int, list[Question]] = {}
    for pid, q in items:
        by_paper.setdefault(pid, []).append(q)

    attempts = (
        db.query(PaperAttempt)
        .filter(PaperAttempt.paper_id.in_(ids))
        .order_by(PaperAttempt.id)
        .all()
    )

    # 只有「真的作答过」的答卷才算一次。光打开答题卡不算 ——
    # `POST /papers/{id}/attempts` 是**一进答题卡就建答卷**的（这样中途刷新不丢进度），
    # 所以「误点一下」和「自检脚本访问页面」都会留下一份 status='doing'、作答 0 条的空答卷。
    # 拿它当「未交卷」显示，用户会看到自己从没开始过的卷子被标成未完成。
    answered: dict[int, int] = {}
    if attempts:
        rows = (
            db.query(Attempt.paper_attempt_id, func.count(Attempt.id))
            .filter(Attempt.paper_attempt_id.in_([a.id for a in attempts]))
            .group_by(Attempt.paper_attempt_id)
            .all()
        )
        answered = {pa_id: n for pa_id, n in rows if pa_id is not None}

    def has_content(a: PaperAttempt) -> bool:
        return a.status == "submitted" or answered.get(a.id, 0) > 0

    agg: dict[int, dict] = {}
    for a in attempts:
        if not has_content(a):
            continue
        d = agg.setdefault(a.paper_id, {"count": 0, "done": 0, "last": None, "last_done": None})
        d["count"] += 1
        d["last"] = a
        if a.status == "submitted":
            d["done"] += 1
            d["last_done"] = a

    out: list[PaperOut] = []
    for p_ in papers:
        d = agg.get(p_.id) or {}
        last = d.get("last")
        last_done = d.get("last_done")
        out.append(PaperOut.model_validate(p_).model_copy(update={
            "source_mix": source_mix_of(by_paper.get(p_.id, [])),
            "attempt_count": d.get("count", 0),
            "done_count": d.get("done", 0),
            "last_attempt_id": last.id if last else None,
            "last_status": last.status if last else None,
            "last_score": last_done.score if last_done else None,
            "last_submitted_at": last_done.submitted_at if last_done else None,
        }))
    return out


def _blueprint_with_mix(mix: dict[str, dict[str, int]] | None) -> list[dict]:
    """把面板传来的「题源配额」盖到默认蓝图上。

    只改 `mix`，不动题数与分值 —— 卷面结构必须跟官方蓝图一致，
    能调的只有「每道大题由哪些题源组成」。
    """
    blueprint = [dict(sec, mix=dict(sec.get("mix") or {})) for sec in DEFAULT_BLUEPRINT]
    if not mix:
        return blueprint
    for sec in blueprint:
        override = mix.get(sec["qtype"])
        if not override:
            continue
        # 只接受已知的题源桶，防止面板传错键名把配额悄悄清空
        sec["mix"] = {k: max(0, int(v)) for k, v in override.items()
                      if k in (BUCKET_REAL_EXAM, BUCKET_CHAPTER, BUCKET_PREDICT)}
    return blueprint


@router.get("", response_model=list[PaperOut])
def list_papers(subject_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Paper)
    if subject_id is not None:
        q = q.filter(Paper.subject_id == subject_id)
    return _decorate(db, q.order_by(Paper.id.desc()).all())


@router.get("/blueprint/default")
def default_blueprint():
    """官方蓝图，前端做组卷参数面板时用。"""
    return DEFAULT_BLUEPRINT


@router.post("/generate", response_model=PaperOut, status_code=201)
def api_generate(req: GeneratePaperRequest, db: Session = Depends(get_db)):
    if db.get(Subject, req.subject_id) is None:
        raise HTTPException(404, "学科不存在")
    blueprint = req.blueprint or _blueprint_with_mix(req.mix)
    paper, warnings = generate_paper(
        db, req.subject_id, name=req.name, blueprint=blueprint,
        duration_min=req.duration_min, seed=req.seed, note="按蓝图自动组卷",
        auto_cloze=req.auto_cloze, min_kp_importance=req.min_kp_importance,
    )
    if warnings:
        db.commit()
    # 走 _decorate，把题源构成一起返回 —— 直接 return paper 的话
    # 前端拿到的 source_mix 永远是 None。
    return _decorate(db, [paper])[0]


@router.get("/{paper_id}", response_model=PaperDetail)
def get_paper(paper_id: int, with_answer: bool = False, db: Session = Depends(get_db)):
    """取试卷。with_answer=False（默认）会抹掉答案，供答题卡使用。"""
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(404, "试卷不存在")

    items = (
        db.query(PaperItem).filter(PaperItem.paper_id == paper_id)
        .order_by(PaperItem.order_index).all()
    )
    qids = [it.question_id for it in items]
    qmap = {q.id: q for q in db.query(Question).filter(Question.id.in_(qids)).all()}

    sec_by_index, sec_by_name = _section_maps(paper)

    out_items = []
    for it in items:
        q = qmap.get(it.question_id)
        if q is None:
            continue
        qo = question_out(q)
        if not with_answer:
            qo = qo.model_copy(update={"answer": "", "explanation": None})
        out_items.append(PaperItemOut(
            order_index=it.order_index, section_name=it.section_name,
            score_per=it.score_per,
            display_qtype=(sec_by_index.get(it.section_index)
                           or sec_by_name.get(it.section_name)
                           or canon_qtype(q.qtype.value)),
            question=qo,
        ))
    # 注意：不能直接 PaperDetail.model_validate(paper)——那会把 ORM 的 items 关系
    # 当成本模型的 items 去校验，而 ORM PaperItem 里没有嵌套的 question。
    base = _decorate(db, [paper])[0]
    detail = PaperDetail(**base.model_dump(), items=out_items)
    return detail


@router.post("/{paper_id}/attempts", response_model=PaperAttemptOut, status_code=201)
def start_attempt(paper_id: int, db: Session = Depends(get_db)):
    """开考：建一份答卷。

    如果这份卷子已经有一份「未交卷」的答卷，直接复用它 ——
    否则用户每次点开答题卡看一眼（哪怕是误触）都会新建一份，
    攒一堆 status='doing' 的孤儿答卷。
    """
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(404, "试卷不存在")

    pa = (
        db.query(PaperAttempt)
        .filter(PaperAttempt.paper_id == paper_id, PaperAttempt.status == "doing")
        .order_by(PaperAttempt.id.desc())
        .first()
    )
    if pa is not None:
        return pa

    pa = PaperAttempt(paper_id=paper_id, status="doing")
    db.add(pa)
    db.commit()
    db.refresh(pa)
    return pa


@router.post("/attempts/{attempt_id}/submit", response_model=PaperAttemptOut)
def submit_attempt(attempt_id: int, req: SubmitRequest, db: Session = Depends(get_db)):
    """交卷：写入作答并自动判分（主观题登记待人工）。"""
    pa = db.get(PaperAttempt, attempt_id)
    if pa is None:
        raise HTTPException(404, "答卷不存在")
    if pa.status == "submitted":
        raise HTTPException(400, "该答卷已交卷")

    item_qids = {
        it.question_id
        for it in db.query(PaperItem).filter(PaperItem.paper_id == pa.paper_id).all()
    }
    db.query(Attempt).filter(Attempt.paper_attempt_id == pa.id).delete(synchronize_session=False)
    db.flush()

    for a in req.answers:
        if a.question_id not in item_qids:
            continue
        db.add(Attempt(
            question_id=a.question_id, paper_attempt_id=pa.id,
            user_answer=a.user_answer or "", duration_ms=0,
        ))
    db.flush()

    detail = score_paper_attempt(db, pa)
    pa.status = "submitted"
    pa.submitted_at = datetime.now()
    pa.duration_ms = req.duration_ms
    db.commit()
    db.refresh(pa)
    return pa


@router.get("/attempts/{attempt_id}", response_model=PaperAttemptOut)
def get_attempt(attempt_id: int, db: Session = Depends(get_db)):
    pa = db.get(PaperAttempt, attempt_id)
    if pa is None:
        raise HTTPException(404, "答卷不存在")
    return pa


@router.get("/attempts/{attempt_id}/review")
def review_attempt(attempt_id: int, db: Session = Depends(get_db)):
    """逐题回看：你的答案 / 正确答案 / 解析 / 对错。"""
    pa = db.get(PaperAttempt, attempt_id)
    if pa is None:
        raise HTTPException(404, "答卷不存在")
    items = (
        db.query(PaperItem).filter(PaperItem.paper_id == pa.paper_id)
        .order_by(PaperItem.order_index).all()
    )
    qmap = {q.id: q for q in db.query(Question).filter(
        Question.id.in_([it.question_id for it in items])).all()}
    amap = {a.question_id: a for a in pa.answers}
    # 与答题卡口径一致：判断题在单选大题里按单选题呈现，
    # 回看页的「正确答案」才会显示 A/B 而不是「正确/错误」。
    sec_by_index, sec_by_name = _section_maps(pa.paper)

    rows = []
    for it in items:
        q = qmap.get(it.question_id)
        a = amap.get(it.question_id)
        # 判断题要和题目接口走同一套整形：补 A/B 选项 + 答案归一到 A/B。
        # 否则回看页拿到的是 √ / ×，跟选项 key 对不上，对错高亮会全错。
        qt = q.qtype.value if q else None
        opts, ans = (q.options, q.answer or "") if q else (None, "")
        if qt == "true_false":
            opts, ans = shape_true_false(opts, ans)
        # 题面体检结论也要透出去，回看页据此显示「题面残缺，无法判分」
        q_level = check_fields(q.qtype, q.stem or "", q.options, q.answer or "").level if q else "ok"
        rows.append({
            "order_index": it.order_index,
            "section_name": it.section_name,
            "score_per": it.score_per,
            "qtype": qt,
            "display_qtype": (sec_by_index.get(it.section_index)
                              or sec_by_name.get(it.section_name)
                              or canon_qtype(qt)),
            "stem": q.stem if q else "",
            "options": opts,
            "answer": ans,
            "explanation": q.explanation if q else None,
            "user_answer": a.user_answer if a else "",
            "is_correct": a.is_correct if a else None,
            "awarded_score": a.awarded_score if a else 0.0,
            "pending_manual": bool(q and q.qtype.value in ("short_answer", "essay")),
            "quality": q_level,
        })
    return {"attempt_id": pa.id, "paper_id": pa.paper_id, "score": pa.score,
            "detail": pa.detail, "rows": rows}
