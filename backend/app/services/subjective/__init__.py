"""主观题（简答 / 论述）易考清单。面向考前冲刺的背诵清单。

## 为什么数据放在后端包里

`data/` 目录不进分享包（见 tools/make_share_package.py），后端一旦依赖它，
拿到试用包的人一点这个页面就 500。所以清单内容放在
`backend/app/services/subjective/checklist.json`，与 `confusable_terms.json` 同一套做法。

## 内容是怎么来的

1. 教材《军事理论》（中大出版社）正文逐页比对 —— 页码是教材原书页码；
2. 2021—2025 历年真题（含回忆版、参考站整理卷）里的简答 / 论述题；
3. 教材各章末「思考题」（26 道）—— 这是全卷信度最高的题源。

每条都带 `evidence` 字段，标明答案是「教材原文核对」还是「历年卷参考答案」，
不写没核过的答案。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).with_name("checklist.json")


@lru_cache(maxsize=1)
def load() -> dict:
    """读一遍缓存住。utf-8-sig 兼容带 BOM 的写法。"""
    return json.loads(DATA.read_text(encoding="utf-8-sig"))
