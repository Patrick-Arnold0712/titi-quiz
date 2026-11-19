"""导出供其他程序使用的只读题库数据库。

设计目标不是「把主库整个复制一份」，而是给外部程序一份**稳定、干净、只读**的接口：

- 只保留 subjects / chapters / knowledge_points / questions / question_options /
  documents / textbook_chunks；
- 不包含 attempts、paper_attempts、question_marks 等个人数据；
- 只导出通过 quality 检查的题（题面残缺题不进外部库）；
- 额外建好 `v_questions` 视图，外部程序不需要自己拼章节和选项。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.models.entities import canon_qtype
from app.services.ingest.textnorm import shape_true_false
from app.services.quality import check_fields

SCHEMA_VERSION = 1
OBJECTIVE = {"single_choice", "multi_choice", "true_false", "fill_blank"}


def _load_options(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []
    out = []
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            key = str(item.get("key") or chr(65 + i))
            text = str(item.get("text") or "")
        else:
            key, text = chr(65 + i), str(item)
        if key and text:
            out.append({"key": key, "text": text})
    return out


def _answer_text(qtype: str, answer: str, options: list[dict]) -> str:
    if qtype == "fill_blank" or not options:
        return answer or ""
    mapping = {o["key"]: o["text"] for o in options}
    letters = "".join(sorted(set(ch for ch in (answer or "").upper() if "A" <= ch <= "H")))
    return "  ".join(f"{key}. {mapping[key]}" for key in letters if key in mapping)


def build_export_db(target: Path, db_path: Path | None = None) -> dict:
    """把主库导出为外部只读 SQLite，返回统计信息。"""

    db_path = db_path or get_settings().db_path
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    src = sqlite3.connect(str(db_path))
    src.row_factory = sqlite3.Row
    out = sqlite3.connect(str(tmp))
    try:
        out.executescript(
            """
            PRAGMA journal_mode=DELETE;
            CREATE TABLE schema_version (
                version INTEGER NOT NULL,
                exported_at TEXT NOT NULL,
                source TEXT NOT NULL
            );
            CREATE TABLE subjects (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                exam_name TEXT,
                description TEXT
            );
            CREATE TABLE chapters (
                id INTEGER PRIMARY KEY,
                subject_id INTEGER NOT NULL,
                parent_id INTEGER,
                level INTEGER NOT NULL,
                name TEXT NOT NULL,
                order_index INTEGER NOT NULL,
                summary TEXT,
                page_start INTEGER
            );
            CREATE TABLE knowledge_points (
                id INTEGER PRIMARY KEY,
                subject_id INTEGER NOT NULL,
                chapter_id INTEGER,
                name TEXT NOT NULL,
                description TEXT,
                importance REAL NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                unit_id INTEGER,
                unit_name TEXT,
                lesson_name TEXT
            );
            CREATE TABLE questions (
                id INTEGER PRIMARY KEY,
                subject_id INTEGER NOT NULL,
                subject_code TEXT NOT NULL,
                subject_name TEXT NOT NULL,
                chapter_id INTEGER,
                unit_id INTEGER,
                unit_name TEXT,
                lesson_name TEXT,
                kp_id INTEGER,
                kp_name TEXT,
                qtype TEXT NOT NULL,
                stem TEXT NOT NULL,
                answer TEXT NOT NULL,
                answer_text TEXT,
                explanation TEXT,
                difficulty REAL,
                score REAL,
                source_type TEXT,
                year TEXT,
                tags TEXT
            );
            CREATE TABLE question_options (
                question_id INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                option_key TEXT NOT NULL,
                option_text TEXT NOT NULL,
                PRIMARY KEY (question_id, option_key)
            );
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                subject_id INTEGER,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                doc_type TEXT,
                source_type TEXT,
                year TEXT
            );
            CREATE TABLE textbook_chunks (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL,
                subject_id INTEGER,
                kp_id INTEGER,
                page_no INTEGER,
                content TEXT NOT NULL
            );
            CREATE INDEX idx_chapters_subject ON chapters(subject_id, parent_id);
            CREATE INDEX idx_kp_subject ON knowledge_points(subject_id, chapter_id);
            CREATE INDEX idx_q_subject ON questions(subject_id, chapter_id);
            CREATE INDEX idx_q_kp ON questions(kp_id);
            CREATE INDEX idx_q_qtype ON questions(qtype);
            CREATE INDEX idx_options_q ON question_options(question_id, sort_order);
            CREATE INDEX idx_chunks_kp ON textbook_chunks(kp_id, page_no);
            """
        )
        out.execute("INSERT INTO schema_version VALUES (?,?,?)", (
            SCHEMA_VERSION, datetime.now().isoformat(timespec="seconds"), str(db_path),
        ))

        subjects = [dict(r) for r in src.execute(
            "SELECT id, code, name, exam_name, description FROM subjects ORDER BY id"
        )]
        subjects_by_id = {s["id"]: s for s in subjects}
        out.executemany(
            "INSERT INTO subjects(id,code,name,exam_name,description) VALUES(?,?,?,?,?)",
            [(s["id"], s["code"], s["name"], s["exam_name"], s["description"]) for s in subjects],
        )

        chapter_rows = [dict(r) for r in src.execute(
            "SELECT id,subject_id,parent_id,name,order_index,summary,page_start FROM chapters ORDER BY subject_id,parent_id,order_index,id"
        )]
        chapter_by_id = {c["id"]: c for c in chapter_rows}
        units_by_id = {}
        for c in chapter_rows:
            c["level"] = 2 if c["parent_id"] is not None else 1
            if c["level"] == 1:
                units_by_id[c["id"]] = c
        out.executemany(
            "INSERT INTO chapters(id,subject_id,parent_id,level,name,order_index,summary,page_start) VALUES(?,?,?,?,?,?,?,?)",
            [(c["id"], c["subject_id"], c["parent_id"], c["level"], c["name"], c["order_index"], c["summary"], c["page_start"]) for c in chapter_rows],
        )

        kp_rows = []
        for k in src.execute(
            "SELECT id,subject_id,chapter_id,name,description,importance,page_start,page_end FROM knowledge_points ORDER BY subject_id,page_start,id"
        ):
            k = dict(k)
            lesson = chapter_by_id.get(k["chapter_id"])
            unit = units_by_id.get(lesson["parent_id"]) if lesson and lesson["parent_id"] else lesson
            k["unit_id"] = unit["id"] if unit else None
            k["unit_name"] = unit["name"] if unit else None
            k["lesson_name"] = lesson["name"] if lesson else None
            kp_rows.append(k)
        out.executemany(
            "INSERT INTO knowledge_points(id,subject_id,chapter_id,name,description,importance,page_start,page_end,unit_id,unit_name,lesson_name) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(k["id"], k["subject_id"], k["chapter_id"], k["name"], k["description"], k["importance"], k["page_start"], k["page_end"], k["unit_id"], k["unit_name"], k["lesson_name"]) for k in kp_rows],
        )
        kp_by_id = {k["id"]: k for k in kp_rows}

        q_rows = []
        option_rows = []
        for row in src.execute(
            "SELECT id,subject_id,chapter_id,kp_id,qtype,stem,options,answer,explanation,difficulty,score,source_type,year,tags FROM questions ORDER BY id"
        ):
            q = dict(row)
            qtype = canon_qtype(q["qtype"])
            options = _load_options(q["options"])
            tags = {part for part in (q.get("tags") or "").split("|") if part}
            if tags & {"noise", "dup"}:
                continue
            verdict = check_fields(qtype, q["stem"] or "", options, q["answer"] or "")
            if not verdict.usable:
                continue
            answer = q["answer"] or ""
            if qtype == "true_false":
                options, answer = shape_true_false(options, answer)
            subject = subjects_by_id.get(q["subject_id"], {})
            lesson = chapter_by_id.get(q["chapter_id"])
            unit = units_by_id.get(lesson["parent_id"]) if lesson and lesson["parent_id"] else lesson
            kp = kp_by_id.get(q["kp_id"])
            qtype = canon_qtype(qtype)
            q_rows.append({
                "id": q["id"], "subject_id": q["subject_id"],
                "subject_code": subject.get("code", ""), "subject_name": subject.get("name", ""),
                "chapter_id": q["chapter_id"], "unit_id": unit["id"] if unit else None,
                "unit_name": unit["name"] if unit else None,
                "lesson_name": lesson["name"] if lesson else None,
                "kp_id": q["kp_id"], "kp_name": kp["name"] if kp else None,
                "qtype": qtype, "stem": q["stem"], "answer": answer,
                "answer_text": _answer_text(qtype, answer, options),
                "explanation": q["explanation"], "difficulty": q["difficulty"],
                "score": q["score"], "source_type": q["source_type"], "year": q["year"],
                "tags": q["tags"],
            })
            for i, opt in enumerate(options):
                option_rows.append((q["id"], i, opt["key"], opt["text"]))
        out.executemany(
            "INSERT INTO questions(id,subject_id,subject_code,subject_name,chapter_id,unit_id,unit_name,lesson_name,kp_id,kp_name,qtype,stem,answer,answer_text,explanation,difficulty,score,source_type,year,tags) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(q["id"], q["subject_id"], q["subject_code"], q["subject_name"], q["chapter_id"], q["unit_id"], q["unit_name"], q["lesson_name"], q["kp_id"], q["kp_name"], q["qtype"], q["stem"], q["answer"], q["answer_text"], q["explanation"], q["difficulty"], q["score"], q["source_type"], q["year"], q["tags"]) for q in q_rows],
        )
        out.executemany(
            "INSERT INTO question_options(question_id,sort_order,option_key,option_text) VALUES(?,?,?,?)",
            option_rows,
        )

        docs = [dict(r) for r in src.execute(
            "SELECT id,subject_id,title,filename,doc_type,source_type,year FROM documents ORDER BY id"
        )]
        out.executemany(
            "INSERT INTO documents(id,subject_id,title,filename,doc_type,source_type,year) VALUES(?,?,?,?,?,?,?)",
            [(d["id"], d["subject_id"], d["title"], d["filename"], d["doc_type"], d["source_type"], d["year"]) for d in docs],
        )

        chunks = [dict(r) for r in src.execute(
            "SELECT c.id,c.document_id,d.subject_id,c.kp_id,c.page_no,c.content FROM chunks c JOIN documents d ON d.id=c.document_id ORDER BY c.document_id,c.order_index"
        )]
        out.executemany(
            "INSERT INTO textbook_chunks(id,document_id,subject_id,kp_id,page_no,content) VALUES(?,?,?,?,?,?)",
            [(c["id"], c["document_id"], c["subject_id"], c["kp_id"], c["page_no"], c["content"]) for c in chunks],
        )

        out.executescript(
            """
            CREATE VIEW v_questions AS
            SELECT q.id, q.subject_code, q.subject_name, q.unit_name, q.lesson_name,
                   q.kp_name, q.qtype, q.stem, q.answer, q.answer_text,
                   q.explanation, q.source_type, q.year,
                   GROUP_CONCAT(qo.option_key || '.' || qo.option_text, ' | ') AS options_text
            FROM questions q
            LEFT JOIN question_options qo ON qo.question_id = q.id
            GROUP BY q.id
            ORDER BY q.id;
            PRAGMA user_version = 1;
            """
        )
        out.commit()
        counts = {
            "subjects": len(subjects),
            "chapters": len(chapter_rows),
            "knowledge_points": len(kp_rows),
            "questions": len(q_rows),
            "options": len(option_rows),
            "documents": len(docs),
            "textbook_chunks": len(chunks),
            "path": str(target),
        }
    finally:
        src.close()
        out.close()
    os.replace(tmp, target)
    return counts


def ensure_export(target: Path, db_path: Path | None = None) -> dict:
    """按主库 mtime 判断是否需要重建，避免每次下载都全量导出。"""

    db_path = db_path or get_settings().db_path
    target = Path(target)
    if target.exists() and target.stat().st_mtime >= db_path.stat().st_mtime:
        con = sqlite3.connect(str(target))
        try:
            count = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        finally:
            con.close()
        return {"path": str(target), "questions": count, "reused": True}
    return build_export_db(target, db_path)


__all__ = ["SCHEMA_VERSION", "build_export_db", "ensure_export"]
