"""军事理论学科种子数据。

结构依据（权威优先）：
1. 《普通高等学校军事课教学大纲》（教体艺〔2019〕1 号）—— 军事理论 5 大模块。
2. 《中山大学 2026 级学生军事课教学实施方案》附件 1 —— 各模块教学内容。

约定：
- Chapter  = 大纲 5 大模块（中国国防 / 国家安全 / 军事思想 / 现代战争 / 信息化装备）。
- KnowledgePoint(一级) = 附件 1「内容」列拆出的教学主题，作为考点骨架。
- 细粒度二级考点在资料解析入库后，由考点抽取流程从教材/提纲补充，不在这里硬编码。

注意：中大 2026 方案的「专题讲座」（国家安全知识教育、国防大讲堂）按讲座计，
不构成知识章节，故不建 Chapter。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

import re

from app.models.entities import Chapter, KnowledgePoint, Subject

SYLLABUS = "《普通高等学校军事课教学大纲》（教体艺〔2019〕1号）"
CURRICULUM_SOURCE = "《中山大学2026级学生军事课教学实施方案》附件1"

MILITARY_THEORY = {
    "name": "军事理论",
    "code": "military_theory",
    "exam_name": "中山大学 军事理论（期末）",
    "description": (
        f"普通高等学校军事课。章节依据 {SYLLABUS} 的 5 大模块，"
        f"考点骨架依据 {CURRICULUM_SOURCE}。"
    ),
    "chapters": [
        {
            "name": "中国国防",
            "summary": "国防概述、国防教育、国防法规、国防建设、武装力量、国防动员。",
            "sections": [
                "一、国防概述、国防教育、国防法规",
                "二、国防建设、武装力量、国防动员",
            ],
            "points": [
                "国防概述",
                "国防教育",
                "国防法规",
                "国防建设",
                "武装力量",
                "国防动员",
            ],
        },
        {
            "name": "国家安全",
            "summary": "国家安全概述、国家安全形势、国际战略形势。",
            "sections": [
                "一、国家安全概述",
                "二、国家安全形势、国际战略形势",
            ],
            "points": [
                "国家安全概述",
                "国家安全形势",
                "国际战略形势",
            ],
        },
        {
            "name": "军事思想",
            "summary": "军事思想概述、外国军事思想、中国古代军事思想、当代中国军事思想。",
            "sections": [
                "一、军事思想概述、外国军事思想",
                "二、中国古代军事思想、当代中国军事思想",
            ],
            "points": [
                "军事思想概述",
                "外国军事思想",
                "中国古代军事思想",
                "当代中国军事思想",
            ],
        },
        {
            "name": "现代战争",
            "summary": "战争概述、新军事革命、机械化战争、信息化战争、混合战争。",
            "sections": [
                "一、战争概述、新军事革命",
                "二、机械化战争、信息化战争、混合战争",
            ],
            "points": [
                "战争概述",
                "新军事革命",
                "机械化战争",
                "信息化战争",
                "混合战争",
            ],
        },
        {
            "name": "信息化装备",
            "summary": (
                "信息化战争概述、信息化战争的特征与发展趋势、信息化战争与国防建设、"
                "信息化装备、作战平台和杀伤性武器。"
            ),
            "sections": [
                "一、信息化战争概述、信息化战争的特征与发展趋势、信息化战争与国防建设",
                "二、信息化装备、作战平台和杀伤性武器",
            ],
            "points": [
                "信息化战争概述",
                "信息化战争的特征与发展趋势",
                "信息化战争与国防建设",
                "信息化装备",
                "作战平台",
                "杀伤性武器",
            ],
        },
    ],
}


def norm_name(name: str) -> str:
    """去掉「第X章/第X节」前缀，用于宽松匹配已有章节，避免重复创建。"""
    return re.sub(r"^第[一二三四五六七八九十]+[章节]\s*", "", name or "").strip()


def _ensure_subject(db: Session) -> Subject:
    subject = db.query(Subject).filter(Subject.code == MILITARY_THEORY["code"]).one_or_none()
    if subject is None:
        subject = Subject(
            name=MILITARY_THEORY["name"],
            code=MILITARY_THEORY["code"],
            exam_name=MILITARY_THEORY["exam_name"],
            description=MILITARY_THEORY["description"],
        )
        db.add(subject)
        db.flush()
    else:
        # 描述随大纲更新，其余字段保持人工可编辑
        subject.description = MILITARY_THEORY["description"]
    return subject


def seed_military_theory(db: Session) -> Subject:
    """幂等同步：按名称补齐章节与一级考点，已存在的不删除、不覆盖。

    这样每次启动都安全；需要推倒重建时用 data/rebuild_structure.py。
    """

    subject = _ensure_subject(db)

    chapters = {
        norm_name(c.name): c
        for c in db.query(Chapter).filter(Chapter.subject_id == subject.id)
    }

    created_chapters = 0

    for order, spec in enumerate(MILITARY_THEORY["chapters"]):
        chapter = chapters.get(norm_name(spec["name"]))
        if chapter is None:
            chapter = Chapter(
                subject_id=subject.id,
                name=spec["name"],
                order_index=order,
                summary=spec["summary"],
            )
            db.add(chapter)
            db.flush()
            chapters[norm_name(spec["name"])] = chapter
            created_chapters += 1
        else:
            chapter.order_index = order
            chapter.summary = spec["summary"]

        # 注意：这里**不建考点**。
        # 考点（72 个三级目）来自教材目录，由 data/import_textbook_toc.py 导入。
        # 曾经在这里按「模块内容」建了 24 个粗考点，结果每次启动都追加一次，
        # 和教材派生的考点混在一起（72 -> 96），已移除。
    db.commit()
    db.refresh(subject)
    if created_chapters:
        print(f"[seed] 军事理论：新增章节 {created_chapters} 个")
    return subject


def seed_all(db: Session) -> None:
    seed_military_theory(db)
