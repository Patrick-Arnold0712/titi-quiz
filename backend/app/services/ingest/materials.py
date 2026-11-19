"""分科资料：提取、校对诊断和入库共用同一套规则。"""
from __future__ import annotations

import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from app.models.entities import (
    Chapter, Chunk, DocStatus, Document, KnowledgePoint, Paper, PaperItem,
    Question, QuestionType, SourceType,
)
from app.services.extract.questions import TYPE_MAP
from app.services.ingest.material_tags import IMPORT_MARK, SECTION_TAG
from app.services.ingest.ocr import ocr_image
from app.services.ingest.parsers import IMAGE_SUFFIXES, chunk_text, extract_text, sanitize
from app.services.ingest.textnorm import normalize_bool
from app.services.paper.scoring import normalize_letters
from app.services.quality import RE_BLANK, check_fields

MAX_PAGES = 1_000
MAX_CHARS = 2_000_000
MAX_BYTES = 30 * 1024 * 1024
# 整本扫描教材常超过普通上传限额；其他格式仍用原限制，避免大文本或图片撑满内存。
MAX_PDF_BYTES = 256 * 1024 * 1024
HEADING = re.compile(r"^#{1,6}\s+(.{1,120})$|^(第[〇零一二三四五六七八九十百\d]+[章节]\s*[^。！？]{0,70})$")
TYPE = re.compile(r"^(?:#{1,6}\s+|[一二三四五六七八九十]+[、.]\s*)?(单项选择题|多项选择题|不定项选择题|选择题|单选题|多选题|判断题|填空题|简答题|论述题)(?:$|[：:（( \t])")
NUMBER = re.compile(r"^(?:#{1,6}\s+)?(\d{1,5})\s*[.．、)）]\s*(.+)$")
ANSWER = re.compile(r"^(?:【(?:参考)?答案】|(?:参考)?答案\s*[:：])\s*(.*)$")
KEY_TITLE = re.compile(r"^(?:#{1,6}\s+)?(?:参考答案|答案汇总|答案)\s*[:：]?$")
OPTION_MARK = re.compile(r"(?<!\S)([A-HＡ-Ｈ])\s*[.．、)）]\s*")
NAMES = {v: k for k, v in TYPE_MAP.items()}


def extract_pages(path: Path, force_ocr: bool = False) -> tuple[list[str], list[int]]:
    suffix = path.suffix.lower()
    scanned = []
    if suffix == ".pdf":
        import pymupdf

        pages = []
        with pymupdf.open(path) as doc, tempfile.TemporaryDirectory() as tmp:
            if doc.needs_pass:
                raise ValueError("请先解密 PDF")
            if doc.page_count > MAX_PAGES:
                raise ValueError(f"每份 PDF 最多 {MAX_PAGES} 页，请分册上传")
            image = Path(tmp) / "page.png"
            char_count = 0
            for i, page in enumerate(doc, 1):
                text = page.get_text(sort=True)
                if force_ocr or len(text.strip()) < 12:
                    # 限制长边，避免非常规 PDF 页面渲染成超大位图。
                    zoom = min(2.5, 2400 / max(page.rect.width, page.rect.height, 1))
                    page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).save(str(image))
                    text = "\n".join(ocr_image(image))
                    scanned.append(i)
                pages.append(sanitize(text).strip())
                char_count += len(pages[-1])
                if char_count > MAX_CHARS:
                    raise ValueError("识别文本过长，请拆分文件后再导入")
    else:
        if suffix in IMAGE_SUFFIXES:
            scanned.append(1)
        if suffix in {".md", ".txt"}:
            pages = [sanitize(path.read_text(encoding="utf-8-sig")).strip()]
        elif suffix == ".docx":
            from docx import Document as WordDocument

            lines = []
            for par in WordDocument(str(path)).paragraphs:
                text = par.text.strip()
                if text:
                    style = par.style.style_id if par.style else ""
                    prefix = "# " if re.fullmatch(r"Heading[1-9]", style) else ""
                    lines.append(prefix + text)
            pages = [sanitize("\n".join(lines))]
        else:
            pages = [extract_text(path).strip()]
    validate_pages(pages)
    return pages, scanned


def validate_pages(pages: list[str]) -> None:
    if not pages or len(pages) > MAX_PAGES or sum(map(len, pages)) > MAX_CHARS:
        raise ValueError("资料页数或文本长度超出限制")
    if not any(p.strip() for p in pages):
        raise ValueError("未提取到文字，请检查扫描清晰度或文件编码（TXT/Markdown 使用 UTF-8）")


def split_title(line: str) -> str | None:
    hit = HEADING.fullmatch(line)
    return (hit[1] or hit[2]).strip() if hit else None


def parse_workbook(pages: list[str]) -> list[dict]:
    """只接受可追溯的标答；不从题尾孤立字母猜答案。"""
    rows, keys = [], defaultdict(list)
    current, chapter, qtype, in_key = None, None, None, False
    field = "stem"

    def flush():
        nonlocal current
        if current is not None:
            rows.append(current)
            current = None

    for page_no, page in enumerate(pages, 1):
        for raw in page.splitlines():
            line = raw.strip()
            if not line:
                continue
            norm = unicodedata.normalize("NFKC", line)
            if KEY_TITLE.fullmatch(norm):
                flush()
                in_key = True
                continue
            numbered = NUMBER.match(line)
            if in_key:
                if numbered:
                    keys[int(numbered[1])].append(numbered[2])
                continue
            if m := TYPE.match(norm):
                flush()
                label = m[1]
                alias = {
                    "单项选择题": QuestionType.single_choice, "多项选择题": QuestionType.multi_choice,
                    "不定项选择题": QuestionType.multi_choice,
                }
                qtype = TYPE_MAP.get(label) or alias.get(label)
                continue
            if title := split_title(line):
                flush()
                chapter, qtype = title, None
                continue
            if numbered:
                flush()
                current = dict(number=int(numbered[1]), page=page_no, chapter=chapter,
                               qtype=qtype, stem=numbered[2], options=[], answer="", explanation="")
                field = "stem"
                continue
            if current is None:
                continue
            if m := ANSWER.match(line):
                current["answer"] = m[1]
                field = "answer"
            elif m := re.match(r"^(?:【解析】|解析\s*[:：])\s*(.*)$", line):
                current["explanation"] = m[1]
                field = "explanation"
            elif field in ("stem", "options") and OPTION_MARK.match(line):
                # 保留数学符号等原文，只归一化选项的分隔符和编号。
                marks = list(OPTION_MARK.finditer(line))
                for i, mark in enumerate(marks):
                    end = marks[i + 1].start() if i + 1 < len(marks) else len(line)
                    current["options"].append({"key": unicodedata.normalize("NFKC", mark[1]),
                                               "text": line[mark.end():end].strip()})
                field = "options"
            elif field == "options":
                current["options"][-1]["text"] += " " + line
            else:
                current[field] = (current[field] + "\n" + line).strip()
    flush()
    counts = Counter(r["number"] for r in rows)
    for r in rows:
        key = keys.get(r["number"], [])
        if not r["answer"] and len(key) == counts[r["number"]] == 1:
            r["answer"] = key[0]
        answer = r["answer"].strip()
        kind, opts = r["qtype"], r["options"]
        r["issues"] = []
        issues = r["issues"]
        if not answer:
            issues.append("缺少可定位的标准答案")
        if opts or kind in (QuestionType.single_choice, QuestionType.multi_choice):
            answer = unicodedata.normalize("NFKC", answer)
            valid = re.fullmatch(r"[A-H](?:[\s,、/]*[A-H])*", answer.upper())
            letters = normalize_letters(answer) if valid else ""
            labels = [o["key"] for o in opts]
            if kind is None:
                kind = QuestionType.multi_choice if len(letters) > 1 else QuestionType.single_choice
            if kind not in (QuestionType.single_choice, QuestionType.multi_choice):
                issues.append("题型与选项冲突")
            if len(labels) < 2 or labels != list("ABCDEFGH"[:len(labels)]) or not all(o["text"].strip() for o in opts):
                issues.append("选项缺失、重复或编号不连续")
            if not letters or not set(letters) <= set(labels) or (kind == QuestionType.single_choice and len(letters) != 1):
                issues.append("标答与选项或单选题型不符")
            answer = letters
        elif kind == QuestionType.true_false:
            answer = normalize_bool(unicodedata.normalize("NFKC", answer)) or ""
            if not answer:
                issues.append("无法识别判断题标答")
        elif kind == QuestionType.fill_blank:
            if not RE_BLANK.search(r["stem"]):
                issues.append("填空题缺少设空")
        elif kind is None:
            issues.append("题型不明确，请补题型标题")
        r.update(qtype=kind, answer=answer)
        verdict = check_fields(kind, r["stem"], opts, answer)
        if not verdict.usable:
            issues.extend(verdict.reasons)
    return rows


def chapter_for(db, sid: int, name: str) -> Chapter:
    matches = db.query(Chapter).filter_by(subject_id=sid, name=name).order_by(Chapter.id).all()
    chapter = matches[0] if len(matches) == 1 else next((c for c in matches if c.parent_id is None), None)
    if not chapter:
        last = db.query(Chapter.order_index).filter_by(subject_id=sid).order_by(Chapter.order_index.desc()).first()
        chapter = Chapter(subject_id=sid, name=name, order_index=(last[0] + 1 if last else 1))
        db.add(chapter)
        db.flush()
    return chapter


def textbook_chunks(db, doc: Document, pages: list[str], default_chapter: str, paginated: bool) -> int:
    name = default_chapter or doc.title
    index = 0
    for pno, page in enumerate(pages, 1):
        pending = []

        def save():
            nonlocal index
            pieces = chunk_text("\n".join(pending))
            pending.clear()
            if not pieces:
                return
            chapter = chapter_for(db, doc.subject_id, name)
            kp = db.query(KnowledgePoint).filter_by(
                subject_id=doc.subject_id, chapter_id=chapter.id, source_doc_id=doc.id, name=name,
            ).first()
            if not kp:
                kp = db.query(KnowledgePoint).filter_by(
                    subject_id=doc.subject_id, chapter_id=chapter.id, source_doc_id=None,
                    name=name, tags=SECTION_TAG,
                ).first()
            if not kp:
                # 文件页号不冒充印刷页码，也不冒充历年考频。
                kp = KnowledgePoint(subject_id=doc.subject_id, chapter_id=chapter.id, name=name, tags=SECTION_TAG)
                db.add(kp)
            kp.source_doc_id = doc.id
            db.flush()
            for piece in pieces:
                db.add(Chunk(document_id=doc.id, kp_id=kp.id, order_index=index, content=piece,
                             char_count=len(piece), page_no=pno if paginated else None))
                index += 1

        for line in page.splitlines():
            if (title := split_title(line.strip())) and not default_chapter:
                save()
                name = title
            pending.append(line)
        save()
    return index


def practice_paper(db, doc: Document, questions: list[Question]) -> int | None:
    groups = defaultdict(list)
    for q in questions:
        # 现有试卷判分不支持填空；不把填空算作可自动评分的题。
        if q.qtype != QuestionType.fill_blank:
            groups[q.qtype].append(q)
    if not groups:
        return None
    blueprint = [{"section": NAMES[t], "qtype": t.value, "count": len(qs), "score_per": 1}
                 for t, qs in groups.items()]
    total = sum(len(qs) for qs in groups.values())
    paper = Paper(subject_id=doc.subject_id, document_id=doc.id, name=f"{doc.title[:245]} · 练习卷",
                  source_type=SourceType.own_material, total_score=total, duration_min=60,
                  blueprint=blueprint, note="题源为本次校对入库的习题；填空题不计入卷面；不是押题卷")
    db.add(paper)
    db.flush()
    order = 0
    for i, (kind, qs) in enumerate(groups.items(), 1):
        for q in qs:
            order += 1
            db.add(PaperItem(paper_id=paper.id, question_id=q.id, order_index=order,
                             section_index=i, section_name=NAMES[kind], score_per=1))
    return paper.id


def book_questions(db, doc: Document, rows: list[dict], default_chapter: str, make_paper: bool) -> dict:
    def identity(stem, qtype, options):
        # 同题干但不同选项的题不能合并；不折叠 x² 和 x2 等不同题面。
        return (qtype, " ".join(unicodedata.normalize("NFC", stem).split()),
                tuple((o["key"], " ".join(unicodedata.normalize("NFC", o["text"]).split()))
                      for o in options if isinstance(o, dict) and "key" in o and "text" in o))

    seen = {identity(q.stem, q.qtype, q.options or []) for q in
            db.query(Question).filter_by(subject_id=doc.subject_id).all()}
    added, duplicate = [], 0
    for row in rows:
        if row["issues"]:
            continue
        key = identity(row["stem"], row["qtype"], row["options"])
        if key in seen:
            duplicate += 1
            continue
        seen.add(key)
        name = default_chapter or row["chapter"] or doc.title
        ch = chapter_for(db, doc.subject_id, name)
        kps = db.query(KnowledgePoint).filter_by(subject_id=doc.subject_id, chapter_id=ch.id).limit(2).all()
        if not kps:
            kp = KnowledgePoint(subject_id=doc.subject_id, chapter_id=ch.id, name=name, tags=SECTION_TAG)
            db.add(kp)
            db.flush()
            kps = [kp]
        q = Question(subject_id=doc.subject_id, chapter_id=ch.id,
                     kp_id=kps[0].id if len(kps) == 1 else None,
                     document_id=doc.id, tags=f"{IMPORT_MARK}:page:{row['page']}",
                     source_type=SourceType.own_material, qtype=row["qtype"], stem=row["stem"],
                     options=row["options"] or None, answer=row["answer"], explanation=row["explanation"] or None)
        db.add(q)
        added.append(q)
    db.flush()
    return {"question_count": len(added), "duplicates": duplicate,
            "paper_id": practice_paper(db, doc, added) if make_paper else None}
