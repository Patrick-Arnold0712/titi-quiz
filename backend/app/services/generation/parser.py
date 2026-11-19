from __future__ import annotations

import json
import re


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def parse_generated_questions(raw: str) -> list[dict]:
    """把模型返回的文本解析成题目 dict 列表。容错：去代码围栏、兼容 {questions:[...]}。"""

    if not raw:
        return []
    text = _strip_code_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("questions", [])
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]
