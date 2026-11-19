"""备考建议：把掌握度分析变成「先学什么、为什么、怎么验收」。

设计原则（借用 finals-week skill 的输出风格）：
- **先说什么、为什么、怎么验收**，不要励志长文
- 每条建议都要能被立即执行（小到马上能开始）
- 事实与建议分开：数据是算出来的，话是照着数据说的

ROI 排序依据：
    risk_score = 预估占分 × (1 - 掌握度)
即「这条考点这可能让你丢多少分」。丢分多、成本低的排前面。
"""

from __future__ import annotations

from collections import defaultdict


def _action_for(s: dict, margin: int = 3, has_correct: bool = True) -> str:
    """给一条考点生成「最快的复习动作」。

    has_correct=False 表示目前只有错题记录（一条答对记录都没有）。
    这种情况下不能说「正确率低」，只能说「这几道题你错过」——
    否则会凭空造出一个不存在的正确率，误导复习判断。
    """
    lo, hi = s["page_start"], (s["page_start"] or 0) + (s["pages"] or 1) - 1
    where = f"教材 p{lo}-{hi}" if lo else "教材对应章节"

    if s["total_q"] == 0:
        return f"该考点题库里还没有题 —— 直接读 {where} 原文，自己做笔记"
    if s["attempted"] == 0:
        return f"先读 {where}，再做 {min(s['total_q'], 15)} 道该考点的题（目前一道没做过）"
    if not has_correct:
        return (
            f"错题命中 {len(s['weak_questions'])} 道 —— 先把这几道重做一遍，"
            "并在系统里提交答案（提交后才会产生答对记录，掌握度才算得出来）"
        )
    if s["coverage"] < 0.4:
        return f"补齐覆盖：还有 {s['total_q'] - s['attempted']} 道没做，今天做 {min(15, s['total_q'] - s['attempted'])} 道"
    if s["accuracy"] < 0.7:
        n = len(s["weak_questions"])
        return f"回炉错题 {min(n, 10)} 道 + 同考点 {margin} 道新题；错了就写一句误解笔记"
    if s["last_ok"] is False:
        return "最近一次还错着 —— 先重做这道，再补 3 道同类题"
    if s["coverage"] < 0.8:
        return f"覆盖还不够（{s['coverage']:.0%}），再刷 {min(10, s['total_q'] - s['attempted'])} 道"
    return "维持：混在综合练习里保持手感即可，不必再单独投入"


def build_roi_plan(analysis: dict, top_n: int = 15) -> list[dict]:
    """按「失分风险」排序的冲刺清单。"""
    stats = analysis["knowledge_points"]
    has_correct = bool(analysis["kpi"].get("has_correct_records"))
    # 已掌握的（mastery>=0.9）不占冲刺位
    pool = [s for s in stats if s["mastery"] < 0.90]
    pool.sort(key=lambda s: (-s["risk_score"], s["pages"]))

    out = []
    for i, s in enumerate(pool[:top_n], 1):
        if has_correct:
            why = (
                f"本卷预估占 {s['est_score']:.1f} 分，"
                f"掌握度 {s['mastery']:.0%}（正确率 {s['accuracy']:.0%}，覆盖 {s['coverage']:.0%}）"
            )
        else:
            # 没有答对记录时，掌握度/正确率都是 0，写出来就是假数字
            why = (
                f"本卷预估占 {s['est_score']:.1f} 分，覆盖 {s['coverage']:.0%}；"
                f"错题命中 {len(s['weak_questions'])} 道（暂无答对记录，掌握度未知）"
            )
        out.append({
            "rank": i,
            "kp_id": s["kp_id"],
            "name": s["name"],
            "chapter": s["chapter_name"],
            "page": s["page_start"],
            "est_score": s["est_score"],
            "mastery": s["mastery"],
            "coverage": s["coverage"],
            "accuracy": s["accuracy"],
            "risk_score": s["risk_score"],
            "roi_per_page": s["roi_per_page"],
            "total_q": s["total_q"],
            "attempted": s["attempted"],
            "weak_count": len(s["weak_questions"]),
            "action": _action_for(s, has_correct=has_correct),
            "why": why,
        })
    return out


def build_chapter_risk(analysis: dict) -> list[dict]:
    """按章的失分风险汇总，用于雷达/分布图。"""
    agg: dict[str, dict] = defaultdict(
        lambda: {"chapter": "", "kp": 0, "est_score": 0.0, "risk_score": 0.0,
                 "attempts": 0, "correct": 0, "attempted_kp": 0}
    )
    for s in analysis["knowledge_points"]:
        a = agg[s["chapter_name"]]
        a["chapter"] = s["chapter_name"]
        a["kp"] += 1
        a["est_score"] += s["est_score"]
        a["risk_score"] += s["risk_score"]
        a["attempts"] += s["attempts"]
        a["correct"] += s["correct"]
        if s["attempted"] > 0:
            a["attempted_kp"] += 1
    rows = []
    for a in agg.values():
        rows.append({
            **{k: v for k, v in a.items() if k != "correct"},
            "est_score": round(a["est_score"], 2),
            "risk_score": round(a["risk_score"], 2),
            "accuracy": round(a["correct"] / a["attempts"], 4) if a["attempts"] else 0.0,
            "coverage": round(a["attempted_kp"] / a["kp"], 4) if a["kp"] else 0.0,
        })
    rows.sort(key=lambda r: -r["risk_score"])
    return rows


def build_schedule(analysis: dict, days: int = 7, daily_minutes: int = 90) -> dict:
    """按剩余天数排计划。天数决定阶段重心。"""
    plan = build_roi_plan(analysis, top_n=40)
    stage = analysis["stage"]

    if days <= 1:
        buckets = [("今天 前 2 小时", 6), ("今天 后 2 小时", 8)]
    elif days <= 3:
        buckets = [("第 1 天", 10), ("第 2 天", 12), ("第 3 天", 14)]
    elif days <= 7:
        buckets = [("第 1-2 天", 12), ("第 3-4 天", 12), ("第 5-6 天", 10), ("第 7 天", 6)]
    else:
        buckets = [("第 1-3 天", 12), ("第 4-7 天", 14), ("第 8-10 天", 10), ("最后阶段", 8)]

    cursor = 0
    timeline = []
    for label, quota in buckets:
        chunk = plan[cursor:cursor + quota]
        cursor += quota
        if not chunk:
            continue
        timeline.append({
            "phase": label,
            "focus": [{"name": c["name"], "chapter": c["chapter"],
                       "risk_score": c["risk_score"], "action": c["action"]} for c in chunk],
            "note": _phase_note(stage, label),
        })

    # 每天的时间预算建议
    if daily_minutes < 30:
        budget = "每天 30 分钟以内：只做错题回炉 + 单个考点的小练，别开新章节"
    elif daily_minutes <= 90:
        budget = "每天 30~90 分钟：一个考点专项（读教材 + 做题）+ 错题回炉"
    else:
        budget = "每天 90 分钟以上：考点专项 + 错题回炉 + 一段薄弱章节精读"

    return {
        "days": days,
        "daily_minutes": daily_minutes,
        "stage": stage,
        "budget_advice": budget,
        "timeline": timeline,
        "rules": [
            "每组题 30~50 道，做完立刻看解析，别攒着",
            "某组正确率低于 70% —— 停下来先修错题，不要继续做新题",
            "最近还错的题，优先级高于早先错过但已改对的题",
            "反复错的题通常意味着概念错误，不是记性问题 —— 回去读那一节教材",
            "考前最后几天不再扩张新内容，只收窄到高风险考点和必背清单",
        ],
    }


def _phase_note(stage: str, label: str) -> str:
    if "未开始" in stage:
        return "先做一套限时卷摸底，拿到基线再谈侧重"
    if "建覆盖" in stage or "稳正确率" in stage and label.startswith("第 1"):
        return "这一阶段以「补齐覆盖」为主：每个考点先过教材，再把该考点的题刷一遍"
    if "模考" in stage:
        return "每 2~3 天做一套限时卷；每套的错题都要进错题本，不要只看分数"
    if "收窄" in stage:
        return "只复盘错题与必背清单，保持手感即可，不要开新内容"
    return "混合练习 + 错题回炉，兼顾新题与旧错"


def build_must_know(analysis: dict, top_n: int = 20) -> list[dict]:
    """必背清单：按预估占分排序（不论掌握度）。"""
    stats = sorted(analysis["knowledge_points"], key=lambda s: -s["est_score"])
    return [
        {"name": s["name"], "chapter": s["chapter_name"], "page": s["page_start"],
         "est_score": s["est_score"], "mastery": s["mastery"], "importance": s["importance"]}
        for s in stats[:top_n]
    ]


def build_advice(db, subject_id: int, total_score: float = 100.0,
                 days: int = 7, daily_minutes: int = 90) -> dict:
    from app.services.advice.analyzer import analyze_subject

    analysis = analyze_subject(db, subject_id, total_score)
    return {
        "kpi": analysis["kpi"],
        "data_note": analysis.get("data_note", ""),
        "lines": analysis["lines"],
        "stage": analysis["stage"],
        "readiness": analysis["readiness"],
        "roi_plan": build_roi_plan(analysis),
        "chapter_risk": build_chapter_risk(analysis),
        "must_know": build_must_know(analysis),
        "schedule": build_schedule(analysis, days, daily_minutes),
    }
