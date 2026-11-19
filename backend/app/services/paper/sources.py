"""押题卷的题源策略：哪些池子能进卷，以及怎么让卷子像真题。

## 为什么要把「题源」单独拎出来

题库是多个来源拼起来的，信度差得很远。实测（1820 道）：

| 桶 | 是什么 | 存量 | 题面完好 | 进押题卷 |
| --- | --- | --- | --- | --- |
| `real_exam` | 历年真题（PDF 抽取 + 参考站真题卷） | 459 | 245 | ✅ 最贴考试 |
| `refsite_chapter` | 参考站 500 道章节练习（照这本教材编，**题题带解析**） | 500 | 500 | ✅ |
| `predict` | 依据考点分析自出，题干与答案人工校 | — | — | ✅ |
| `other` | 自有资料抽的题（复习笔记、题库 docx） | 861 | 669 | ❌ 信度不够 |

`other` 里混着大量跟教材无关的题 —— 之前用户反馈押题卷「有非课本内容、偏难怪」，
根子就是组卷时把它们一起抽了。

## 「符合真题的命题规律」怎么落地

不是靠调一个系数，而是三件事：

1. **题源配比**：每个大题按配额取（真题占大头，章节题与自出题补齐）
2. **章节配比**：以**真题客观题的章节分布**为目标，抽得多的章后续权重下降
3. **可判分**：客观题必须有答案；题面残缺的一律不进候选池（见 quality.py）

组完卷会把实际构成写进 `Paper.note`，可核对、可回归。
"""

from __future__ import annotations

import collections

from sqlalchemy.orm import Session

from app.models.entities import Chapter, Question, QuestionType, SourceType

# 题源桶
BUCKET_REAL_EXAM = "real_exam"
BUCKET_CHAPTER = "refsite_chapter"
BUCKET_PREDICT = "predict"
BUCKET_OTHER = "other"

# 只有这三个桶进押题卷
EXAM_BUCKETS = (BUCKET_REAL_EXAM, BUCKET_CHAPTER, BUCKET_PREDICT)
# 补足配额时的取用顺序：真题 -> 章节题 -> 自出题
BUCKET_PRIORITY = (BUCKET_REAL_EXAM, BUCKET_CHAPTER, BUCKET_PREDICT)

BUCKET_LABEL = {
    BUCKET_REAL_EXAM: "真题",
    BUCKET_CHAPTER: "章节题",
    BUCKET_PREDICT: "自出题",
    BUCKET_OTHER: "自有资料",
}


def bucket_of(q: Question) -> str:
    """判断一道题属于哪个题源桶。

    先看 tags（更精确），再看 source_type（兜底）。
    `predict:` 前缀优先于 `refsite:` —— 自出题也可能挂在参考站考点上。
    """
    tags = q.tags or ""
    if tags.startswith("predict:"):
        return BUCKET_PREDICT
    if tags.startswith("refsite:ch"):
        return BUCKET_CHAPTER
    if q.source_type == SourceType.real_exam:
        return BUCKET_REAL_EXAM
    if q.source_type == SourceType.generated:
        return BUCKET_PREDICT
    return BUCKET_OTHER


def in_exam_pool(q: Question) -> bool:
    """能不能进押题卷。"""
    return bucket_of(q) in EXAM_BUCKETS


# ---------- 章节：统一到「章」这一级 ----------

def root_chapter_map(db: Session) -> dict[int, int]:
    """chapter_id -> 所属「章」的 id。节映射到自己的父章，章映射到自己。"""
    rows = db.query(Chapter).all()
    by_id = {c.id: c for c in rows}
    out: dict[int, int] = {}
    for c in rows:
        root = by_id.get(c.parent_id) if c.parent_id else None
        out[c.id] = root.id if root is not None else c.id
    return out


def exam_chapter_shares(db: Session, subject_id: int) -> dict[int, float]:
    """真题客观题的章节分布（目标配比，加起来为 1）。

    用「章」这一级统计 —— 节的数量在 5 章之间不均衡，章级才是真正的命题分布。
    样本不足（<20 题）时返回空字典，调用方退回「不做章节约束」，
    免得拿三五道题算出来的噪声当目标。
    """
    roots = root_chapter_map(db)
    rows = (
        db.query(Question)
        .filter((Question.subject_id == subject_id) | (Question.subject_id.is_(None)))
        .filter(Question.source_type == SourceType.real_exam)
        .filter(Question.qtype.in_([QuestionType.single_choice, QuestionType.multi_choice]))
        .all()
    )
    rows = [q for q in rows if (q.answer or "").strip()]
    counter: collections.Counter = collections.Counter()
    for q in rows:
        root = roots.get(q.chapter_id) if q.chapter_id else None
        if root:
            counter[root] += 1
    total = sum(counter.values())
    if total < 20:
        return {}
    return {k: v / total for k, v in counter.items()}


# ---------- 报告 ----------

def source_mix_of(questions: list[Question]) -> dict[str, int]:
    """统计题源构成。只吃题目列表 —— 传 (大题, 题) 元组会在这里炸，别传错。"""
    mix: collections.Counter = collections.Counter()
    for q in questions:
        mix[bucket_of(q)] += 1
    return dict(mix)


def format_mix(mix: dict[str, int]) -> str:
    parts = [f"{BUCKET_LABEL.get(k, k)} {v}" for k, v in mix.items() if v]
    return " · ".join(parts) if parts else "—"


def chapter_spread(rows: list[Question], roots: dict[int, int], chapters: dict[int, Chapter]) -> dict[str, int]:
    """按「章」统计卷面题数，返回 {章名: 题数}。"""
    out: collections.Counter = collections.Counter()
    for q in rows:
        root = roots.get(q.chapter_id) if q.chapter_id else None
        name = chapters[root].name if root in chapters else "未归类"
        out[name] += 1
    return dict(out)
