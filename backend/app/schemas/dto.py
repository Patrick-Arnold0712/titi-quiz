from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.entities import DocStatus, QuestionType, SourceType
from app.services.ingest.textnorm import shape_true_false
from app.services.quality import check_fields


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Subject ----------
class SubjectCreate(BaseModel):
    name: str
    code: str
    exam_name: str | None = None
    description: str | None = None


class SubjectOut(ORMModel):
    id: int
    name: str
    code: str
    exam_name: str | None = None
    description: str | None = None
    created_at: datetime | None = None


class KnowledgePointOut(ORMModel):
    id: int
    name: str
    chapter_id: int | None = None
    importance: float = 0.0
    frequency: int = 0
    tags: str | None = None
    # 页码用于「溯源到教材原文」，前端考点图谱要显示，别省
    page_start: int | None = None
    page_end: int | None = None


class ChapterOut(ORMModel):
    id: int
    name: str
    # parent_id 必须有：chapters 表里章和节混在一张表（parent_id=None 才是章），
    # 前端要靠它把 5 章 27 节拼成两层树，否则会平铺成 32 条
    parent_id: int | None = None
    order_index: int = 0
    summary: str | None = None
    page_start: int | None = None
    knowledge_points: list[KnowledgePointOut] = []


class SubjectDetail(SubjectOut):
    chapters: list[ChapterOut] = []
    knowledge_points: list[KnowledgePointOut] = []


def question_out(q) -> "QuestionOut":
    """ORM 题目 -> QuestionOut，并带上题面体检结论。

    **必须走这个函数**，不要直接 `QuestionOut.model_validate(orm)` ——
    那样 quality 会一直是默认的 "ok"。
    """
    o = QuestionOut.model_validate(q)
    o.quality = check_fields(q.qtype, q.stem or "", q.options, q.answer or "").level
    return o


# ---------- Document ----------
class DocumentOut(ORMModel):
    id: int
    subject_id: int | None = None
    title: str
    filename: str
    doc_type: str
    source_type: SourceType
    year: str | None = None
    status: DocStatus
    created_at: datetime | None = None


# ---------- Question ----------
class QuestionOption(BaseModel):
    key: str
    text: str


class QuestionCreate(BaseModel):
    subject_id: int | None = None
    chapter_id: int | None = None
    kp_id: int | None = None
    qtype: QuestionType
    stem: str
    options: list[QuestionOption] | None = None
    answer: str
    explanation: str | None = None
    difficulty: float = 0.5
    score: float = 0.0
    source_type: SourceType = SourceType.own_material
    year: str | None = None
    tags: str | None = None


class QuestionOut(ORMModel):
    """对外输出的题目。

    判断题要在这里做一次「整形」，因为它有两个坑：

    1. **没有选项** —— 题库里判断题的 `options` 是空的，前端按「有选项就渲染
       ABCD」的约定走，判断题就掉进了主观题分支，445 道题根本没法作答。
       这里统一补上 A=正确 / B=错误 两个选项。
    2. **答案写法五花八门** —— √ / 正确 / 对 / T 都表示「正确」。
       如果不归一，前端拿 `answer.includes("A")` 去比较永远为假。
       这里统一归一到 A / B。

    归一化口径与判分共用 `normalize_bool`，保证「给前端看的答案」和
    「判分用的答案」永远是同一个。
    """

    id: int
    subject_id: int | None = None
    chapter_id: int | None = None
    kp_id: int | None = None
    qtype: QuestionType
    stem: str
    options: list[QuestionOption] | None = None
    answer: str
    explanation: str | None = None
    difficulty: float = 0.5
    score: float = 0.0
    source_type: SourceType
    year: str | None = None
    tags: str | None = None
    created_at: datetime | None = None
    # 题面体检结论：ok / suspect / defective。
    # 前端据此决定「能不能作答」—— defective 的题不该渲染成可作答的样子，
    # 否则用户答了也判不了分，还会被记成错题。
    #
    # 刻意做成**普通字段、由接口层赋值**，而不是在 validator 里实时计算：
    # 答题卡接口会先把 answer 清空再下发，嵌套校验（PaperItemOut 包 QuestionOut）
    # 会再跑一次 validator，那时候所有题都会被算成「没有标准答案 -> defective」。
    # 这个坑踩过，别再改回去。
    quality: str = "ok"

    @model_validator(mode="after")
    def _shape_true_false(self):
        if self.qtype == QuestionType.true_false:
            # 这个 validator 可能被跑两次：一次是 model_validate(ORM)，
            # 一次是 FastAPI 对已经构造好的 QuestionOut 做响应序列化时再校验。
            # 第二次进来时 self.options 已经是 QuestionOption 对象，
            # 直接 **o 会炸（TypeError）。所以先统一拍平成 dict。
            plain = None
            if self.options:
                plain = [o.model_dump() if hasattr(o, "model_dump") else dict(o)
                         for o in self.options]
            opts, ans = shape_true_false(plain, self.answer)
            self.options = [QuestionOption(**o) for o in opts]
            self.answer = ans
        return self



# ---------- Generate ----------
class GenerateRequest(BaseModel):
    subject_id: int
    chapter_id: int | None = None
    kp_id: int | None = None
    qtype: QuestionType = QuestionType.single_choice
    count: int = Field(default=5, ge=1, le=50)
    difficulty: float = 0.5
    use_material: bool = True
    extra_instruction: str | None = None


# ---------- Attempt ----------
class AttemptCreate(BaseModel):
    question_id: int
    user_answer: str


class AttemptOut(ORMModel):
    id: int
    question_id: int
    user_answer: str | None = None
    is_correct: bool | None = None
    # 数据来源：manual（系统内作答）/ import_jlq（导入）/ reconstructed（推算）
    source: str | None = None
    created_at: datetime | None = None


# ---------- Analysis ----------
class ChapterCoverage(BaseModel):
    chapter_id: int | None = None
    chapter_name: str
    kp_count: int = 0
    question_count: int = 0
    covered: bool = False


class AnalysisOut(BaseModel):
    subject_id: int
    total_knowledge_points: int = 0
    total_questions: int = 0
    coverage_rate: float = 0.0
    by_chapter: list[ChapterCoverage] = []
    top_knowledge_points: list[KnowledgePointOut] = []

# ---------- Paper / 试卷 ----------
class PaperOut(ORMModel):
    id: int
    subject_id: int | None = None
    name: str
    year: str | None = None
    volume: str | None = None
    source_type: SourceType
    duration_min: int = 0
    total_score: float = 0.0
    blueprint: list[dict] | None = None
    note: str | None = None
    created_at: datetime | None = None

    # 题源构成 {"real_exam": 9, "refsite_chapter": 7, "predict": 4}。
    # 只认这三个桶（见 services/paper/sources.py）。由接口层现算，不落库 ——
    # 落库的话，题目被清理或改判之后就会和卷面不一致。
    source_mix: dict[str, int] | None = None

    # 做过没有、做过几次、最近一次多少分。
    # 一套卷可以被做多次（重做），所以「完成」要分两层：
    #   attempt_count  开过几次考（含做了一半丢在那儿的）
    #   done_count     交过几次卷 —— 界面上的「已完成」以它为准
    attempt_count: int = 0
    done_count: int = 0
    last_attempt_id: int | None = None
    last_status: str | None = None
    last_score: float | None = None
    last_submitted_at: datetime | None = None


class PaperItemOut(BaseModel):
    order_index: int
    section_name: str | None = None
    score_per: float = 0.0
    # 卷面上按什么题型呈现。判断题在「一、单项选择题」里就是单选题
    # （A=正确 / B=错误），不能还标成「判断」——
    # 用户看到卷面上是 A/B 选项，却被告知这是判断题，会以为系统算错了。
    display_qtype: str | None = None
    question: QuestionOut


class PaperDetail(PaperOut):
    items: list[PaperItemOut] = []


class GeneratePaperRequest(BaseModel):
    subject_id: int
    name: str
    duration_min: int = 60
    seed: int | None = None
    blueprint: list[dict] | None = None

    # 组卷参数面板用：
    #   每次组卷现造几道「教材原文挖空」自出题（0 = 不造）
    auto_cloze: int = Field(default=3, ge=0, le=10)
    # 挖空只从重要度不低于此值的考点里出（0 = 不设门槛）
    min_kp_importance: float = Field(default=0.0, ge=0.0, le=1.0)
    # 覆盖每个大题的题源配额：{"single_choice": {"real_exam": 9, ...}}
    mix: dict[str, dict[str, int]] | None = None


# ---------- 答卷 ----------
class AnswerIn(BaseModel):
    question_id: int
    user_answer: str = ""


class SubmitRequest(BaseModel):
    answers: list[AnswerIn] = []
    duration_ms: int = 0


class PaperAttemptOut(ORMModel):
    id: int
    paper_id: int
    status: str
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    duration_ms: int = 0
    score: float = 0.0
    objective_total: float = 0.0
    subjective_total: float = 0.0
    detail: dict | None = None
