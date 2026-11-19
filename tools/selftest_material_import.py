"""使用临时数据库验证分科导入；不读取或写入正式库。"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

BOOK = """# 第一章 水循环
一、单项选择题
1. 下列哪种变化属于水的蒸发（ ）
A. 液体变为气体
B. 液体变为固体
解析：受热后的水分子离开液面。
2. 下列哪项有完整答案（ ）
A. 第一项
B. 第二项
# 第二章 地表
判断题
3. 河流会改变地表形态。
答案：正确
填空题
4. 液体变为气体叫作____。
答案：汽化
参考答案
1. A
2. C
"""


def run():
    import docx
    import pymupdf
    from fastapi.testclient import TestClient

    from app.core.db import SessionLocal
    from app.main import app
    from app.models.entities import Document

    def ok(response):
        assert response.is_success, (response.status_code, response.text)
        return response.json()

    with TestClient(app) as client:
        def subject(name, code):
            return ok(client.post("/api/subjects", json={"name": name, "code": code}))["id"]

        sid = subject("自然科学", "material_test")
        other = subject("自然科学乙", "material_other")

        def preview(name, data, kind="workbook", target=sid, **extra):
            return ok(client.post("/api/material-import/preview", files={"file": (name, data)},
                                  data={"subject_id": target, "kind": kind, **extra}))

        def action(draft, step="commit", **extra):
            return client.post(f"/api/material-import/{draft['draft_id']}/{step}",
                               json={"pages": draft["pages"], **extra})

        raw = BOOK.encode()
        draft = preview("../练习册.txt", raw)
        assert draft["filename"] == "练习册.txt"
        assert draft["candidate_count"] == 4 and draft["usable_count"] == 3, draft["issues"]
        assert draft["issues"][0]["number"] == 2
        assert ok(client.get("/api/questions", params={"subject_id": sid})) == []
        assert ok(client.get("/api/search", params={"subject_id": sid, "q": "蒸发"}))
        assert action(draft, pages=["", ""]).status_code == 422
        assert draft["sha256"] == hashlib.sha256(raw).hexdigest()
        assert ok(action(draft, "check"))["usable_count"] == 3

        result = ok(action(draft, make_paper=True))
        assert result["question_count"] == 3 and result["skipped"] == 1
        with SessionLocal() as db:
            doc = db.get(Document, result["document_id"])
            assert Path(doc.path).read_bytes() == raw
        assert ok(action(draft, make_paper=True))["already_imported"]
        assert client.post(f"/api/documents/{result['document_id']}/parse").status_code == 409

        qs = ok(client.get("/api/questions", params={"subject_id": sid}))
        assert len(qs) == 3 and all(q["kp_id"] for q in qs) and not any("完整答案" in q["stem"] for q in qs)
        assert ok(client.get("/api/questions", params={"subject_id": other})) == []
        q = next(q for q in qs if q["qtype"] == "single_choice")
        tf = next(q for q in qs if q["qtype"] == "true_false")
        search = ok(client.get("/api/search", params={"subject_id": sid, "q": "蒸发"}))
        assert str(q["id"]) in str(search) and q["stem"][:8] in str(search), search
        print("通过：预览无写库、纠错诊断、原件 SHA256、重复导入、搜索刷新、学科隔离")

        paper = ok(client.get(f"/api/papers/{result['paper_id']}"))
        assert len(paper["items"]) == 2 and paper["source_type"] == "own_material"
        pa = ok(client.post(f"/api/papers/{paper['id']}/attempts"))
        submitted = ok(client.post(f"/api/papers/attempts/{pa['id']}/submit", json={
            "answers": [{"question_id": q["id"], "user_answer": "B"},
                        {"question_id": tf["id"], "user_answer": "A"}],
            "duration_ms": 1000,
        }))
        assert submitted["score"] == 1 and submitted["objective_total"] == 2
        wrong = ok(client.get("/api/questions", params={"subject_id": sid, "wrong_only": "true"}))
        assert [r["id"] for r in wrong] == [q["id"]]
        metrics = ok(client.get(f"/api/advice/{sid}/analysis"))
        assert metrics["kpi"]["attempts"] == 2
        assert "等权" in metrics["data_note"] and metrics["kpi"]["mastery"] > 0
        print("通过：练习卷、交卷判分、错题归入、备考统计")

        doc = docx.Document()
        doc.add_paragraph("第一章 水循环")
        doc.add_paragraph("蒸发会让液态水转为水蒸气。")
        stream = io.BytesIO()
        doc.save(stream)
        textbook = preview("教材.docx", stream.getvalue(), "textbook")
        txt = ok(action(textbook))
        chunks = ok(client.get(f"/api/documents/{txt['document_id']}/chunks"))
        assert "水蒸气" in chunks[0]["content"]
        lookup = ok(client.get("/api/search", params={"subject_id": sid, "q": "水蒸气"}))
        assert any("水蒸气" in x["full"] and x["page_no"] is None for x in lookup["excerpts"])
        kp = ok(client.get(f"/api/kp/{q['kp_id']}"))
        assert "水蒸气" in kp["excerpts"][0]["text"]
        with SessionLocal() as db:
            from app.services.paper.cloze import _sentences, _pools
            assert list(_sentences(db, sid)) == []
            assert "第一章 水循环" not in _pools(db)["term_origin"]
        with SessionLocal() as db:
            from app.models.entities import Chunk
            assert db.get(Chunk, chunks[0]["id"]).kp_id == q["kp_id"]
        exported = ok(action(preview("新学科练习.txt", raw, target=other)))
        assert exported["question_count"] == 3
        print("通过：DOCX 教材入库、先习题后教材仍按同名章节关联、同文件可分科导入")

        with pymupdf.open() as pdf:
            page = pdf.new_page(width=600, height=240)
            page.insert_text((22, 65), "Water Cycle textbook", fontsize=30)
            clean = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")
            scan = pdf.new_page(width=600, height=240)
            scan.insert_image(scan.rect, stream=clean)
            combined = pdf.tobytes()
        image = preview("照片.png", clean, "textbook")
        assert image["ocr_pages"] == [1] and "water" in image["pages"][0].lower(), image["pages"]
        imagerec = ok(action(image))
        with SessionLocal() as db:
            assert db.get(Document, imagerec["document_id"]).doc_type == "img"
        pdfrec = preview("混合教材.pdf", combined, "textbook")
        assert pdfrec["ocr_pages"] == [2] and all("water" in s.lower() for s in pdfrec["pages"])
        pdfresult = ok(action(pdfrec))
        with SessionLocal() as db:
            assert {c.page_no for c in db.get(Document, pdfresult["document_id"]).chunks} == {1, 2}
        print("通过：真实图片 OCR、混合 PDF 逐页 OCR 回退、PDF 文件页码保存")

        # 保留 PDF 的合法结构，不靠改扩展名或损坏文件重现 413。
        with pymupdf.open() as book:
            for n in range(201):
                book.new_page().insert_text((35, 55), f"Calculus textbook chapter {n + 1}")
            book.embfile_add("padding.dat", hashlib.shake_256(b"material-size-test").digest(31 * 1024 * 1024))
            large_pdf = book.tobytes()
        assert len(large_pdf) > 30 * 1024 * 1024
        full_book = preview("高等数学教材.pdf", large_pdf, "textbook")
        assert len(full_book["pages"]) == 201 and full_book["ocr_pages"] == []
        assert ok(action(full_book))["chunk_count"] == 201
        print("通过：超过 30 MiB、201 页的整本教材可预览并入库")
        non_pdf = client.post("/api/material-import/preview", files={"file": ("大文本.txt", large_pdf)},
                              data={"subject_id": sid, "kind": "textbook"})
        assert non_pdf.status_code == 413 and "30 MiB" in non_pdf.json()["detail"]

        # OCR 后可补答案；禁用不明答案题，不允许空题库作为习题册提交。
        ambiguous = preview("缺标答.txt", "判断题\n1. 冬天所有河流都会结冰。".encode())
        assert action(ambiguous).status_code == 422
        assert ok(action(ambiguous, pages=["判断题\n1. 冬天所有河流都会结冰。\n答案：错"]))["question_count"] == 1
        assert client.post("/api/material-import/preview", data={"subject_id": sid, "kind": "textbook"},
                           files={"file": ("bad.exe", b"x")}).status_code == 415
        print("通过：无标答拒绝、手工校对补答、格式校验")
        from contextlib import redirect_stdout

        import audit_db_conventions as audit
        audit.DB = Path(os.environ["TTK_DATA_DIR"]) / "db" / "ttk.db"
        audit_output = io.StringIO()
        with redirect_stdout(audit_output):
            status = audit.main()
        assert status == 0, audit_output.getvalue()
        print("通过：导入后的库取值约定审计")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp:
        os.environ["TTK_DATA_DIR"] = temp
        from app.core.db import engine

        try:
            run()
        finally:
            engine.dispose()
