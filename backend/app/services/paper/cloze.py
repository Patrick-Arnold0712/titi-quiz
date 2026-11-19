"""教材挖空出题器：每次组卷现做几道「依据教材原文」的单选题。

## 为什么用挖空，而不是「让模型凭空写题」

这套系统**没有接大模型**（用户明确要求先不接），所以「自己出题」必须落成
可复现、可审计的规则。挖空恰好满足，而且有一个关键优势：
**每一道的题干都是教材原句**，天然不会偏、不会超纲。

## 三类挖空（按考情价值排序）

| 类型 | 挖什么 | 干扰项从哪来 | 为什么值得考 |
| --- | --- | --- | --- |
| `year` | 句子里的年份 | 教材和速查里出现过的其他年份 | 年份几乎是必考零碎知识 |
| `book` | 《书名》/法律名 | 同类（著作取著作、法律取法律） | 真题反复考「哪部著作/哪部法」 |
| `term` | 考点名/知识链接标题 | **同章**的其他术语 | 考核心概念定义 |

## 每道题都要满足的硬条件

1. **答案在句子里只出现一次**，且挖掉后句子里不再残留答案（防泄漏）
2. 句子长度 15~70 字，是完整的一句话
3. 干扰项与答案**不同**、不互相包含、长度接近（防「最长的那个就是答案」）
4. 选项顺序由种子打乱，答案位置随机
5. 落库时 `tags = predict:auto:<稳定hash>`，所以**重复组卷不会重复造题**
   —— 同一句挖同一个空只有一道，靠 seed 换题面组合

`explanation` 一律写「教材 p{页码}：原文」，可溯源、可人工复核。
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.services.ingest.material_tags import SECTION_TAG
from app.services.ingest.textnorm import strip_running_header
from app.models.entities import (
    Chapter,
    Chunk,
    KnowledgeBit,
    KnowledgePoint,
    Question,
    QuestionType,
    SourceType,
)

TAG_PREFIX = "predict:auto:"

MIN_LEN = 15
MAX_LEN = 70

RE_YEAR = re.compile(r"(1[5-9]\d{2}|20[0-2]\d)\s*年")
RE_BOOK = re.compile(r"《[^》]{2,28}》")
# 表格残留 / 图表引用 / 目录行 —— 这些句子挖出来不成话
RE_JUNK = re.compile(r"图\s?\d|表\s?\d|见\s?第|参考|习题|目录|略$")
CJK = re.compile(r"[\u4e00-\u9fff]")

PLACEHOLDER = "（　　）"

# 年份干扰项优先取同一「年代段」的，太远的太好排除
def _year_bucket(y: int) -> int:
    return y // 10


@dataclass
class Candidate:
    kind: str
    chunk_id: int
    kp_id: int
    chapter_id: int | None
    page_no: int | None
    sentence: str
    answer: str
    distractors: list[str] = field(default_factory=list)
    why: str = ""          # 混淆组的辨析，写进解析

    @property
    def key(self) -> str:
        raw = f"{self.kind}|{self.sentence}|{self.answer}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:10]

    @property
    def tag(self) -> str:
        return TAG_PREFIX + self.key


def _inside_paren(s: str, pos: int) -> bool:
    """判断位置 pos 是否落在某对括号里面。"""
    depth = 0
    for i, ch in enumerate(s):
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        if i == pos:
            return depth > 0
    return False


def _split_sentences(text: str) -> list[str]:
    out = []
    for s in re.split(r"(?<=[。；？！])", text or ""):
        s = re.sub(r"\s+", "", s).strip()
        if s:
            out.append(s)
    return out


def _sentences(db: Session, subject_id: int):
    """遍历教材正文（已挂考点的段落），产出 (句子, chunk, 考点)。"""
    kps = {k.id: k for k in db.query(KnowledgePoint).all()}
    chapters = {c.id: c for c in db.query(Chapter).all()}
    rows = (
        db.query(Chunk)
        .filter(Chunk.kp_id.isnot(None))
        .order_by(Chunk.page_no, Chunk.id)
        .all()
    )
    for c in rows:
        kp = kps.get(c.kp_id)
        # 上传教材允许查阅，不代表已纳入军理官方教材题源。
        if kp is None or kp.subject_id != subject_id or kp.tags == SECTION_TAG:
            continue
        # 先剥页眉。教材每页顶部是「章名 + 本页页码」，切块后会和正文粘成
        # 「国家安全81习近平主席在…」。这里复用教材切块那套精确匹配
        # （见 ingest/textnorm.py 的 strip_running_header）——
        # 通用正则会误伤，因为章名本身就是正文用词。
        ch = chapters.get(kp.chapter_id) if kp.chapter_id else None
        root = chapters.get(ch.parent_id) if ch and ch.parent_id else ch
        body = c.content or ""
        if root is not None and c.page_no:
            body = strip_running_header(body, root.name, c.page_no)
        if RE_JUNK.search(c.content or ""):
            # 段落级就直接跳过太狠了（junk 只影响个别句子），所以这里不跳，
            # 留给句子级过滤 —— 改这一行前先看 _ok_sentence。
            pass
        for s in _split_sentences(body):
            yield _strip_heading(s), c, kp
        # 长句子再按逗号/分号切一层「小句」。
        # 为什么必须切：用户点名要的「全民国防教育日」那句话有 90+ 字
        #   「2001年8月31日,第九届全国人民代表大会常务委员会第二十三次会议通过了
        #     《…决定》,确定每年9月的第三个星期六为全民国防教育日。」
        # 整句超长被长度闸挡掉，知识点就再也挖不出来。
        # 而它后半句「确定每年9月的第三个星期六为全民国防教育日」本身就是一道好题。
        for s in _split_sentences(body):
            if len(s) <= MAX_LEN:
                continue
            for part in re.split(r"[，,；;]", s):
                part = part.strip()
                if not part:
                    continue
                # 小句是硬切出来的，必须含「定义动词」才算一句完整的话：
                #   ✅「确定每年9月的第三个星期六为全民国防教育日」
                #   ❌「计划、实施预案与潜力统计调查」「特别措施和相关法律责任等」
                #      —— 这两个是长句里的列举残片，切出来读不通。
                if not re.search(r"[是为指包括称为叫作]", part):
                    continue
                if not re.search(r"[。！？]$", part):
                    part += "。"
                yield _strip_heading(part), c, kp


# 段落里的标题标记：「(八)战争保障」「1.物资储备」「三、机器人」。
# 它们和正文粘在同一行，不剥掉的话题干会变成
# 「(八)战争保障1.物资储备和后方补给（　　）指出,…」—— 一眼假。
RE_LEAD_HEADING = re.compile(r"^(?:[（(][一二三四五六七八九十百]+[）)]|[0-9０-９]+\s*[.、．]|[一二三四五六七八九十]+\s*[、.])\s*")
RE_CHAPTER_HEAD = re.compile(r"^第[一二三四五六七八九十百]+[章节]\s*[^,，。；]{0,20}?\d{0,3}")


# 教材侧栏标记：「★知识链接:」「★」—— 它不是正文，粘在题干里就是噪声
RE_SIDEBAR = re.compile(r"^\s*★+\s*(?:知识链接|知识拓展|小资料)?\s*[:：]?\s*")

# 句中残留小标题：正文被切成块时，「2.重视军事训练」这种编号标题
# 会和上下文粘成一句（「…临险亦2.重视军事训练《吴子》指出,…」）。
# 这种句子剥不干净，直接丢掉 —— 宁可少出题，不能出一眼假的题。
RE_MID_HEADING = re.compile(r"[0-9０-９]+\s*[.、．]\s*[\u4e00-\u9fff]{2,10}\s*(?=（|《)")


# 图注 / 表注：「图5-4粒子加速器」「表1-2国防法规」。
# 它们后面常常紧跟一个小标题再接正文，粘起来就是
#   「图5-4粒子加速器3.电磁炮电磁炮是利用电磁能代替化学发射药发射弹丸的…」
# 图注不剥掉，RE_JUNK 会把这句整个判掉（那正是「电磁炮」出不了题的原因）。
# 注意 `[^。，；：\d]` 里的 **\d**：图注标题不能吃掉后面的编号。
# 写成 `[^。，；：]{0,14}` 会把「粒子加速器3.电磁炮电磁炮是利」一起吞掉，
# 结果整句的术语没了，题也就出不来。
RE_CAPTION = re.compile(r"^\s*[图表]\s?\d+\s*(?:[-–—]\s*\d+)?\s*[^。，；：\d]{0,14}")


def _strip_heading(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        s = RE_CAPTION.sub("", s)
        s = RE_SIDEBAR.sub("", s)
        s = RE_LEAD_HEADING.sub("", s)
        s = RE_CHAPTER_HEAD.sub("", s)
    # 侧栏标题去掉了「★知识链接:」之后还会剩一个人名/术语，和正文连在一起：
    #   「克劳塞维茨卡尔·冯·克劳塞维茨1780年6月出生于…」
    # 判据：开头 4~10 个汉字在后面又出现了一次（中间隔着别的字）。
    # **长度下限必须是 4** —— 用 2 个字做判据会把「国防是…的基础，国防…」
    # 这种正常句子砍坏。
    # 先处理**相邻**重复：「3.电磁炮电磁炮是利用电磁能…」
    # 这是「小标题 + 正文首词」粘连，剥掉一次即可，且不会有误伤。
    # 注意循环要覆盖到 3 字：下面那条通用规则的下限是 4 字，
    # 漏掉 3 字会让「电磁炮」这种三字术语永远出不了题。
    for k in range(8, 1, -1):
        if s[:k] and s[:k] == s[k:2 * k]:
            s = s[k:]
            break
    # 再处理**非相邻**重复：「克劳塞维茨卡尔·冯·克劳塞维茨1780年…」
    for k in range(10, 3, -1):
        head = s[:k]
        if len(head) >= 4 and all("\u4e00" <= ch <= "\u9fff" for ch in head) and head in s[k:]:
            s = s[k:].lstrip(":：,，。、 ")
            break
    return s.strip()


def _ok_sentence(s: str) -> bool:
    if not (MIN_LEN <= len(s) <= MAX_LEN):
        return False
    # **必须是一句完整的话**。教材切块会在一页末尾截断，
    # 「在1914—（　　）的第一次世界大战中,火炮、机枪的强大」这种半截题不能要。
    if not re.search(r"[。！？]$", s):
        return False
    if RE_JUNK.search(s):
        return False
    # 至少 60% 是汉字，滤掉公式/乱码行
    if len(CJK.findall(s)) / max(len(s), 1) < 0.6:
        return False
    if s.count("（") != s.count("）"):
        return False
    # 引号也要闭合 —— 不闭合说明这句子是从中间截断的
    if s.count("“") != s.count("”"):
        return False
    if RE_MID_HEADING.search(s):
        return False
    # 以收尾标点开头的句子，说明它是从引文中间截出来的
    if s[0] in "”’）)、，。；：":
        return False
    # 短标题粘在句子前面：「战争的性质《司马法》指出,…」「战争与主观指导（　　）明确指出,…」
    # 判据是「开头 2~10 个汉字后紧接《或设空」—— 正常句子在这之间会有动词或标点。
    if re.match(r"^[\u4e00-\u9fff0-9]{2,12}(《|（　　）)", s):
        return False
    # 段落标题和正文粘在一起时会出现「三、传统领域的国家安全(一)政治安全政治安全主要包括…」
    # 这种短语原样重复。剥不干净，直接丢。
    # 阈值取 2 字：实测 3 字时漏掉「民兵民兵是中国共产党领导的…」这类。
    # 代价是「屡屡/常常」这种叠词句子会被一起丢掉 —— 可接受，反正候选够多。
    if re.search(r"(.{2,10}?)\1", s):
        return False
    # 句首两个字在紧接着的 30 字里又出现一次 —— 标题粘连的残留特征。
    # 例：「邓小平新时期军队建设思想的基本内容邓小平新时期军队建设思想是一个完整…」
    # 前面的剥离规则会按最长匹配切在词中间，剩下「思想的基本内容…」；
    # 这种切法没法靠剥离修好，只能整句丢掉。
    # 窗口取 30 字、只比两个字，是为了不误伤「中国人民的抗日战争是二战的重要组成部分」
    # 这类正经句子（句首「中国」后面不再出现）。
    # 只针对「XX的…」这种标题残留（「思想的基本内容…」）。
    # **不能放宽成「句首 2 字再现」** —— 那样会把「电磁炮是利用…电磁能…」
    # 这类正常句子一起枪毙（实测「电磁炮」因此彻底出不了题）。
    # 加 s[2] == "的" 这个限制后，误伤面就只剩「XX的…」这一种形态。
    if len(s) > 12 and s[2:3] == "的" and s[:2] in s[2:30]:
        return False
    # 剥掉标题粘连之后，句首剩下一个虚词，说明是从短语中间切开的：
    #   「毛泽东军事思想的科学含义 毛泽东军事思想是…」→ 剥掉重复的标题后剩下「的科学含义…」
    # 只收虚词。**不能把「中」也放进来** ——「中国人民的抗日战争是…」这种正经句子
    # 就是以「中」开头的，加了会把一大批题误杀（实测候选从 184 掉到 45）。
    if s[0] in "的得地和与及并而是":
        return False
    # 一行里没有任何内部标点、却出现两次「是」—— 两行正文被粘成一句的典型特征：
    #   「国防动员的行为主体是国家国防是国家根本利益所在」
    # **不能放宽成「无标点且长」**：那样会砍掉 38% 的句子（实测 1125/2936），
    # 而真正出问题的是这一小撮粘连句。
    if len(s) > 22 and not re.search(r"[，、；：]", s) and s.count("是") >= 2:
        return False
    # 开头是 1~3 位的「X年/X月/X日」= 四位数年份被切块截断了
    # （「9年4月23日成立华东军区海军的日期为…」，原文是 1949年）。
    # 四位数的正常年份不受影响，因为 \d{1,3} 匹配不上「1949」+「年」。
    if re.match(r"^\d{1,3}\s*[年月日]", s):
        return False
    # 列举式残句：「《国防法》的主要内容:1明确国防建设的方针、原则。」—— 后面还有 2、3、4，
    # 挖了空也读不通。
    if re.search(r"[:：]\s*[0-9０-９]+\s*[\u4e00-\u9fff]", s):
        return False
    # 本身就是一道带空的题（题库里混进来的），不能再挖
    if "（　" in s or "____" in s or "＿＿" in s:
        return False
    return True


CONFUSABLE_FILE = Path(__file__).with_name("confusable_terms.json")

# 定义句的「前导词」：术语出现在这种词后面时，整句就是在定义它。
#   「…确定每年9月的第三个星期六为全民国防教育日。」
# 这类句子的术语在句尾，前面是「为/是/称为」，只看后面（RE_DEF_TAIL）会漏掉。
RE_DEF_HEAD = re.compile(r"(为|是|称为|叫做|叫作|即|标志着)$")


def load_confusable_groups() -> dict[str, dict]:
    """读人工指定的「易混淆名词组」。

    放在后端包内而不是 data/ —— 后端不能依赖数据脚本目录，
    否则分享包（不含 data/）一启动就找不到文件。这个坑在 kpmap.py 上踩过一次。
    文件缺失时返回空字典，出题器退化成「纯算法找相似词」，不影响出题。
    """
    if not CONFUSABLE_FILE.exists():
        return {}
    try:
        payload = json.loads(CONFUSABLE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    out: dict[str, dict] = {}
    for g in payload.get("groups") or []:
        ans = (g.get("answer") or "").strip()
        conf = [str(x).strip() for x in (g.get("confuse") or []) if str(x).strip()]
        if not ans or len(conf) < 3:
            continue
        out[ans] = {"confuse": conf, "why": (g.get("why") or "").strip()}
    return out


def _similarity(a: str, b: str) -> tuple[int, int]:
    """返回 (最长公共后缀长度, 最长公共前缀长度)。"""
    suf = 0
    while suf < min(len(a), len(b)) and a[-1 - suf] == b[-1 - suf]:
        suf += 1
    pre = 0
    while pre < min(len(a), len(b)) and a[pre] == b[pre]:
        pre += 1
    return suf, pre


def _is_confusable(a: str, b: str) -> bool:
    """两个术语算不算「容易混」。

    判据是实测调出来的，太松会把「抗日战争」和「智能化战争」凑成一对 ——
    它们只共享「战争」这个类别词，学生根本不会混。

        共享后缀 ≥ 3 字        例如 信息化战争 / 智能化战争（共享「化战争」）
        共享前缀 ≥ 3 字        例如 中国人民武装警察部队 / 中国人民解放军（共享「中国人民」）
        共享 ≥ 2 字且长度相同   例如 传统领域的国家安全 / 新兴领域的国家安全
    """
    if a == b or len(a) < 4 or len(b) < 4:
        return False
    suf, pre = _similarity(a, b)
    if suf >= 3 or pre >= 3:
        return True
    return suf >= 2 and len(a) == len(b)


def _pools(db: Session):
    """构建干扰项池。"""
    bits = db.query(KnowledgeBit).all()
    kps = db.query(KnowledgePoint).filter(KnowledgePoint.tags.is_distinct_from(SECTION_TAG)).all()
    chunks = db.query(Chunk).filter(Chunk.kp_id.in_([k.id for k in kps])).all()
    years = {int(m.group(1)) for b in bits if b.kind == "year"
             for m in [re.match(r"(\d{4})", b.key or "")] if m}
    for c in chunks:
        for m in RE_YEAR.finditer(c.content or ""):
            years.add(int(m.group(1)))
    # 著作池：速查里的 work 是从教材正文按《》扫出来的，
    # 里面混着《变形金刚》《机械公敌》这种影视作品 ——
    # 判据用「是否在多段正文里反复出现」：真正的考点著作会反复被提，
    # 顺带一提的影视名只出现一次。
    body = "\n".join(c.content or "" for c in chunks)
    def _recur(title: str) -> int:
        return body.count("《" + title + "》")
    works = {b.key.strip("《》") for b in bits
             if b.kind == "work" and b.key and _recur(b.key.strip("《》")) >= 2}
    laws = {b.key.strip("《》") for b in bits
            if b.kind == "law" and b.key and _recur(b.key.strip("《》")) >= 1}
    links = {b.key for b in bits if b.kind == "link" and b.key}

    chapters = {c.id: c for c in db.query(Chapter).all()}
    # 术语池按「章」分桶 —— 干扰项要取同章的其他术语，
    # 否则「射程外」的术语一眼就排除掉了，题就成了送分题。
    terms_by_chapter: dict[int, set[str]] = {}
    term_origin: dict[str, str] = {}
    for k in kps:
        ch = chapters.get(k.chapter_id)
        root = (ch.parent_id or ch.id) if ch else None
        if root is None:
            continue
        name = k.name
        # 「XX的内涵」「XX的类型」这类标题式考点名不适合当术语挖空
        # 标题式考点名（「XX的内涵」「XX的现状」）当选项很怪，剔掉。
        # 判据是结尾词 —— 一个能被挖空的术语，不会以这些词收尾。
        # 「XX概述」「XX现状」是节标题，不是可挖的术语 ——
        # 它当干扰项时和正确答案（「亚洲基础设施投资银行」这类专名）
        # 一比就露馅：太抽象的那个一定不是答案。
        if re.search(r"(概述|现状|概况|简介|综述|导论|通论)$", name):
            continue
        if re.search(r"(的内涵|的类型|的启示|的现状|的概况|的意义|的内容|的成就|"
                     r"的概述|的分类|的作用|的地位|的原则|的特点|的趋势|的影响|"
                     r"的发展|的形态|的基本内容|的基本特征|的演变|的发展趋势|"
                     r"的主要动因|的辩证关系)$", name):
            continue
        # 太长的考点名当选项会「一眼就是它」，也不合适
        if len(name) > 12:
            continue
        # 带冒号的考点名（「典型案例:伊拉克战争」）当选项一眼就露馅 —— 选项里没人这么写
        if re.search(r"[:：、]", name):
            continue
        terms_by_chapter.setdefault(root, set()).add(name)
        term_origin[name] = "kp"
    for b in bits:
        if b.kind == "link" and b.key:
            ch_id = None
            kp = next((k for k in kps if k.id == b.kp_id), None)
            if kp and kp.chapter_id in chapters:
                ch = chapters[kp.chapter_id]
                ch_id = ch.parent_id or ch.id
            if ch_id:
                terms_by_chapter.setdefault(ch_id, set()).add(b.key)
                term_origin[b.key] = "link"
    # 人工指定的混淆组：把 answer 也塞进术语池（它可能不是考点名，
    # 例如「全民国防教育日」），并把干扰项和辨析一起带上。
    confuse_groups = load_confusable_groups()
    for ans, info in confuse_groups.items():
        for t in [ans] + info["confuse"]:
            # 人工组里的术语可能不在教材里（如「全民国家安全教育日」）——
            # 它只作为**干扰项**出现，不需要有句子，所以也放进池子供相似度比较。
            #
            # **必须加进每一个章**，不能只加进第一个章：
            # 原先是 `for root in ...: add; break`，等于把混淆词只挂在某一个章上，
            # 而 harvest 是按「句子所属章」取术语池的 —— 结果 37 组里 24 组成了死配置
            # （词在池里，但碰不到任何句子）。改这一行前先想清楚这一点。
            for root in terms_by_chapter:
                terms_by_chapter[root].add(t)
            term_origin[t] = "link"

    return {
        "confuse_groups": confuse_groups,
        "term_origin": term_origin,
        "years": sorted(years),
        "works": sorted(works),
        "laws": sorted(laws),
        "links": sorted(links),
        "terms_by_chapter": terms_by_chapter,
    }


def _near_years(years: list[int], answer: int, k: int) -> list[int]:
    """取同年代段优先的年份干扰项。"""
    same = [y for y in years if y != answer and _year_bucket(y) == _year_bucket(answer)]
    other = [y for y in years if y != answer and y not in same]
    pool = same + other
    return pool[:max(k * 3, 12)]


# 影视/小说类上下文：后面跟着书名号的多半是作品名，不是考点著作
RE_FICTION_CTX = re.compile(r"(电影|影片|小说|动画|动漫|游戏|电视剧|漫画)\s*$")

# 定义式句式：答案落在「主语位」才适合挖
RE_DEF_TAIL = re.compile(r"^(是|是指|指的是|指|包括|主要包括|分为|可分|由|即)")


def harvest(db: Session, subject_id: int, *, min_importance: float = 0.0) -> list[Candidate]:
    """把教材里所有可挖的句子扫成候选。

    顺序按「考点重要度」降序 —— 这是「考情预测」的落点：
    高频考点的句子排前面，`ensure_pool` 优先造它们。
    """
    pools = _pools(db)
    years = pools["years"]
    works_laws = set(pools["works"]) | set(pools["laws"])
    out: list[Candidate] = []
    kp_importance = {k.id: (k.importance or 0.0) for k in db.query(KnowledgePoint).all()}

    for s, c, kp in _sentences(db, subject_id):
        if min_importance and kp_importance.get(kp.id, 0.0) < min_importance:
            continue
        if not _ok_sentence(s):
            continue
        ch = db.get(Chapter, kp.chapter_id) if kp.chapter_id else None
        root = (ch.parent_id or ch.id) if ch else None

        # ---- ① 年份 ----
        m = RE_YEAR.search(s)
        if m:
            # 括号里的年份区间（「(1954—2010)」）挖出来会变成「(1954—（　　）)」，
            # 括号套括号，一眼就是机器生成的。跳过。
            if _inside_paren(s, m.start()):
                m = None
        if m:
            year = int(m.group(1))
            token = m.group(0)
            rest = s.replace(token, "", 1)
            if str(year) not in rest:
                # 干扰项不能和题干里已有的年份撞车：
                # 句子是「在1914—（　　）的第一次世界大战中」时，
                # 把 1914 当干扰项 = 送分（它在题干里明摆着）。
                near = [str(y) + "年" for y in _near_years(years, year, 6)
                        if str(y) not in s]
                # 也不能和答案差得太近（同一年代段里挑，但不含答案本身）
                near = [x for x in near if x != token][:12]
                if len(near) >= 3:
                    out.append((kp_importance.get(kp.id, 0.0),
                                Candidate("year", c.id, kp.id, root, c.page_no, s, token, near[:3])))
                    continue

        # ---- ② 书名 / 法律 ----
        b = RE_BOOK.search(s)
        if b:
            title = b.group(0)
            inner = title.strip("《》")
            before = s[: b.start()]
            rest = s.replace(title, "", 1)
            keep = (
                inner in works_laws                      # 必须在速查池里（= 教材里反复出现的真著作）
                and inner not in rest                    # 防泄漏
                and not RE_FICTION_CTX.search(before)    # 「电影《变形金刚》」不是考点著作
            )
            if keep:
                same = pools["works"] if inner in pools["works"] else pools["laws"]
                near = [f"《{x}》" for x in same
                        if x != inner and x not in rest and inner not in x and x not in inner
                        and abs(len(x) - len(inner)) <= 4]
                if len(near) >= 3:
                    out.append((kp_importance.get(kp.id, 0.0),
                                Candidate("book", c.id, kp.id, root, c.page_no, s, title, near[:3])))
                    continue

        # ---- ③ 混淆名词 / 考点术语 ----
        if root is None:
            continue
        terms = pools["terms_by_chapter"].get(root, set())
        if not terms:
            continue
        groups = pools["confuse_groups"]

        best = None
        curated = None
        for t in sorted(terms, key=len, reverse=True):
            # 术语短于 4 字一般不挖（噪声太多），但**人工组里的除外** ——
            # 「电磁炮」「府兵制」「火箭军」都是三字高频考点，
            # 一刀切按 4 字拦会把它们全挡在门外。
            if (len(t) < 4 and t not in groups) or t not in s:
                continue
            pos = s.index(t)
            tail = s[pos + len(t):]
            head = s[:pos]
            near_start = pos <= 2 and s.lstrip("“\"").startswith(t)
            # 三种「这句话在定义它」的形态：
            #   ① 术语后面紧跟 是/指/包括…     ② 术语前面是 为/是/称为…（在句尾）
            #   ③ 术语就在句首
            # 其余位置挖出来猜不到答案，属于坏题不是难题。
            if not (RE_DEF_TAIL.match(tail) or RE_DEF_HEAD.search(head) or near_start):
                continue
            rest = s.replace(t, "", 1)
            if t in rest:
                continue
            best = t
            if t in groups:
                curated = groups[t]
                break
        if not best:
            continue
        rest = s.replace(best, "", 1)

        # ---- 干扰项：优先用「容易混的」----
        # 这是这个题型存在的全部意义：选项之间只差一两个字，
        # 学生背混了就一定选错。所以干扰项不能随便取同章术语。
        distractors: list[str] = []
        why = ""
        if curated:
            distractors = [x for x in curated["confuse"] if x != best and x not in s][:3]
            why = curated["why"]
        if len(distractors) < 3:
            kin = sorted(
                [t for t in terms
                 if t != best and t not in s and t not in best and best not in t
                 and _is_confusable(best, t)],
                key=lambda t: (-max(_similarity(best, t)), abs(len(t) - len(best)), t),
            )
            for t in kin:
                if t not in distractors:
                    distractors.append(t)
                if len(distractors) >= 3:
                    break
        # 还不够就放宽相似度再补一轮：只要共享 2 字就收。
        # 直接用「同来源词」补会让选项变成大杂烩 ——
        # 「中国人民解放军」题的干扰项里冒出「习近平强军思想」，一眼就知道不对。
        if len(distractors) < 3:
            loose = sorted(
                (t for t in terms
                 if t not in distractors and t != best and t not in s
                 and t not in best and best not in t
                 and max(_similarity(best, t)) >= 2),
                key=lambda t: (-max(_similarity(best, t)), abs(len(t) - len(best)), t),
            )
            for t in loose:
                if t not in distractors:
                    distractors.append(t)
                if len(distractors) >= 3:
                    break
        # 最后才退回「同来源 + 长度接近」
        if len(distractors) < 3:
            origin = pools["term_origin"]
            extra = sorted(
                [t for t in terms if t != best and t not in s and t not in best
                 and best not in t and t not in distractors],
                key=lambda t: (0 if origin.get(t) == origin.get(best) else 1,
                               abs(len(t) - len(best)), t),
            )
            distractors += extra[: 3 - len(distractors)]
        if len(distractors) < 3:
            continue

        # 有人工辨析、或前两个干扰项里就有相似词 → 算「混淆名词」
        # 人工指定组一律算「混淆名词」；否则要求 3 个干扰项里至少 2 个是真相似词，
        # 只有 1 个的话凑出来的还是大杂烩，不如退化成普通术语题（同章选词更整齐）。
        strong = curated is not None or sum(
            1 for d in distractors[:3] if _is_confusable(best, d)) >= 2
        imp = kp_importance.get(kp.id, 0.0)
        out.append((imp, Candidate("confuse" if strong else "term", c.id, kp.id, root,
                                   c.page_no, s, best, distractors[:3], why)))

        # 同一句话再出一道「说法辨析」题。
        # 两类题训练点不同：挖空题考「这个表述属于哪个名字」，
        # 辨析题考「这个说法本身是对是错」，更接近真题里的辨析判断。
        # key 里带 kind，所以两道题是两个独立的稳定 hash，不会互相覆盖。
        if strong and RE_DISCRIMINATIVE.search(s):
            out.append((imp, Candidate("distinguish", c.id, kp.id, root,
                                       c.page_no, s, best, distractors[:3], why)))

    # 高频考点优先 —— 这就是「依据考情预测」：重要度高的先造
    out.sort(key=lambda x: (-x[0], x[1].kind, x[1].key))
    seen: set[str] = set()
    uniq: list[Candidate] = []
    for _, cand in out:
        if cand.key in seen:
            continue
        seen.add(cand.key)
        uniq.append(cand)
    return uniq


# 判别性标记：句子里有这些，说明它是**这个概念的专属表述**，
# 把主语换成另一个概念后几乎必然为假。辨析题（把 A 的定义安到 B 头上）必须以此为前提，
# 否则换名之后可能仍然成立 —— 那就等于出了一道错题。
#   「确定每年9月的第三个星期六为全民国防教育日」→ 换成「全民国家安全教育日」必假 ✓
RE_DISCRIMINATIVE = re.compile(
    r"\d|《|简称|又称|称为|成立于|首次|第一个|唯一|确定为|共\s*\d+\s*章|"
    r"开始于|始于|止于|标志着|诞生于"
)


def build_distinguish(cand: Candidate, rng: random.Random) -> dict | None:
    """辨析题：「下列关于 A 和 B 的说法，正确的是（　　）」。

    四个选项是**同一句教材原文**，只把主语换成组内的不同名词：

         ✅ 确定每年9月的第三个星期六为全民国防教育日。
         ❌ 确定每年9月的第三个星期六为全民国家安全教育日。
         ❌ 确定每年9月的第三个星期六为国家宪法日。
         ❌ 确定每年9月的第三个星期六为全国防灾减灾日。

    这就是真题里那种「说法辨析」题 —— 学生必须知道这个表述**属于哪个概念**，
    光认得名词没用。前提是原句含判别性标记（见 RE_DISCRIMINATIVE）。
    """
    names = [cand.answer] + [d for d in cand.distractors if d != cand.answer][:3]
    if len(names) < 4:
        return None
    if not RE_DISCRIMINATIVE.search(cand.sentence):
        return None

    texts = [cand.sentence if n == cand.answer
             else cand.sentence.replace(cand.answer, n, 1) for n in names]
    if len(set(texts)) != 4:
        return None

    order = list(range(4))
    rng.shuffle(order)
    keys = "ABCD"
    options = [{"key": keys[i], "text": texts[order[i]]} for i in range(4)]
    answer = keys[order.index(0)]
    partner = names[1]
    return {
        "stem": f"「{cand.answer}」与「{partner}」容易混淆，下列关于它们的说法，正确的是（　　）。",
        "options": options,
        "answer": answer,
        "explanation": (f"辨析题（概念—表述对应）｜正确答案：「{cand.answer}」——"
                        f"教材 p{cand.page_no}：{cand.sentence}"
                        + (f"｜辨析：{cand.why}" if cand.why else "")),
        "kind": "distinguish",
    }


def build_question(cand: Candidate, rng: random.Random) -> dict:
    """把候选变成题目字典（不落库）。"""
    if cand.kind == "distinguish":
        built = build_distinguish(cand, rng)
        if built is not None:
            return built
    stem = cand.sentence.replace(cand.answer, PLACEHOLDER, 1)
    opts = [cand.answer] + list(cand.distractors[:3])
    opts = list(dict.fromkeys(opts))
    rng.shuffle(opts)
    keys = "ABCD"
    options = [{"key": keys[i], "text": t} for i, t in enumerate(opts)]
    answer = keys[opts.index(cand.answer)]
    kind_label = {"year": "年份", "book": "著作/法律",
                  "term": "考点术语", "confuse": "易混淆名词",
                  "distinguish": "说法辨析"}.get(cand.kind, cand.kind)
    return {
        "stem": stem,
        "options": options,
        "answer": answer,
        "explanation": (f"教材 p{cand.page_no}：{cand.sentence}"
                        f"（{kind_label}挖空，由教材原文自动生成，供押题练习）"
                        + (f"｜辨析：{cand.why}" if cand.why else "")),
        "kind": cand.kind,
    }


def ensure_pool(db: Session, subject_id: int, *, want: int, seed: int,
                min_importance: float = 0.0) -> tuple[list[Question], int]:
    """确保题库里至少有 want 道**新的**自动自出题可用；返回 (本卷可用的自动题, 新造了几道)。

    每次组卷调一次：把还没造过的候选造出来，造满了就不再新增
    （候选总数受教材句子数限制，不会无限膨胀）。
    """
    rng = random.Random(seed)
    existing = {
        (q.tags or "").split("|")[0]
        for q in db.query(Question).filter(Question.tags.like(f"{TAG_PREFIX}%")).all()
    }
    cands = [c for c in harvest(db, subject_id, min_importance=min_importance)
             if c.tag not in existing]

    # **按类型轮转取**，而不是直接取重要度最高的前 N 道。
    # harvest 是按考点重要度排的，年份题在教材里密度最高，
    # 不轮转的话每次组卷造出来的全是年份题 —— 用户要的是「几道自出题」，不是「几道年份题」。
    by_kind: dict[str, list[Candidate]] = {}
    for c in cands:
        by_kind.setdefault(c.kind, []).append(c)
    for lst in by_kind.values():
        rng.shuffle(lst)
    # 混淆名词排在第二个：它的复习价值最高（背混了必错），
    # 但也要留位置给年份题（同样高频），所以不排第一。
    order = ["year", "confuse", "distinguish", "book", "term"]
    picked: list[Candidate] = []
    i = 0
    while len(picked) < want and any(by_kind.get(k) for k in order):
        k = order[i % len(order)]
        if by_kind.get(k):
            picked.append(by_kind[k].pop(0))
        i += 1
    # 轮转取不满（某类没候选了）就用剩下的补
    if len(picked) < want:
        rest = [c for k in order for c in by_kind.get(k, [])]
        picked += rest[: want - len(picked)]

    made: list[Question] = []
    for cand in picked:
        payload = build_question(cand, rng)
        q = Question(
            subject_id=subject_id,
            chapter_id=cand.chapter_id,
            kp_id=cand.kp_id,
            qtype=QuestionType.single_choice,
            stem=payload["stem"],
            options=payload["options"],
            answer=payload["answer"],
            explanation=payload["explanation"] + f"｜类型 {cand.kind}｜教材 p{cand.page_no}",
            source_type=SourceType.generated,
            tags=cand.tag + f"|kp{cand.kp_id}",
            score=2.0,
        )
        db.add(q)
        made.append(q)
    if made:
        db.flush()
    return made, len(made)
