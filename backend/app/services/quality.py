"""题目可用性判定：一道题能不能拿来给人做。

## 为什么需要

题库是多个来源拼起来的，质量参差。实测一批「押题卷」里混进了：

- **设空丢失**：`战争中有被称为"沙漠军刀"的地面作战。` —— 原本是「（ ）战争中有…」，
  导入时开头的空位没了，读起来像个陈述句，根本不知道要填什么
- **选项粘在题干里**：`电子侦察通常采用的手段有 A地面电子侦察站B电子对抗侦察飞机C…`
  选项没有拆出来，前端只能渲染成一个文本框 —— 多选题被当成主观题
- **卷头混入**：`学院:____ 姓名:____ 学号:____ 得分:____` 被当成了论述题
- **偏难怪**：来自零散笔记的题，跟教材没关系，考场上不会出现

这些东西进了卷子，轻则做不下去，重则**被判错** ——
用户明明会做，却因为题面残缺被记成错题，反过来污染错题本和掌握度。

所以：出卷、刷题、判分三个地方都要先过这一关。

## 判定分三档

| 档位 | 含义 | 处理 |
| --- | --- | --- |
| `ok` | 题面完整，可正常作答判分 | 正常用 |
| `defective` | 题面残缺（选项缺失 / 没设空 / 卷头） | **不进卷、不判分、不记账** |
| `suspect` | 能作答，但可疑（与教材关联弱 / 太短） | 可用，但出卷时降权 |
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.models.entities import Question, QuestionType

# 设空标记：（ ）/（）/（  ）/____/＿＿＿＿
RE_BLANK = re.compile(r"[（(]\s*[）)]|[_＿]{2,}")

# 提问词：单选题题干里出现这些，说明问题指向明确
RE_ASK = (
    r"下列|以下|哪个|哪些|哪一种|什么|何时|何地|谁|多少|几年|多久|多大|"
    r"属于|不属于|包括|不包括|分为|可分为|标志|"
    r"正确|错误|不正确|是（|有（|指的是|是指|错误的是"
)

# 多选题题干常见的收尾方式（选项就是答案）
# 多选题的常见收尾：以「有 / 包括 / 分为 / 是 / 等」结尾，后面可能跟一个空括号。
# 注意括号整体要可选 —— 写成必需的会把「…主要义务有」这种正常题干判成可疑。
RE_MULTI_TAIL = r"(有|包括|分为|是|等)[。？?]?\s*([（(]\s*[）)]\s*)?[。]?$"

# 卷头 / 说明：不是题目
# 只认「表单式卷头」。不能拿「下划线」当判据 —— 设空本身就长这样，会大面积误伤。
RE_PAPER_HEADER = re.compile(r"学院\s*[:：].{0,4}姓名|姓名\s*[:：].{0,4}学号|学号\s*[:：].{0,6}(班级|专业)|得分\s*[:：]\s*[_＿]")

MIN_STEM = 10


def option_list(q: Question) -> list[tuple[str, str]] | None:
    """解析 options 字段 -> [(key, text)]；缺失或全空返回 None。"""
    raw = q.options
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not raw:
        return None
    out: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append((str(item.get("key", "")).strip(), str(item.get("text", "")).strip()))
        else:
            out.append(("", str(item).strip()))
    if not out or any(not t for _, t in out):
        return None
    return out


def extract_inline_options(stem: str) -> tuple[str, list[dict]] | None:
    """把「…的手段有 A地面站B飞机C船D卫星」这种题干拆成 (新题干, 选项)。

    只在能明确切出 A/B/C/D 四个时才动手 —— 宁可漏拆，不能拆错。
    """
    marks = [(m.start(), m.group()) for m in re.finditer(r"(?<![A-Za-z])[ABCD](?=[.、．]?[\u4e00-\u9fff])", stem)]
    if len(marks) < 4:
        return None
    head = marks[:4]
    if [k for _, k in head] != ["A", "B", "C", "D"]:
        return None
    body = stem[: head[0][0]].rstrip(" ：:，,")
    if len(body) < MIN_STEM - 2:
        return None
    opts = []
    for i, (pos, key) in enumerate(head):
        end = head[i + 1][0] if i + 1 < len(head) else len(stem)
        text = stem[pos + 1 : end].strip().lstrip(".、．").strip()
        if not text:
            return None
        opts.append({"key": key, "text": text})
    return body, opts


@dataclass
class _Plain:
    """只带 check_fields 需要的四个字段，避免为了调检查而造 ORM 对象。"""
    qtype: object
    stem: str
    options: object
    answer: str


@dataclass
class Verdict:
    level: str                 # ok / defective / suspect
    reasons: list[str]

    @property
    def usable(self) -> bool:
        return self.level != "defective"


# 人工 / 脚本标注的题源标签。带这些标签的题直接判残缺，不进任何一道闸的下游。
#   noise —— 不是题目（答案串、卷头须知、页脚水印、复习建议、两题粘在一起）
#   dup   —— 与另一条记录完全重复（保留题面更干净的那条）
# 由 data/clean_exam_subjective.py 标注，可回滚（把标签去掉即可）。
TAGS_BLOCKING = {
    "noise": "已标注为噪声（不是题目）",
    "dup": "与另一条记录重复",
}


def check(q: Question) -> Verdict:
    """给一道题做体检（ORM 对象版）。"""
    tags = q.tags or ""
    if tags:
        parts = set(tags.split("|")) - {""}
        for tag, why in TAGS_BLOCKING.items():
            if tag in parts:
                return Verdict("defective", [why])
    return check_fields(q.qtype, q.stem or "", q.options, q.answer or "")


def check_fields(qtype, stem: str, options, answer: str) -> Verdict:
    """给一道题做体检（纯值版）。

    拆出来是因为 API 层（Pydantic schema）拿不到 ORM 对象，
    但同样需要判定 —— 前端要据此决定「能不能作答」。
    """
    stem = (stem or "").strip()
    q = _Plain(qtype=qtype, stem=stem, options=options, answer=answer)
    reasons: list[str] = []

    if not stem:
        return Verdict("defective", ["题干为空"])
    if RE_PAPER_HEADER.search(stem):
        return Verdict("defective", ["看着像卷头/说明，不是题目"])
    if len(stem) < MIN_STEM:
        reasons.append(f"题干过短（{len(stem)} 字）")

    if q.qtype in (QuestionType.single_choice, QuestionType.multi_choice):
        if option_list(q) is None:
            if extract_inline_options(stem) is not None:
                reasons.append("选项粘在题干里（可自动拆）")
            else:
                return Verdict("defective", ["客观题没有可用的选项"])
        if not RE_BLANK.search(stem) and not re.search(RE_ASK, stem):
            if q.qtype == QuestionType.single_choice:
                return Verdict("defective", ["单选题既没有设空，也没有提问词 —— 设空多半丢了"])
            if not re.search(RE_MULTI_TAIL, stem):
                reasons.append("多选题题干收尾不明确")

    # 主观题（简答/论述）本来就不做自动批改，没有标准答案是正常的。
    # 只有客观题缺答案才算残缺 —— 缺了就没法判分。
    if q.qtype in (QuestionType.single_choice, QuestionType.multi_choice, QuestionType.true_false):
        if not (q.answer or "").strip():
            return Verdict("defective", ["客观题没有标准答案"])
    # 主观题**不因为「短」就判残缺**。
    # 真题里的简答题本来就常是一句话：「战争的内涵。」6 字、「我国的国防政策。」8 字 ——
    # 这些是正经考题，判成残缺就再也抽不进卷子了。
    # 真正的噪声（卷头 / 答案串 / 页脚水印 / 复习建议）由 RE_PAPER_HEADER 和
    # tags 里的 noise / dup 标签拦住，不需要靠长度兜底。
    # 长度只作为「可疑」信号保留。

    return Verdict("suspect" if reasons else "ok", reasons)
