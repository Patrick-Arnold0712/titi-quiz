"""站内搜索：一个关键词，同时搜出考点、教材原文、题目、速查条目。

## 为什么不用 LIKE

`LIKE '%词%'` 只能做字面匹配，而且没法排序 ——
搜「航母」时「山东舰」那条教材原文明明更相关，却可能排在最后。

这里做的是 **BM25 检索**：把考点、教材段落、题目、速查条目全都切成「文档」，
用 jieba 分词建倒排索引，按词频 × 逆文档频率打分。
相关度高的自然排在前面，还能定位到具体是哪几个词命中的。

## 复用

分词与停用词沿用 `services/kpmap.py` 那一套（题目→考点映射用的同一份），
保证「搜索认为相关的词」和「映射认为相关的词」是一致的口径。

## 性能

全库约 2300 篇文档（231 教材段 + 1820 题 + 178 条速查 + 72 考点）。
首次查询建索引约 1~2 秒，之后缓存在内存里，单次查询 < 50ms。
题库变了就调 `invalidate()`。
"""

from __future__ import annotations

import collections
import math
import re
from dataclasses import dataclass, field

from app.services.ingest.material_tags import textbook_excerpt_rows
from app.services.ingest.textnorm import shape_true_false, strip_running_header
from app.services.kpmap import tokenize
from app.services.quality import check as quality_check  # noqa: E402

K1, B = 1.2, 0.75          # BM25 参数
SNIP_RADIUS = 45           # 摘要窗口半径

_cache: dict[int, "Index"] = {}


def invalidate() -> None:
    _cache.clear()


@dataclass
class Doc:
    kind: str                      # kp / chunk / question / bit
    ref_id: int
    text: str
    meta: dict = field(default_factory=dict)


class Index:
    def __init__(self, docs: list[Doc], boost: dict[int, float] | None = None):
        self.docs = docs
        self.tokens = [collections.Counter(tokenize(d.text)) for d in docs]
        self.lens = [max(sum(t.values()), 1) for t in self.tokens]
        self.avg = sum(self.lens) / max(len(self.lens), 1)
        self.df: collections.Counter = collections.Counter()
        for t in self.tokens:
            self.df.update(t.keys())
        self.n = max(len(docs), 1)
        # 倒排：词 -> {文档下标: 词频}
        self.postings: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
        for i, t in enumerate(self.tokens):
            for w, c in t.items():
                self.postings[w].append((i, c))
        # 名称类字段命中要额外加权（考点名、书名）
        self.boost = boost or {}

    def idf(self, w: str) -> float:
        return math.log(1 + (self.n - self.df[w] + 0.5) / (self.df[w] + 0.5))

    def search(self, query: str, top: int = 60) -> list[tuple[Doc, float, list[str]]]:
        terms = tokenize(query)
        if not terms:
            return []
        scores: collections.Counter = collections.Counter()
        hits: dict[int, list[str]] = collections.defaultdict(list)
        for w in terms:
            post = self.postings.get(w)
            if not post:
                continue
            idf = self.idf(w)
            for i, tf in post:
                denom = tf + K1 * (1 - B + B * self.lens[i] / self.avg)
                scores[i] += idf * tf * (K1 + 1) / denom
                hits[i].append(w)
        # 整串命中加成：jieba 会把专有名词切碎（「山东舰」→「山东」+「舰」，
        # 而「舰」因为只有 1 个字被停用词过滤掉），结果搜出来一堆跟「山东」有关的旁支。
        # 只要原文里出现了完整的搜索串，就额外加权。
        raw = (query or "").strip()
        out = []
        for i, s in scores.most_common(top):
            d = self.docs[i]
            if len(raw) >= 2 and raw in d.text:
                s *= 2.2
            out.append((d, s * self.boost.get(i, 1.0), hits[i]))
        out.sort(key=lambda x: -x[1])
        return out


def _snippet(text: str, terms: list[str]) -> str:
    """截第一个命中词周围的窗口。"""
    flat = re.sub(r"\s+", "", text)
    pos = -1
    for t in terms:
        p = flat.find(t)
        if p >= 0 and (pos < 0 or p < pos):
            pos = p
    if pos < 0:
        return flat[: SNIP_RADIUS * 2]
    lo = max(0, pos - SNIP_RADIUS)
    hi = min(len(flat), pos + SNIP_RADIUS)
    return ("…" if lo else "") + flat[lo:hi] + ("…" if hi < len(flat) else "")


def build(db, subject_id: int) -> Index:
    from app.models.entities import Chapter, KnowledgeBit, KnowledgePoint, Question

    chapters = {c.id: c for c in db.query(Chapter).all()}
    kps = db.query(KnowledgePoint).filter(KnowledgePoint.subject_id == subject_id).all()
    docs: list[Doc] = []
    boost: dict[int, float] = {}

    def push(kind: str, ref_id: int, text: str, factor: float, **meta):
        docs.append(Doc(kind=kind, ref_id=ref_id, text=text, meta=meta))
        if factor != 1.0:
            boost[len(docs) - 1] = factor

    # 考点：名字本身就是高度浓缩的信号，给 3 倍权重
    for k in kps:
        sec = chapters.get(k.chapter_id)
        root = chapters.get(sec.parent_id) if sec and sec.parent_id else None
        push("kp", k.id, f"{k.name} {k.name} {sec.name if sec else ''}",
             3.0, name=k.name, chapter=root.name if root else "", section=sec.name if sec else "",
             page_start=k.page_start, page_end=k.page_end, importance=k.importance)

    # 教材段落。检索用原文；返回给前端的正文要先剥页眉（和前面对齐）。
    kp_chapter: dict[int, str] = {}
    for k in kps:
        sec = chapters.get(k.chapter_id)
        root = chapters.get(sec.parent_id) if sec and sec.parent_id else None
        kp_chapter[k.id] = (root.name if root else (sec.name if sec else "")) or ""

    for c, imported in textbook_excerpt_rows(db, kps):
        k = next((x for x in kps if x.id == c.kp_id), None)
        body = c.content if imported else strip_running_header(c.content or "", kp_chapter.get(c.kp_id or 0, ""), c.page_no)
        push("chunk", c.id, c.content or "", 1.0, page_no=c.page_no, kp_id=c.kp_id,
             kp_name=k.name if k else "", full=body, file_page=imported and c.page_no is not None)

    # 题目：题干权重更高，所以题干进两次
    for q in db.query(Question).filter(
        (Question.subject_id == subject_id) | (Question.subject_id.is_(None))
    ).all():
        # 题面残缺的题不进索引。搜出来做不了、答案还可能是空的，
        # 和「刷题页不显示它们」是同一个理由 —— 出现在列表里就是污染。
        verdict = quality_check(q)
        if not verdict.usable:
            continue
        k = next((x for x in kps if x.id == q.kp_id), None)
        # 搜索结果要能**直接把题做了**，所以渲染所需的东西都备齐：
        #   - options：判断题库里是空的，走和接口一样的整形补上 A/B
        #   - answer ：判断题的 √/正确 要归一到 A/B，否则前端比对不上
        #   - quality：题面残缺的题不给「作答」，只给「看解析」
        opts, ans = q.options, (q.answer or "")
        if q.qtype.value == "true_false":
            opts, ans = shape_true_false(opts, ans)
        push("question", q.id, f"{q.stem} {q.stem} {q.explanation or ''}", 1.0,
             qtype=q.qtype.value, stem=q.stem, answer=ans,
             explanation=q.explanation, kp_id=q.kp_id, kp_name=k.name if k else "",
             options=opts, quality=verdict.level)

    # 速查条目：标题加权
    for b in db.query(KnowledgeBit).filter(KnowledgeBit.subject_id == subject_id).all():
        # 注意字段名别叫 kind —— 会和 push() 的位置参数 kind 撞名
        push("bit", b.id, f"{b.key} {b.key} {b.detail or ''}", 2.0,
             bit_kind=b.kind, key=b.key, detail=b.detail, page_no=b.page_no,
             kp_name=b.kp_name, hits=b.hits)

    return Index(docs, boost)


def get_index(db, subject_id: int) -> Index:
    if subject_id not in _cache:
        _cache[subject_id] = build(db, subject_id)
    return _cache[subject_id]


def search(db, subject_id: int, query: str, per_kind: int = 6) -> dict:
    q = (query or "").strip()
    if not q:
        return {"q": q, "terms": [], "kps": [], "excerpts": [], "questions": [], "bits": []}

    idx = get_index(db, subject_id)
    terms = tokenize(q)
    ranked = idx.search(q, top=200)

    buckets: dict[str, list] = {"kp": [], "chunk": [], "question": [], "bit": []}
    for d, s, hit_words in ranked:
        if len(buckets[d.kind]) >= per_kind * 3:
            continue
        item = {"score": round(s, 3), "matched": hit_words[:8], "snippet": _snippet(d.text, terms)}
        item.update({"id": d.ref_id, **d.meta})
        buckets[d.kind].append(item)

    # 考点结果要「合并」出来，不能只看考点文档本身。
    # 考点文档里只有考点名和章节名，搜「航母」时命中不到「航空母舰」这个考点 ——
    # 但教材段落和题目命中了，它们挂在哪个考点下，那个考点就该被搜出来。
    kp_meta: dict[int, dict] = {d.ref_id: d.meta for d in idx.docs if d.kind == "kp"}
    merged: dict[int, dict] = {}
    for it in buckets["kp"]:
        merged[it["id"]] = {**it, "via": "考点名"}
    for kind, weight in (("chunk", 0.6), ("question", 0.5), ("bit", 0.3)):
        for it in buckets[kind]:
            kid = it.get("kp_id")
            if not kid or kid not in kp_meta:
                continue                      # 速查条目没有 kp_id，跳过
            cur = merged.get(kid)
            cand = it["score"] * weight
            if cur is None:
                merged[kid] = {"id": kid, "score": round(cand, 3),
                               "matched": it["matched"], "snippet": it["snippet"],
                               "via": {"chunk": "教材段落", "question": "题目", "bit": "速查"}[kind],
                               **kp_meta[kid]}
            elif cur.get("via") != "考点名":
                cur["score"] = round(max(cur["score"], cand), 3)
    kps = sorted(merged.values(), key=lambda x: -x["score"])[:per_kind]

    return {
        "q": q,
        "terms": terms,
        "kps": kps,
        "excerpts": buckets["chunk"][:per_kind],
        "questions": buckets["question"][:per_kind],
        "bits": buckets["bit"][:per_kind],
        "total": {k: len(v) for k, v in buckets.items()},
    }
