from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuestionType(str, enum.Enum):
    """题型。"""

    single_choice = "single_choice"    # 单选题
    multi_choice = "multi_choice"      # 多选题
    true_false = "true_false"          # 判断题
    fill_blank = "fill_blank"          # 填空题
    short_answer = "short_answer"      # 简答题
    essay = "essay"                    # 论述题


# 蓝图 / 早先导入的数据里，qtype 用的是短名（"single" / "multi" / "short" …），
# 而 QuestionType 的枚举值是全名（single_choice …）。
# 两边混用会让前端按 qtype 分支的代码静默走错路 —— 真题卷的「不定项选择题」
# 就是这样被判成了单选。**凡是拿 qtype 跟枚举比的地方，先过这个函数**。
QTYPE_ALIASES = {
    "single": QuestionType.single_choice,
    "single_choice": QuestionType.single_choice,
    "multi": QuestionType.multi_choice,
    "multi_choice": QuestionType.multi_choice,
    "judge": QuestionType.true_false,
    "tf": QuestionType.true_false,
    "true_false": QuestionType.true_false,
    "fill": QuestionType.fill_blank,
    "fill_blank": QuestionType.fill_blank,
    "short": QuestionType.short_answer,
    "short_answer": QuestionType.short_answer,
    "essay": QuestionType.essay,
}


def canon_qtype(value) -> str | None:
    """把 qtype 的任意写法（短名/全名/枚举）统一成 QuestionType 的值。认不出来返回原样。"""
    if value is None:
        return None
    if isinstance(value, QuestionType):
        return value.value
    key = str(value).strip()
    hit = QTYPE_ALIASES.get(key)
    return hit.value if hit else key


class SourceType(str, enum.Enum):
    """题目/资料来源。"""

    own_material = "own_material"      # 自有资料
    authority = "authority"            # 权威平台资源
    real_exam = "real_exam"            # 历年真题
    generated = "generated"            # AI 生成


class DocStatus(str, enum.Enum):
    """资料处理状态。"""

    uploaded = "uploaded"
    parsed = "parsed"
    indexed = "indexed"
    failed = "failed"


class Subject(Base):
    """学科/科目。扩展新学科就是新增一条 Subject + 其章节。"""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    exam_name: Mapped[str | None] = mapped_column(String(128), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    knowledge_points: Mapped[list["KnowledgePoint"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(back_populates="subject")
    questions: Mapped[list["Question"]] = relationship(back_populates="subject")


class Chapter(Base):
    """章/节。"""

    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    parent_id: Mapped[int | None] = mapped_column(Integer, default=None)
    name: Mapped[str] = mapped_column(String(255))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    page_start: Mapped[int | None] = mapped_column(Integer, default=None)  # 教材印刷页码

    subject: Mapped["Subject"] = relationship(back_populates="chapters")
    knowledge_points: Mapped[list["KnowledgePoint"]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan"
    )


class KnowledgePoint(Base):
    """考点。分析、预测、出题都围绕它聚合。"""

    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), default=None
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    importance: Mapped[float] = mapped_column(Float, default=0.0)  # 0~1 重要度（预测用）
    frequency: Mapped[int] = mapped_column(Integer, default=0)     # 真题出现次数
    tags: Mapped[str | None] = mapped_column(String(255), default=None)
    page_start: Mapped[int | None] = mapped_column(Integer, default=None)  # 教材印刷页码
    page_end: Mapped[int | None] = mapped_column(Integer, default=None)
    source_doc_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None
    )

    subject: Mapped["Subject"] = relationship(back_populates="knowledge_points")
    chapter: Mapped["Chapter"] = relationship(back_populates="knowledge_points")


class Document(Base):
    """导入的资料：自有 PDF/Word、权威资源、历年真题。"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), default=None
    )
    title: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(512))
    doc_type: Mapped[str] = mapped_column(String(32))  # pdf/docx/txt/md/img
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType), default=SourceType.own_material
    )
    year: Mapped[str | None] = mapped_column(String(16), default=None)
    status: Mapped[DocStatus] = mapped_column(Enum(DocStatus), default=DocStatus.uploaded)
    meta: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    subject: Mapped["Subject"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """资料切分后的文本块，用于检索与溯源。"""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    kp_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), default=None
    )  # 该文本块归属的考点（教材切块时用）
    page_no: Mapped[int | None] = mapped_column(Integer, default=None)  # 教材印刷页码

    document: Mapped["Document"] = relationship(back_populates="chunks")


class Question(Base):
    """题目。真题、AI 生成题、自有题共用一张表，用 source_type 区分。"""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), default=None
    )
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), default=None
    )
    kp_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), default=None
    )
    qtype: Mapped[QuestionType] = mapped_column(Enum(QuestionType))
    stem: Mapped[str] = mapped_column(Text)                              # 题干
    options: Mapped[list | None] = mapped_column(JSON, default=None)    # [{"key":"A","text":"..."}]
    answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text, default=None)
    difficulty: Mapped[float] = mapped_column(Float, default=0.5)        # 0~1
    score: Mapped[float] = mapped_column(Float, default=0.0)
    kp_score: Mapped[float | None] = mapped_column(Float, default=None)   # 题目->考点 匹配置信度
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType), default=SourceType.generated
    )
    year: Mapped[str | None] = mapped_column(String(16), default=None)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None
    )
    tags: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    subject: Mapped["Subject"] = relationship(back_populates="questions")
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class QuestionMark(Base):
    """用户对单题的标记：收藏、心得笔记。

    参考站的 localStorage['jlq_v1'] 里有 fav / notes 两块，导入时落到这里。
    """

    __tablename__ = "question_marks"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16), default="fav")   # fav | note
    note: Mapped[str | None] = mapped_column(Text, default=None)
    source: Mapped[str | None] = mapped_column(String(32), default=None)   # 来源标记，如 refsite
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Paper(Base):
    """试卷。把「一套卷」显式建模——押题卷、真题卷、模拟卷共用。"""

    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), default=None
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None
    )
    name: Mapped[str] = mapped_column(String(255))
    year: Mapped[str | None] = mapped_column(String(32), default=None)
    volume: Mapped[str | None] = mapped_column(String(32), default=None)   # A卷 / B卷 / C卷
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType), default=SourceType.real_exam
    )
    duration_min: Mapped[int] = mapped_column(Integer, default=0)          # 考试时长（分钟）
    total_score: Mapped[float] = mapped_column(Float, default=0.0)
    blueprint: Mapped[list | None] = mapped_column(JSON, default=None)     # 题型×题数×分值
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list["PaperItem"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )
    attempts: Mapped[list["PaperAttempt"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class PaperItem(Base):
    """卷面题。记录题目在某套卷里的位置、所属大题和分值。"""

    __tablename__ = "paper_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer, default=0)        # 卷面题号
    section_index: Mapped[int] = mapped_column(Integer, default=0)      # 第几个大题
    section_name: Mapped[str | None] = mapped_column(String(128), default=None)
    score_per: Mapped[float] = mapped_column(Float, default=0.0)         # 该题分值

    paper: Mapped["Paper"] = relationship(back_populates="items")


class PaperAttempt(Base):
    """一份答卷。记录某套卷的一次作答与判分结果。"""

    __tablename__ = "paper_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="doing")  # doing / submitted
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    score: Mapped[float] = mapped_column(Float, default=0.0)             # 已判得分
    objective_total: Mapped[float] = mapped_column(Float, default=0.0)   # 客观题满分
    subjective_total: Mapped[float] = mapped_column(Float, default=0.0)  # 主观题满分（待人工）
    detail: Mapped[dict | None] = mapped_column(JSON, default=None)      # 分题型得分明细

    answers: Mapped[list["Attempt"]] = relationship(
        back_populates="paper_attempt", cascade="all, delete-orphan"
    )
    paper: Mapped["Paper"] = relationship(back_populates="attempts")


class Attempt(Base):
    """单题作答记录，用于错题本与薄弱点分析。"""

    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    paper_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_attempts.id", ondelete="CASCADE"), default=None
    )
    user_answer: Mapped[str | None] = mapped_column(Text, default=None)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, default=None)
    awarded_score: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 记录来源，用来区分「证据」和「推算」：
    #   manual        —— 在本系统里作答（最可信）
    #   import_jlq    —— 从外部刷题记录/错题夹导入（错题有据可查）
    #   reconstructed —— 由「做过 N 题、错 M 题」反推出来的答对记录（属于推算，可一键撤销）
    source: Mapped[str] = mapped_column(String(32), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    question: Mapped["Question"] = relationship(back_populates="attempts")
    paper_attempt: Mapped["PaperAttempt"] = relationship(back_populates="answers")


class KnowledgeBit(Base):
    """零碎知识条目：教材知识链接、年份、法律、著作。

    考前速查用。来源是教材正文和题目解析，按「提及次数」排序 ——
    提得越多，越可能考。
    """

    __tablename__ = "knowledge_bits"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), default=None
    )
    # link 知识链接 / year 年份 / law 法律文件 / work 著作
    kind: Mapped[str] = mapped_column(String(16), default="link")
    # 速查用的键：知识链接是标题，年份是 "1945年"，法律/著作是书名
    key: Mapped[str] = mapped_column(String(120))
    # 正文（知识链接全文；年份/法律/著作是多条摘录拼起来）
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    page_no: Mapped[int | None] = mapped_column(Integer, default=None)
    kp_id: Mapped[int | None] = mapped_column(Integer, default=None)
    kp_name: Mapped[str | None] = mapped_column(String(120), default=None)
    hits: Mapped[int] = mapped_column(Integer, default=1)   # 提及次数
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
