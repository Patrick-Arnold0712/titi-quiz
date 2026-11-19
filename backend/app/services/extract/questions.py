from __future__ import annotations

import re

from app.models.entities import QuestionType

CHAPTER_RE = re.compile(r"^《\s*(.+?)\s*》\s*章节?\s*$")
TYPE_RE = re.compile(r"^[一二三四五六七八九十]+\s*[、.．]\s*(单选题|多选题|判断题|填空题|简答题|论述题)")
QNUM_RE = re.compile(r"^(\d{1,3})\s*[、.．]\s*(.+)$")
OPT_LINE_RE = re.compile(r"^\s*[A-EＡ-Ｅ]\s*[.．、]")
OPT_PART_RE = re.compile(r"([A-EＡ-Ｅ])\s*[.．、]\s*")
NOISE_RE = re.compile(r"^(第\s*\d+\s*页|共\s*\d+\s*页|更多资料|》|军理|题库\s*\d*)\s*$")

_ANS = "A-Ea-exXＡ-Ｅ对错正确误√×"

TYPE_MAP = {
    "单选题": QuestionType.single_choice,
    "多选题": QuestionType.multi_choice,
    "判断题": QuestionType.true_false,
    "填空题": QuestionType.fill_blank,
    "简答题": QuestionType.short_answer,
    "论述题": QuestionType.essay,
}

_FULLWIDTH = {"Ａ": "A", "Ｂ": "B", "Ｃ": "C", "Ｄ": "D", "Ｅ": "E"}


def stitch_chunks(parts: list[str], max_overlap: int = 200) -> str:
    """把带重叠的切块拼接回原文，去掉重复部分。"""

    if not parts:
        return ""
    out = parts[0]
    for p in parts[1:]:
        n = min(len(out), len(p), max_overlap)
        k = 0
        for j in range(n, 0, -1):
            if out[-j:] == p[:j]:
                k = j
                break
        out += p[k:]
    return out


def _norm_key(k: str) -> str:
    return _FULLWIDTH.get(k, k)


def _split_answer(body: str) -> tuple[str, str | None]:
    # 1) 括号内含答案，如 （C）、（ABCDE）、（√）
    m = re.search(r"[（(]\s*([" + _ANS + r"]{1,12})\s*[)）]", body)
    if m:
        ans = re.sub(r"\s+", "", m.group(1))
        stem = (body[: m.start()] + body[m.end():]).strip().strip("：:。. ")
        return stem, ans
    # 2) 空括号 + 尾随字母，如 （）：A
    m = re.search(r"[（(]\s*[)）]\s*[：:]?\s*([A-E]{1,6})\s*[.。]?\s*$", body)
    if m:
        stem = re.sub(r"[：:]?\s*[A-E]{1,6}\s*[.。]?\s*$", "", body).strip()
        return stem, m.group(1)
    # 3) 句尾字母（前面是中文/全角符号）
    m = re.search(r"(?<=[^\x00-\x7f])\s*([A-E]{1,6})\s*[.。]?\s*$", body)
    if m:
        return body[: m.start()].strip(), m.group(1)
    return body.strip(), None


def _split_options(line: str) -> list[dict]:
    matches = list(OPT_PART_RE.finditer(line))
    opts: list[dict] = []
    for i, mt in enumerate(matches):
        start = mt.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
        text = line[start:end].strip()
        if text:
            opts.append({"key": _norm_key(mt.group(1)), "text": text})
    return opts


def parse_questions(text: str) -> list[dict]:
    lines = [ln.strip() for ln in text.split("\n")]
    chapter = None
    qtype = None
    questions: list[dict] = []
    cur: dict | None = None

    def flush() -> None:
        nonlocal cur
        if cur is not None and cur.get("stem"):
            questions.append(cur)
        cur = None

    for line in lines:
        if not line:
            continue

        m = CHAPTER_RE.match(line)
        if m:
            flush()
            chapter = m.group(1)
            continue

        m = TYPE_RE.match(line)
        if m:
            flush()
            qtype = TYPE_MAP.get(m.group(1))
            continue

        m = QNUM_RE.match(line)
        if m and qtype is not None:
            flush()
            stem, answer = _split_answer(m.group(2).strip())
            cur = {"chapter": chapter, "qtype": qtype, "stem": stem, "answer": answer, "options": []}
            continue

        if cur is not None and OPT_LINE_RE.match(line):
            cur["options"].extend(_split_options(line))
            continue

        if cur is not None:
            if NOISE_RE.match(line):
                continue
            if not cur["options"]:
                cur["stem"] = (cur["stem"] + " " + line).strip()
            else:
                cur["options"][-1]["text"] = (cur["options"][-1]["text"] + " " + line).strip()

    flush()
    return questions
