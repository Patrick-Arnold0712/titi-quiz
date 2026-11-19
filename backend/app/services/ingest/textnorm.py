"""教材文本归一化：处理 PDF 文字层里的三类「坑」。

这两类问题来自 PDF 内嵌字体子集，不是 OCR 错误，所以 OCR 工具解决不了：

1. 康熙部首（U+2F00–U+2FDF）：`⼀⼆⼈⼤` 之类，NFKC 归一化即可还原。
2. CJK 部首补充（U+2E80–U+2EFF）：`⺠⻓⻜` 之类，NFKC **无效**，需要手工映射。
   本模块的映射表覆盖了《大学军事课教程（试用）》全书实际出现的 23 个变体字。
3. 「版权保护」水印层：独立字体子集、无 ToUnicode 映射，抽出的是乱码标点，
   特征是几乎不含汉字。另有少量可读的水印行需要按字面过滤。
"""

from __future__ import annotations

import re
import unicodedata

# CJK 部首补充区中 NFKC 无法还原的简体部首形
RADICAL_MAP = str.maketrans({
    "\u2ea0": "民",  # ⺠
    "\u2ec1": "虎",  # ⻁
    "\u2ec4": "西",  # ⻄
    "\u2ec5": "见",  # ⻅
    "\u2ec6": "角",  # ⻆
    "\u2ec9": "贝",  # ⻉
    "\u2ecb": "车",  # ⻋
    "\u2ed3": "长",  # ⻓
    "\u2ed4": "门",  # ⻔
    "\u2ed8": "青",  # ⻘
    "\u2edb": "风",  # ⻛
    "\u2edc": "飞",  # ⻜
    "\u2edd": "食",  # ⻝
    "\u2ee2": "马",  # ⻢
    "\u2ee3": "骨",  # ⻣
    "\u2ee4": "鬼",  # ⻤
    "\u2ee5": "鱼",  # ⻥
    "\u2ee6": "鸟",  # ⻦
    "\u2ee8": "麦",  # ⻨
    "\u2ee9": "黄",  # ⻩
    "\u2eec": "齐",  # ⻬
    "\u2eee": "齿",  # ⻮
    "\u2ef0": "龙",  # ⻰
})

CJK = re.compile(r"[\u4e00-\u9fff]")

# 按字面出现的噪声行：水印 + 页眉书名
LITERAL_NOISE = {"版权保护", "版 权 保 护", "大学军事课教程"}
RE_ONLY_NUM = re.compile(r"^\d{1,3}$")
RE_PAGE_HEADER = re.compile(r"^\d{1,3}\s*(大学军事课教程|《军事理论》)?$")


def normalize_chars(text: str) -> str:
    """部首变体字 -> 标准汉字。"""
    return unicodedata.normalize("NFKC", text.translate(RADICAL_MAP))


def is_noise_line(line: str) -> bool:
    """判断一行是否属于水印 / 页眉页脚噪声。"""
    s = line.strip()
    if not s:
        return True
    if len(CJK.findall(s)) < 2:            # 水印乱码行
        return True
    if s.replace(" ", "") in LITERAL_NOISE:
        return True
    if RE_ONLY_NUM.match(s) or RE_PAGE_HEADER.match(s):   # 页码 / 页眉
        return True
    return False


def clean_page_text(raw: str) -> str:
    """清洗一页正文：归一化字符 + 去水印/页眉页脚 + 合并空行。"""
    text = normalize_chars(raw)
    keep = [ln.strip() for ln in text.splitlines() if not is_noise_line(ln)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()

# ---------- 判断题答案归一化 ----------
#
# 题库里判断题的标准答案写法五花八门：√ 正确 对 T A 1 / × 错误 错 X F B 0。
# 前端统一用 A（正确）/ B（错误）两个选项，所以入库和判分都必须先归一到 A/B。
# 这套映射原先只写在判分模块里，抽到这里是为了让 API 层也能用同一份口径 ——
# 否则「返回给前端的答案」和「判分用的答案」会各走各的，早晚对不上。
TRUE_TOKENS = {"对", "正确", "√", "T", "TRUE", "是", "YES", "A", "1", "V", "✓"}
FALSE_TOKENS = {"错", "错误", "×", "X", "F", "FALSE", "否", "NO", "B", "0", "╳"}


def normalize_bool(text: str | None) -> str | None:
    """判断题答案 -> "A"（正确）/ "B"（错误）/ None（认不出来）。"""
    t = (text or "").strip().upper()
    if t in TRUE_TOKENS:
        return "A"
    if t in FALSE_TOKENS:
        return "B"
    return None

# 判断题的统一展示选项：A=正确 / B=错误
TRUE_FALSE_OPTIONS: list[dict] = [
    {"key": "A", "text": "正确"},
    {"key": "B", "text": "错误"},
]


def shape_true_false(options, answer):
    """判断题整形：补上默认选项 + 把答案归一到 A/B。

    返回 (options, answer)。题库里判断题既没有选项、答案写法又五花八门，
    所有出口（题目列表 / 试卷 / 回看）都必须过这一道，否则前端渲染和判分会各说各话。
    """
    opts = options
    if not opts:
        opts = [dict(o) for o in TRUE_FALSE_OPTIONS]
    return opts, (normalize_bool(answer) or "")

# ---------- 页眉 / 页脚 ----------
#
# 教材每页顶部有页眉，形如：
#
#     重要手段。
#     第二章
#     国家安全57          ← 「章名 + 本页印刷页码」
#     它们利用西方的…
#
# 抽取时它落在正文中间，读起来就是「重要手段。第二章国家安全57它们利用…」。
# 通用正则不好写 —— 章名本身是正文用词，很容易误伤。
# 所以这里用「章名 + 本页页码」两个已知量精确匹配：
# 页码对不上就不动，误伤概率极低。

def running_header_pattern(chapter_name: str, page_no: int):
    """构造页眉正则：第X章 + <章名逐字允许空白> + <本页页码>。"""
    import re as _re

    name = _re.sub(r"\s+", "", _re.sub(r"^第[一二三四五六七八九十]+章", "", chapter_name or ""))
    if not name or not page_no:
        return None
    name_pat = r"\s*".join(_re.escape(c) for c in name)
    return _re.compile(rf"第[一二三四五六七八九十]+章\s*{name_pat}\s*{page_no}(?!\d)")


def strip_running_header(text: str, chapter_name: str, page_no: int | None) -> str:
    """删掉混进正文的页眉。页码未知时原样返回（宁可不删，不能删错）。"""
    if not text or not chapter_name or not page_no:
        return text
    pat = running_header_pattern(chapter_name, page_no)
    if pat is None:
        return text
    return pat.sub("\n", text)
