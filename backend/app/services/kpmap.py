"""题目 -> 考点 匹配器（可复用内核）。

原先是 `map_questions_to_kp.py` 里的私有逻辑，抽出来是为了：
- 诊断脚本能直接对单题打分、看候选排名，不用重跑全量
- 以后接新科目时，同一套打分逻辑只维护一份

思路：把每个考点当成一篇「文档」（= 考点名 + 该考点名下的教材正文），
用 TF-IDF 构建特征签名；题目的题干（含选项/答案/解析）去匹配打分。

打分三部分：
1. 正文特征命中：题干词 在 考点签名 中的 tf*idf 之和（余弦）
2. **考点名命中**（权重大）：考点名本身就是高度浓缩的提示
3. 章节一致性：题目已挂的章 与 考点所属章 一致时，只在同章考点里选

为什么不用模型：这一步要的是**可复现、可审计**。
每个题的得分都能拆开看是哪几个词贡献的，出问题时能定位。
"""

from __future__ import annotations

import collections
import math
import re
from dataclasses import dataclass

import jieba

from app.models.entities import Chapter, Chunk, KnowledgePoint, Question

CJK = re.compile(r"[\u4e00-\u9fff]")
# 只要中文词、纯英文词、以及「必须含字母」的混合词。
# 纯数字（"17" "2010"）一律丢掉 —— 它们 idf 很高但没有语义，
# 会把题目带到毫不相关的考点上（实测：山东舰 → 核生化武器，就是被 "17" 带偏的）。
TOKEN_OK = re.compile(r"^[\u4e00-\u9fff]{2,}$"          # 中文词
                      r"|^[A-Za-z]{2,}$"               # 纯英文词
                      r"|^(?=.*[A-Za-z])[A-Za-z0-9]{2,}$")  # 含字母的混合词，如 C4ISR

STOPWORDS = set("""
的 了 和 与 及 或 是 在 有 为 对 以 上 下 中 内 外 前 后 等 其 该 此 这 那 你 我 他 她 它
我们 你们 他们 我国 下列 以下 上述 这个 那个 什么 哪些 哪个 如何 怎样 可以 不能 不是 属于
包括 主要 基本 进行 具有 属于 关于 根据 按照 通过 由于 因为 所以 但是 而且 并且 以及 同时
方面 内容 情况 问题 特点 作用 意义 影响 要求 方式 方法 过程 发展 形成 产生 实现 完成 建设
一项 两项 三项 一项 正确 错误 说法 表述 选项 答案 每题 共 分 题 道 个 种 类 项
时期 阶段 时间 年代 世界 中国 国家 人民 军队 军事 战略 战争 国防 装备 技术 思想 思想史
类型 分类 划分 活动 事件 情况 状况 形势 内容 概念 定义 含义 内涵 特征 性质 本质 目的 目标
原则 基本 基础 前提 关键 核心 重要 主要 直接 间接 具体 一般 特殊 不同 相同 相似 相关 有关
要求 措施 办法 途径 手段 方式 方法 过程 步骤 阶段 结果 原因 条件 因素 表现 体现 反映 表明
正确 错误 说法 表述 判断 选择 判断 认为 提出 主张 强调 指出 说明 表示 具有 包含 包括 属于
可以 能够 应该 必须 需要 进行 实现 完成 达到 取得 形成 产生 发展 变化 增长 提高 加强 建立
哪些 什么 怎么 如何 是否 关于 对于 根据 按照 通过 由于 因为 所以 但是 而且 并且 以及 同时
中国 我国 外国 世界 各国 社会主义 现代化 建设 制度 体系 系统 管理 组织 机构 部门 领导
""".split())

NAME_WEIGHT = 6.0        # 考点名命中权重
CHAPTER_BONUS = 1.15     # 同章加成
# 每个考点保留的特征词数。原先 60 太激进 —— 教材正文一多，
# 具体词（突火枪、金属炮弹、元朝）全被截掉，导致题目匹配不上。
# 500 之后基本收敛（再放宽结果几乎不变），见 docs/06 的对比记录。
TOP_TERMS = 500


def tokenize(s: str) -> list[str]:
    out = []
    for t in jieba.cut(s or ""):
        t = t.strip()
        if len(t) < 2 or t in STOPWORDS or not TOKEN_OK.match(t):
            continue
        out.append(t)
    return out


@dataclass
class Hit:
    kp: KnowledgePoint
    score: float
    terms: list[str]          # 贡献最大的几个词，按 idf 降序
    name_hits: list[str]      # 考点名直接命中的词


class Matcher:
    """给定 db，构建一次，可以反复对任意题目打分。"""

    def __init__(self, db):
        self.db = db
        self.kps: list[KnowledgePoint] = db.query(KnowledgePoint).all()
        self.chapters: dict[int, Chapter] = {c.id: c for c in db.query(Chapter).all()}

        kp_text: dict[int, list[str]] = collections.defaultdict(list)
        for ch in db.query(Chunk).filter(Chunk.kp_id.isnot(None)).all():
            kp_text[ch.kp_id].append(ch.content)

        # 考点签名 = 考点名 + 正文
        kp_tokens: dict[int, list[str]] = {
            kp.id: tokenize(kp.name + " " + " ".join(kp_text.get(kp.id, [])))
            for kp in self.kps
        }

        # IDF：以 72 个考点为语料。过泛的词（出现在 >20% 考点里）剔除，它们刷分但无区分度
        n_doc = len(self.kps)
        df: collections.Counter = collections.Counter()
        for toks in kp_tokens.values():
            df.update(set(toks))
        max_df = max(2, int(n_doc * 0.2))
        self.idf = {
            t: math.log(n_doc / (1 + d)) + 1.0
            for t, d in df.items()
            if d <= max_df
        }

        self.sig: dict[int, dict[str, float]] = {}
        self.name_terms: dict[int, set[str]] = {}
        for kp in self.kps:
            toks = kp_tokens[kp.id]
            tf = collections.Counter(toks)
            total = max(len(toks), 1)
            scored = {t: (c / total) * self.idf.get(t, 1.0) for t, c in tf.items()}
            self.sig[kp.id] = dict(sorted(scored.items(), key=lambda x: -x[1])[:TOP_TERMS])
            self.name_terms[kp.id] = set(tokenize(kp.name))

        self.norms = {
            kp.id: math.sqrt(sum(v * v for v in self.sig[kp.id].values())) or 1.0
            for kp in self.kps
        }
        # 考点所属的根章（L1）
        self.kp_root: dict[int, int | None] = {}
        for kp in self.kps:
            c = self.chapters.get(kp.chapter_id)
            self.kp_root[kp.id] = (c.parent_id or c.id) if c else None
        # 章 -> 该章的考点
        self.by_root: dict[int | None, list[KnowledgePoint]] = collections.defaultdict(list)
        for kp in self.kps:
            self.by_root[self.kp_root[kp.id]].append(kp)

    # ---------- 打分 ----------
    def _question_text(self, q: Question) -> str:
        return " ".join(filter(None, [
            q.stem,
            q.answer or "",
            q.explanation or "",
            " ".join(o.get("text", "") for o in (q.options or [])),
        ]))

    def question_root(self, q: Question) -> int | None:
        if q.chapter_id and q.chapter_id in self.chapters:
            c = self.chapters[q.chapter_id]
            return c.parent_id or c.id
        return None

    def rank(self, q: Question, top: int = 5) -> list[Hit]:
        q_toks = tokenize(self._question_text(q))
        if not q_toks:
            return []
        q_tf = collections.Counter(t for t in q_toks if t in self.idf)
        q_vec = {t: c * self.idf[t] for t, c in q_tf.items()}
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
        q_set = set(q_vec)

        root = self.question_root(q)
        candidates = self.by_root.get(root) if root is not None else self.kps
        if not candidates:
            candidates = self.kps

        out: list[Hit] = []
        for kp in candidates:
            sig = self.sig[kp.id]
            dot = 0.0
            terms: list[tuple[float, str]] = []
            for t in q_set:
                w = sig.get(t)
                if w:
                    dot += q_vec[t] * w
                    terms.append((self.idf.get(t, 1.0), t))
            cos = dot / (q_norm * self.norms[kp.id]) if self.norms[kp.id] else 0.0
            s = cos * 10.0
            name_hit = q_set & self.name_terms[kp.id]
            if name_hit:
                s += NAME_WEIGHT * sum(self.idf.get(t, 1.0) for t in name_hit)
            if s > 0:
                out.append(Hit(
                    kp=kp, score=s,
                    terms=[t for _, t in sorted(terms, reverse=True)[:8]],
                    name_hits=sorted(name_hit),
                ))
        out.sort(key=lambda h: -h.score)
        return out[:top]

    def best(self, q: Question) -> Hit | None:
        r = self.rank(q, top=1)
        return r[0] if r else None
