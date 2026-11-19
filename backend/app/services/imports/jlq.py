"""导入参考站（zhongshanjunli.netlify.app）的刷题记录。

支持两种来源：

**1. `jlq_v1` 原始 JSON**（推荐，信息最全）
   在参考站页面按 F12 打开控制台执行：
       copy(localStorage.getItem('jlq_v1'))
   结构：
       {
         "answers": {"ch1-single-1": "A", "ch1-single-2": "BC", ...},
         "wrong":   {"ch1-single-2": true, ...},
         "fav":     {"ch1-single-5": true},
         "notes":   {"ch1-single-2": "我把主体记成政府了"},
         "reveal":  {...}
       }
   `answers` 存的是「每题当前答案」，所以导入出来是**每题一条作答记录**（最新状态），
   不是完整作答历史——这是源数据的限制，站点本身也只存当前答案。

**2. 导出文本**（点「导出」下载的 .txt）
   没有 qid，只能靠题干模糊匹配。信息量少于 JSON（只有错题/收藏，没有答题历史）。

匹配方式：站点的 `qid`（如 `ch1-single-1`）在导入题库时已存进 `Question.tags`，
格式 `refsite:<qid>`。所以 JSON 导入可以**精确匹配、零误差**。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.entities import Attempt, Question, QuestionMark, QuestionType

OBJECTIVE = {QuestionType.single_choice, QuestionType.multi_choice, QuestionType.true_false}

PUNCT = re.compile(r"[\s,.，。、;；:：!！?？\"'“”‘’()（）\[\]【】《》<>/\-_—…·~`|\\^*#$%&+=]+")
LETTERS = re.compile(r"[A-H]")
TRUE_TOKENS = {"对", "正确", "√", "T", "TRUE", "是", "YES", "A", "1"}
FALSE_TOKENS = {"错", "错误", "×", "X", "F", "FALSE", "否", "NO", "B", "0"}


def norm(s: str) -> str:
    return PUNCT.sub("", unicodedata.normalize("NFKC", s or "")).strip().upper()


def letters(s: str) -> str:
    return "".join(sorted(set(LETTERS.findall((s or "").upper()))))


def to_bool(s: str) -> str | None:
    t = (s or "").strip().upper()
    return "A" if t in TRUE_TOKENS else ("B" if t in FALSE_TOKENS else None)


def judge(q: Question, ua: str) -> bool | None:
    """与 app.services.paper.scoring.judge_objective 口径一致。主观题返回 None。"""
    if q.qtype not in OBJECTIVE:
        return None
    if q.qtype == QuestionType.true_false:
        u, c = to_bool(ua), to_bool(q.answer or "")
        return None if (u is None or c is None) else u == c
    c = letters(q.answer or "")
    return None if not c else letters(ua) == c


@dataclass
class ImportReport:
    answered: int = 0
    correct: int = 0
    wrong: int = 0
    fav: int = 0
    notes: int = 0
    unmatched: list[str] = field(default_factory=list)
    subjective_skipped: int = 0
    type_corrected: int = 0
    unknown_qid_sample: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "answered": self.answered, "correct": self.correct, "wrong": self.wrong,
            "fav": self.fav, "notes": self.notes, "subjective_skipped": self.subjective_skipped,
            "题型自动纠正": self.type_corrected,
            "unmatched": len(self.unmatched), "unknown_qid_sample": self.unknown_qid_sample[:10],
        }


def detect_format(text: str) -> str:
    """识别三种输入：jlq_v1 JSON / 错题页复制 / 导出文本。

    判别依据：
      - 以 { [ 开头            -> jlq_v1 JSON
      - 开头是「共 N 题」       -> 错题页直接复制
      - 同时含「正确答案：」和「你的选择：」 -> 错题页直接复制
      - 含「错题夹」/「收藏夹」  -> 导出文本
    """
    t = text.lstrip()
    if t.startswith("{") or t.startswith("["):
        return "json"
    if re.match(r"^共\s*\d+\s*题", t):
        return "wrongpage"
    if "正确答案：" in text and "你的选择：" in text:
        return "wrongpage"
    if parse_qnum_list(text) is not None:
        return "qnums"
    return "text"


# ---------- 「错题页直接复制」格式 ----------
# 结构（每题 20 行左右）：
#     17.              <- 题号（行尾带点）
#     单选题            <- 题型
#     [✎ 已勘误]        <- 可选
#     [⭐ 已收藏]        <- 可选
#     第一章 中国国防     <- 章节
#     春秋时期提出…（　）。 <- 题干（可能多行）
#     A                <- 选项字母，单独一行
#     管仲✓ 正确答案      <- 选项文本 + 标记
#     B
#     商鞅✗ 你的选择
#     ❌ 回答错误
#     正确答案：A 你的选择：B
#     解析…（"解析"紧跟内容，没有冒号）
#     → 去练习本题
#     ☆ 收藏
#     ✓ 移出错题夹
#     📝 我的心得 / 易错点
#     在这里记录你的理解、记忆口诀或易错点……（自动保存）
#
# 关键：**题号 + 题型 + 章节 能直接拼出站点的 qid**（如 ch1-single-17），
# 所以这个格式也能精确匹配，不需要题干模糊匹配。

QT_ALIAS = {"单选题": "single", "多选题": "multi", "判断题": "judge",
            "简答题": "short", "论述题": "essay", "填空题": "fill"}

CHAPTER_GID = {
    "第一章 中国国防": "ch1", "第二章 国家安全": "ch2", "第三章 军事思想": "ch3",
    "第四章 现代战争": "ch4", "第五章 信息化装备": "ch5",
}

RE_QNUM = re.compile(r"^(\d{1,3})\.$")
RE_OPTKEY = re.compile(r"^([A-H])$")
RE_ANS_LINE = re.compile(r"^正确答案[：:]?\s*([A-H]*)\s*你的选择[：:]?\s*([A-H]*)$")
RE_RESULT = re.compile(r"^[❌✅]\s*回答(错误|正确)$")
RE_MARKER = re.compile(r"^[✎⭐🔖]\s*(已勘误|已收藏)$|^已勘误$|^已收藏$")
RE_PLACEHOLDER = re.compile(r"^在这里记录你的理解")
SKIP_HEADS = {"→ 去练习本题", "☆ 收藏", "⭐ 取消收藏", "✓ 移出错题夹", "📝 我的心得 / 易错点"}

OPT_FLAG = re.compile(r"\s*[✓✗]\s*(正确答案|你的选择)\s*$")


def parse_wrong_page(text: str) -> list[dict]:
    """解析「错题页直接复制」的文本，返回题目列表。"""
    lines = [l.rstrip() for l in text.splitlines()]
    out: list[dict] = []
    i = 0
    n = len(lines)
    while i < n:
        m = RE_QNUM.match(lines[i].strip())
        if not m:
            i += 1
            continue
        num = int(m.group(1))
        i += 1
        qtype = None
        chapter = None
        stem_lines: list[str] = []
        options: list[dict] = []
        answer = ""
        choice = ""
        explain = ""
        result = None
        favored = False

        # 题型
        while i < n and lines[i].strip() in ("",) :
            i += 1
        if i < n and lines[i].strip() in QT_ALIAS:
            qtype = QT_ALIAS[lines[i].strip()]
            i += 1
        # 可选标记 + 章节
        while i < n:
            t = lines[i].strip()
            if not t:
                i += 1
                continue
            if "已收藏" in t:
                favored = True; i += 1; continue
            if "已勘误" in t:
                i += 1; continue
            if t in CHAPTER_GID or re.match(r"^([ABC]卷|\d{4}级|[A-Z]卷)", t):
                chapter = t; i += 1; continue
            break
        # 题干：直到遇到选项字母行
        while i < n:
            t = lines[i].strip()
            if RE_OPTKEY.match(t):
                break
            if t in SKIP_HEADS or RE_RESULT.match(t) or RE_ANS_LINE.match(t):
                break
            if t:
                stem_lines.append(t)
            i += 1
        # 选项
        while i < n:
            mk = RE_OPTKEY.match(lines[i].strip())
            if not mk:
                break
            key = mk.group(1)
            i += 1
            txt = ""
            flag = None
            if i < n:
                raw = lines[i].rstrip()
                fm = OPT_FLAG.search(raw)
                if fm:
                    flag = fm.group(1)
                    raw = OPT_FLAG.sub("", raw)
                txt = raw.strip()
                i += 1
            options.append({"key": key, "text": txt, "flag": flag})
        # 结果 / 答案 / 解析
        while i < n:
            t = lines[i].strip()
            if RE_QNUM.match(t):
                break
            mr = RE_RESULT.match(t)
            if mr:
                result = mr.group(1) == "正确"; i += 1; continue
            ma = RE_ANS_LINE.match(t)
            if ma:
                answer, choice = ma.group(1), ma.group(2); i += 1; continue
            if t.startswith("解析"):
                explain = t[2:].strip(); i += 1; continue
            if t in SKIP_HEADS or RE_PLACEHOLDER.match(t) or not t:
                i += 1; continue
            if t.startswith("☆") or t.startswith("⭐") or t.startswith("✓") or t.startswith("→"):
                i += 1; continue
            i += 1

        out.append({
            "num": num, "qtype": qtype, "chapter": chapter,
            "stem": " ".join(stem_lines).strip(),
            "options": options, "answer": answer, "choice": choice,
            "explain": explain, "favored": favored, "result": result,
        })
    return out


def import_wrong_page(db: Session, subject_id: int, text: str,
                      *, replace: bool = False) -> ImportReport:
    """导入「错题页直接复制」的文本。题号+题型+章节 拼 qid，精确匹配。"""
    items = parse_wrong_page(text)
    rep = ImportReport()

    by_qid: dict[str, Question] = {}
    by_stem: dict[str, Question] = {}
    for q in db.query(Question).filter(Question.subject_id == subject_id).all():
        by_stem.setdefault(norm(q.stem), q)
        for part in (q.tags or "").split("|"):
            if part.startswith("refsite:"):
                by_qid[part[8:]] = q

    if not by_qid:
        raise ValueError("题库里没有参考站来源的题，请先运行 data/import_ref_site.py")

    if replace:
        # 清掉本学科参考站题目上的旧作答与标记（含之前的仿真数据）
        qids = [q.id for q in by_qid.values()]
        db.query(Attempt).filter(Attempt.question_id.in_(qids)).delete(synchronize_session=False)
        db.query(QuestionMark).filter(QuestionMark.question_id.in_(qids)).delete(
            synchronize_session=False)
        db.flush()

    for it in items:
        q = None
        gid = CHAPTER_GID.get(it["chapter"] or "")
        if gid and it["qtype"]:
            q = by_qid.get(f"{gid}-{it['qtype']}-{it['num']}")
        if q is None:
            q = by_stem.get(norm(it["stem"]))
        if q is None:
            rep.unmatched.append(it["stem"][:40] or f"#{it['num']}")
            if len(rep.unknown_qid_sample) < 10:
                rep.unknown_qid_sample.append(it["stem"][:40])
            continue

        ua = it["choice"] or ""
        rep.answered += 1
        ok = judge(q, ua)
        if ok is None:
            rep.subjective_skipped += 1
        elif ok:
            rep.correct += 1
        else:
            rep.wrong += 1
        db.add(Attempt(question_id=q.id, user_answer=ua, is_correct=ok,
                       awarded_score=0.0))
        if it["favored"]:
            db.add(QuestionMark(question_id=q.id, kind="fav", source="refsite"))
            rep.fav += 1
    db.commit()
    return rep


def import_jlq(db: Session, subject_id: int, payload: str | dict,
               *, replace: bool = False) -> ImportReport:
    """把 jlq_v1 记录导入库。replace=True 时先清掉本学科由导入产生的作答记录。"""
    fmt0 = detect_format(payload) if isinstance(payload, str) else "json"
    if fmt0 == "wrongpage":
        return import_wrong_page(db, subject_id, payload, replace=replace)
    if fmt0 == "qnums":
        return import_qnum_list(db, subject_id, payload, replace=replace)
    data = payload if isinstance(payload, dict) else json.loads(payload)
    rep = ImportReport()

    # qid -> Question
    by_qid: dict[str, Question] = {}
    for q in db.query(Question).filter(Question.subject_id == subject_id).all():
        tag = q.tags or ""
        for part in tag.split("|"):
            if part.startswith("refsite:"):
                by_qid[part[len("refsite:"):]] = q
    if not by_qid:
        raise ValueError("题库里没有参考站来源的题（tags 里找不到 refsite:<qid>）。请先运行 data/import_ref_site.py")

    if replace:
        qids = [q.id for q in by_qid.values()]
        db.query(Attempt).filter(Attempt.question_id.in_(qids)).delete(synchronize_session=False)
        db.query(QuestionMark).filter(QuestionMark.question_id.in_(qids)).delete(synchronize_session=False)
        db.flush()

    answers: dict = data.get("answers") or {}
    for qid, ua in answers.items():
        q = by_qid.get(qid)
        if q is None:
            rep.unmatched.append(qid)
            if len(rep.unknown_qid_sample) < 10:
                rep.unknown_qid_sample.append(qid)
            continue
        if q.qtype not in OBJECTIVE:
            rep.subjective_skipped += 1
            continue
        ok = judge(q, ua or "")
        rep.answered += 1
        if ok:
            rep.correct += 1
        else:
            rep.wrong += 1
        db.add(Attempt(question_id=q.id, user_answer=ua or "", is_correct=ok,
                       awarded_score=0.0))

    for qid in (data.get("fav") or {}):
        q = by_qid.get(qid)
        if q is None:
            continue
        db.add(QuestionMark(question_id=q.id, kind="fav", source="refsite"))
        rep.fav += 1

    for qid, note in (data.get("notes") or {}).items():
        q = by_qid.get(qid)
        if q is None or not (note or "").strip():
            continue
        db.add(QuestionMark(question_id=q.id, kind="note", note=str(note)[:2000],
                            source="refsite"))
        rep.notes += 1

    db.commit()
    return rep


# ---------- 文本导出格式 ----------
RE_HEAD = re.compile(r"^\[(?P<chap>[^\]]+)\]\s*(?P<num>\d+)\.\s*(?P<stem>.*)$")
RE_OPT = re.compile(r"^\s*([A-H])[.．、]\s*(.*)$")
RE_ANS = re.compile(r"^\s*答案[：:]\s*(?P<a>.*)$")
RE_YOUR = re.compile(r"^\s*你的答案[：:]\s*(?P<a>.*)$")


def parse_export_text(text: str) -> tuple[list[dict], list[dict]]:
    """解析导出的 .txt。返回 (错题列表, 收藏列表)，每条含 stem/answer/options。"""
    wrong: list[dict] = []
    fav: list[dict] = []
    bucket: list[dict] | None = None
    cur: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if "错题夹" in line:
            bucket = wrong
            continue
        if "收藏夹" in line:
            bucket = fav
            continue
        m = RE_HEAD.match(line.strip())
        if m and bucket is not None:
            cur = {"chapter": m.group("chap"), "num": int(m.group("num")),
                   "stem": m.group("stem").strip(), "options": [], "answer": ""}
            bucket.append(cur)
            continue
        if cur is None:
            continue
        mo = RE_OPT.match(line)
        if mo:
            cur["options"].append({"key": mo.group(1), "text": mo.group(2).strip()})
            continue
        ma = RE_ANS.match(line)
        if ma:
            cur["answer"] = ma.group("a").strip()
            continue
        if line.strip() and not RE_YOUR.match(line):
            if not cur["stem"].endswith(line.strip()):
                cur["stem"] += "\n" + line.strip()
    return wrong, fav


def import_export_text(db: Session, subject_id: int, text: str,
                       *, threshold: float = 0.90) -> ImportReport:
    """导入文本导出：没有 qid，只能按题干模糊匹配。"""
    wrong, fav = parse_export_text(text)
    rep = ImportReport()

    pool = db.query(Question).filter(Question.subject_id == subject_id).all()
    idx = {norm(q.stem): q for q in pool}

    def bigrams(s: str) -> set[str]:
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}

    def match(stem: str) -> Question | None:
        key = norm(stem)
        if len(key) < 6:
            return None
        hit = idx.get(key)
        if hit is not None:
            return hit
        kg = bigrams(key)
        best, bs = None, 0.0
        for k, q in idx.items():
            if abs(len(k) - len(key)) > 12:
                continue
            s = len(kg & bigrams(k)) / len(kg | bigrams(k))
            if s > bs:
                best, bs = q, s
        return best if bs >= threshold else None

    for item in wrong:
        q = match(item["stem"])
        if q is None:
            rep.unmatched.append(item["stem"][:40])
            continue
        rep.wrong += 1
        db.add(Attempt(question_id=q.id, user_answer="", is_correct=False, awarded_score=0.0))
    for item in fav:
        q = match(item["stem"])
        if q is None:
            rep.unmatched.append(item["stem"][:40])
            continue
        rep.fav += 1
        db.add(QuestionMark(question_id=q.id, kind="fav", source="refsite"))
    db.commit()
    return rep

# ---------- 极简格式：只报题号 ----------
# 错题夹里真正需要的信息只有「章节 + 题型 + 题号」，因为题干/选项/解析题库里都有，
# 而 `章节+题型+题号` 能直接拼出 qid（如 ch1-single-17），精确匹配。
#
# 支持的行格式（很宽松，容错）：
#     第一章 中国国防 单选: 17,22,24
#     第一章 中国国防  多选：55 60 63
#     第一章 中国国防
#     单选: 17,22,24
#     多选 55,60,63
#
# 章节名可写「第一章 中国国防」「第一章」「中国国防」「ch1」「A卷」；
# 题型可写「单选/单选题/single」「多选/多选题/multi」。

CHAPTER_ALIAS = {
    "第一章": "ch1", "中国国防": "ch1", "ch1": "ch1",
    "第二章": "ch2", "国家安全": "ch2", "ch2": "ch2",
    "第三章": "ch3", "军事思想": "ch3", "ch3": "ch3",
    "第四章": "ch4", "现代战争": "ch4", "ch4": "ch4",
    "第五章": "ch5", "信息化装备": "ch5", "ch5": "ch5",
    "A卷": "paperA", "B卷": "paperB", "C卷": "paperC",
    "paperA": "paperA", "paperB": "paperB", "paperC": "paperC",
}

QTYPE_ALIAS2 = {
    "单选": "single", "单选题": "single", "single": "single",
    "多选": "multi", "多选题": "multi", "不定项": "multi", "multi": "multi",
    "判断": "judge", "判断题": "judge", "judge": "judge",
    "简答": "short", "简答题": "short", "short": "short",
    "论述": "essay", "论述题": "essay", "essay": "essay",
}

NUM_SPLIT = re.compile(r"[\s,，、;；/]+")


def _chapter_of(token: str) -> str | None:
    tok = token.strip().replace(" ", "")
    for k, v in CHAPTER_ALIAS.items():
        if tok == k.replace(" ", "") or tok.startswith(k.replace(" ", "")):
            return v
    return None


def _qtype_of(token: str) -> str | None:
    tok = token.strip().replace(" ", "")
    return QTYPE_ALIAS2.get(tok)


def parse_qnum_list(text: str) -> list[dict] | None:
    """解析极简题号清单。识别不出来返回 None。"""
    out: list[dict] = []
    cur_ch: str | None = None
    seen_num = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head, _, tail = line.partition(":" if ":" in line else ("：" if "：" in line else "\x00"))
        if tail:
            # 同一行：章节? + 题型? + 题号
            ch = _chapter_of(head)
            if ch:
                cur_ch = ch
            qt = _qtype_of(head)
            if qt is None:
                # 可能是「第一章 中国国防 单选」这种，章节+题型挤在 head
                for tok in re.split(r"\s+", head):
                    qt = qt or _qtype_of(tok)
                    cur_ch = _chapter_of(tok) or cur_ch
            nums = [int(x) for x in NUM_SPLIT.split(tail) if x.strip().isdigit()]
            if qt and nums:
                out.extend({"gid": cur_ch, "qtype": qt, "num": n} for n in nums)
                seen_num = True
            continue
        # 没有冒号：可能是章节行，也可能是「题型 题号」行
        ch = _chapter_of(line)
        if ch and len(line) <= 20:
            cur_ch = ch
            continue
        parts = line.split()
        qt = _qtype_of(parts[0]) if parts else None
        nums = [int(x) for x in NUM_SPLIT.split(" ".join(parts[1:])) if x.strip().isdigit()]
        if qt and nums:
            out.extend({"gid": cur_ch, "qtype": qt, "num": n} for n in nums)
            seen_num = True

    if not seen_num:
        return None
    return out


def import_qnum_list(db: Session, subject_id: int, text: str,
                     *, replace: bool = False) -> ImportReport:
    """按题号清单导入错题（无「你的选择」，一律记为答错）。"""
    items = parse_qnum_list(text) or []
    rep = ImportReport()

    by_qid: dict[str, Question] = {}
    for q in db.query(Question).filter(Question.subject_id == subject_id).all():
        for part in (q.tags or "").split("|"):
            if part.startswith("refsite:"):
                by_qid[part[8:]] = q
    if not by_qid:
        raise ValueError("题库里没有参考站来源的题，请先运行 data/import_ref_site.py")

    if replace:
        qids = [q.id for q in by_qid.values()]
        db.query(Attempt).filter(Attempt.question_id.in_(qids)).delete(synchronize_session=False)
        db.query(QuestionMark).filter(QuestionMark.question_id.in_(qids)).delete(
            synchronize_session=False)
        db.flush()

    # 站点的题号是「按章统一编号」的：单选 1-50 / 多选 51-75 / 判断 76-100。
    # 也就是说 (章节, 题号) 在章内唯一 —— 所以题型写错也能定位。
    # 这很重要：用户抄题号时容易把「多选 82」写错（82 其实是判断），
    # 按 (gid, num) 兜底就免疫了这个问题。
    by_gid_num: dict[tuple[str, int], Question] = {}
    for qid, q in by_qid.items():
        m = re.match(r"^([a-z0-9]+)-[a-z]+-(\d+)$", qid)
        if m:
            by_gid_num[(m.group(1), int(m.group(2)))] = q

    corrected = 0
    for it in items:
        gid = it["gid"]
        if not gid:
            rep.unmatched.append(f"缺少章节: {it['qtype']}-{it['num']}")
            continue
        qid = f"{gid}-{it['qtype']}-{it['num']}"
        q = by_qid.get(qid)
        if q is None:
            alt = by_gid_num.get((gid, it["num"]))
            if alt is not None:
                q = alt
                corrected += 1
        if q is None:
            rep.unmatched.append(qid)
            if len(rep.unknown_qid_sample) < 10:
                rep.unknown_qid_sample.append(qid)
            continue
        rep.answered += 1
        rep.wrong += 1
        db.add(Attempt(question_id=q.id, user_answer="", is_correct=False, awarded_score=0.0))
    db.commit()
    rep.type_corrected = corrected
    return rep
