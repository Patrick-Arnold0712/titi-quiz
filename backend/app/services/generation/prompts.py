from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import Chapter, KnowledgePoint, QuestionType
from app.schemas.dto import GenerateRequest

TYPE_LABEL = {
    QuestionType.single_choice: "单选题（四选一，只有一个正确选项）",
    QuestionType.multi_choice: "多选题（可选多个正确选项）",
    QuestionType.true_false: "判断题（答案为 对 或 错）",
    QuestionType.fill_blank: "填空题（空格用 ____ 表示）",
    QuestionType.short_answer: "简答题",
    QuestionType.essay: "论述题",
}

ANSWER_FORMAT = {
    QuestionType.single_choice: "answer 为单个选项字母，如 \"A\"",
    QuestionType.multi_choice: "answer 为选项字母组合，如 \"ACD\"",
    QuestionType.true_false: "answer 为 \"对\" 或 \"错\"",
    QuestionType.fill_blank: "answer 为填空内容的字符串",
    QuestionType.short_answer: "answer 为参考答案要点",
    QuestionType.essay: "answer 为论述参考答案",
}


def build_generation_prompt(db: Session, req: GenerateRequest) -> list[dict[str, str]]:
    context_parts: list[str] = []
    if req.chapter_id is not None:
        chapter = db.get(Chapter, req.chapter_id)
        if chapter is not None:
            context_parts.append(f"章节：{chapter.name}")
            if chapter.summary:
                context_parts.append(f"章节要点：{chapter.summary}")
    if req.kp_id is not None:
        kp = db.get(KnowledgePoint, req.kp_id)
        if kp is not None:
            context_parts.append(f"考点：{kp.name}")
    if req.extra_instruction:
        context_parts.append(f"额外要求：{req.extra_instruction}")
    context = "\n".join(context_parts) if context_parts else "（未指定，覆盖该学科重点）"

    system = (
        "你是一位高校军事理论课程的资深命题专家，熟悉教学大纲与历年真题风格。"
        "你出的题目必须知识点准确、表述严谨、选项干扰合理，难度贴合本科期末考。"
        "只输出 JSON，不要输出任何解释性文字。"
    )

    user = f"""请围绕以下范围命制 {req.count} 道{TYPE_LABEL[req.qtype]}，难度约 {req.difficulty:.2f}（0 最易，1 最难）。

范围：
{context}

严格输出如下 JSON 结构（数组，元素个数 = {req.count}）：
[
  {{
    "stem": "题干",
    "options": [{{"key": "A", "text": "选项内容"}}, ...],   // 判断题/填空/简答可为 null
    "answer": "正确答案",
    "explanation": "解析",
    "difficulty": 0.5
  }}
]

要求：
- {ANSWER_FORMAT[req.qtype]}
- 单选题必须恰好 4 个选项，干扰项要有迷惑性但不产生歧义。
- 解析要简洁点明依据。
- 多道题之间不得雷同。"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
