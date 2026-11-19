# -*- coding: utf-8 -*-
"""全库「取值约定」审计：同一个概念在库里有没有两种写法。

## 为什么需要

真出过一次事故：`Paper.blueprint` 里的 `qtype` 有两套写法 ——
押题卷写枚举值 `multi_choice`，真题卷写短名 `multi`。
前端拿 `=== "multi_choice"` 比，短名判不中，
**真题卷的「不定项选择题」静默变成了单选**。
而且只有部分卷子症状明显（其余因为大题名对不上、回退到题目自身的 qtype 反而蒙对），
所以光看代码看不出来，只能拿数据来对。

这类问题的共同特征：**值是字符串，不是数据库枚举，所以没人拦**。
SQLAlchemy 的 Enum 列有约束，JSON 列和自由文本列没有。

## 它检查什么

1. **每一列的真实取值分布** —— 低基数列全列出来，比肉眼看 schema 靠谱
2. **JSON 列里的枚举字段** —— `blueprint[].qtype` 这种，列级检查发现不了
3. **与代码声明集合的差异** —— 库里出现了代码里不认的值（或反过来）
4. **同概念多写法** —— 把值规范化后分组，一组里超过一种写法的就报出来

## 用法

    .venv\Scripts\python.exe tools/audit_db_conventions.py

加新表、新 JSON 列、接新学科之后都该跑一遍。
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "db" / "ttk.db"
sys.path.insert(0, str(ROOT / "backend"))

from app.models.entities import (  # noqa: E402
    DocStatus,
    QuestionType,
    SourceType,
    canon_qtype,
)

# ---- 代码里声明的取值集合（改了枚举就来这里同步；工具会报差异） ----
EXPECTED: dict[tuple[str, str], tuple[set[str], str]] = {
    ("questions", "qtype"): ({q.value for q in QuestionType}, "models.entities.QuestionType"),
    ("questions", "source_type"): ({s.value for s in SourceType}, "models.entities.SourceType"),
    ("papers", "source_type"): ({s.value for s in SourceType}, "models.entities.SourceType"),
    ("documents", "source_type"): ({s.value for s in SourceType}, "models.entities.SourceType"),
    ("documents", "status"): ({d.value for d in DocStatus}, "models.entities.DocStatus"),
    ("documents", "doc_type"): ({"pdf", "docx", "doc", "txt", "md", "img", "web"}, "ingest/parsers.py"),
    ("knowledge_bits", "kind"): ({"link", "year", "law", "work"}, "build_knowledge_bits.py"),
    ("attempts", "source"): ({"manual", "import_jlq", "reconstructed"}, "api/questions.py 注释"),
    ("paper_attempts", "status"): ({"doing", "submitted"}, "services/paper/scoring.py"),
}

# JSON 列里的枚举字段：(表, 列, 路径, 期望集合, 说明)。期望为 None 表示只看分布。
EXPECTED_JSON: list[tuple[str, str, str, set[str] | None, str]] = [
    ("papers", "blueprint", "qtype", {q.value for q in QuestionType},
     "generator.py 写枚举值；早先 build_papers.py 写的是短名 single/multi/short"),
]

# 有意保留多写法的「展示串」列。
# 它们的差异**不是隐患** —— 各套真题卷就该保留原卷的措辞（含分值说明）。
# 前提是：代码绝不能拿它们当查表的 key（改用结构化 id，例如 PaperItem.section_index）。
DISPLAY_ONLY: dict[tuple[str, str], str] = {
    ("paper_items", "section_name"): "各套真题卷保留原卷大题写法；查蓝图请用 section_index",
}

# 「同一概念的多种写法」：规范化后能归到一组的，都算可疑
NORM_RULES = [
    (re.compile(r"^single$"), "single_choice"),
    (re.compile(r"^multi$"), "multi_choice"),
    (re.compile(r"^short$"), "short_answer"),
    (re.compile(r"^(tf|judge)$"), "true_false"),
    (re.compile(r"^fill$"), "fill_blank"),
    (re.compile(r"^(img|image)$"), "img"),
    # 判断题的作答：库里同时存在 A/B 和 正确/错误 两套写法。
    # 判分能兼容（normalize_bool 两者都认），但同一概念两种写法本身就是隐患。
    # 只收「确定是判断题答案」的写法。**不要把 1/0 也算进来** ——
    # 主观题答案以「1.」开头很常见，会被误归到「判断」组。
    (re.compile(r"^(正确|对|√|✓|T|TRUE|是|A)$"), "<判断:正确>"),
    (re.compile(r"^(错误|错|×|╳|X|F|FALSE|否|B)$"), "<判断:错误>"),
]

# 大类名（大题标题）的规范化：去掉编号、括号补注、LaTeX 分值、空白。
# 真题卷每套的写法都不一样：
#   「一、单项选择题」/「一、单项选择题(共20题,每题2分)」/「单项选择题 $20 \times 2$ 分」
# 而代码是拿这个串去查蓝图的 —— 写法一变，查表就落空。
RE_SEC_NOISE = re.compile(r"[（(][^)）]*[)）]|\$[^$]*\$|\s+")


def canon_section(s: str) -> str:
    t = RE_SEC_NOISE.sub("", s or "")
    t = re.sub(r"^[一二三四五六七八九十]+[、.．]", "", t)
    t = re.sub(r"^第[一二三四五六七八九十]+", "", t)
    # 「不定项选择」与「不定项选择题」是同一个大题
    t = re.sub(r"题$", "", t)
    t = t.replace("单项选择", "单选")
    return t.strip()


def norm(v: str) -> str:
    for pat, rep in NORM_RULES:
        if pat.match(v):
            return rep
    return v


def col_values(con: sqlite3.Connection, table: str, col: str) -> collections.Counter:
    try:
        rows = con.execute(
            'select "{}" , count(*) from "{}" group by "{}" order by 2 desc'.format(col, table, col)
        ).fetchall()
    except sqlite3.OperationalError:
        return collections.Counter()
    return collections.Counter({("(NULL)" if r[0] is None else str(r[0])): r[1] for r in rows})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=40, help="低基数列最多列几个值")
    args = ap.parse_args()

    if not DB.exists():
        raise SystemExit("找不到数据库：{}".format(DB))
    con = sqlite3.connect(DB)
    problems: list[str] = []
    notes: list[str] = []

    tables = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]

    bar = "=" * 78
    print(bar)
    print("一、各列真实取值分布（低基数列全列）")
    print(bar)
    for t in tables:
        cols = [r[1] for r in con.execute('pragma table_info("{}")'.format(t))]
        out = [(c, col_values(con, t, c)) for c in cols]
        out = [(c, v) for c, v in out if v]
        if not out:
            continue
        total = con.execute('select count(*) from "{}"'.format(t)).fetchone()[0]
        print("\n[{}] {} 行".format(t, total))
        for c, vals in out:
            if len(vals) > args.max:
                print("   {:22s} {} 种取值（高基数，略）".format(c, len(vals)))
                continue
            head = "  ".join("{}x{}".format(k, v) for k, v in list(vals.items())[:8])
            more = " …共{}种".format(len(vals)) if len(vals) > 8 else ""
            print("   {:22s} {}{}".format(c, head, more))
            # 大题名（section_name）单独用 canon_section 归一：
            # 它是有意保留原卷写法的展示串，但代码不该拿它当 key。
            keyfn = canon_section if c == "section_name" else norm
            groups: dict[str, list[str]] = collections.defaultdict(list)
            for k in vals:
                groups[keyfn(k)].append(k)
            for g, members in groups.items():
                if len(set(members)) <= 1:
                    continue
                msg = "[{}.{}] 同一概念有多种写法：{}".format(t, c, sorted(set(members)))
                if (t, c) in DISPLAY_ONLY:
                    note = "{}（有意为之：{}）".format(msg, DISPLAY_ONLY[(t, c)])
                    if note not in notes:
                        notes.append(note)
                elif msg not in problems:
                    problems.append(msg)

    print("\n" + bar)
    print("二、JSON 列里的枚举字段")
    print(bar)
    for t, c, path, expected, why in EXPECTED_JSON:
        vals: collections.Counter = collections.Counter()
        for (raw,) in con.execute('select "{}" from "{}" where "{}" is not null'.format(c, t, c)):
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(data, list):
                continue
            for item in data:
                if isinstance(item, dict) and item.get(path) is not None:
                    vals[str(item[path])] += 1
        print("\n[{}.{}] 字段 {}：{}".format(t, c, path, dict(vals)))
        print("   说明：{}".format(why))
        if expected is not None and vals:
            unknown = {v for v in vals if canon_qtype(v) not in expected}
            if unknown:
                problems.append("[{}.{}.{}] 代码不认识的值：{}".format(t, c, path, sorted(unknown)))
                print("   [!] 代码不认识：{}".format(sorted(unknown)))
            noncanon = {v for v in vals} - expected
            if noncanon:
                problems.append("[{}.{}.{}] 写法不统一：{}".format(t, c, path, sorted(noncanon)))
                print("   [!] 写法不统一：{}".format(sorted(noncanon)))

    print("\n" + bar)
    print("三、与代码声明集合的差异")
    print(bar)
    for (t, c), (expected, src) in EXPECTED.items():
        vals = col_values(con, t, c)
        got = {k for k in vals if k != "(NULL)"}
        unknown = got - expected
        unused = expected - got
        print("\n[{}.{}]  声明来源：{}".format(t, c, src))
        print("   声明：{}".format(sorted(expected)))
        print("   实际：{}".format(sorted(got)))
        if unknown:
            problems.append("[{}.{}] 库里多出代码未声明的值：{}".format(t, c, sorted(unknown)))
            print("   不一致 [x]  库里多出：{}".format(sorted(unknown)))
        else:
            print("   一致 [OK]")
        if unused:
            notes.append("[{}.{}] 声明了但库里暂无：{}".format(t, c, sorted(unused)))

    print("\n" + bar)
    print("四、结论")
    print(bar)
    if problems:
        print("发现 {} 处可疑：".format(len(problems)))
        for x in problems:
            print("  [!]", x)
    else:
        print("没有发现「同一概念多种写法」或「代码不认识的值」。")
        print("（提示：section_name 这类展示串的多种写法如果被报出来，")
        print("  要看代码是不是拿它当了查表的 key —— 请改用 section_index。）")
    if notes:
        print("\n另有 {} 条提示（不算问题）：".format(len(notes)))
        for x in notes:
            print("  ·", x)
    con.close()
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
