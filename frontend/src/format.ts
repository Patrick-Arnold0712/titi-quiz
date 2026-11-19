// 展示层通用格式化。放在这里是为了跨学科复用 ——
// 以后接第二、第三门课时，不用再各自抄一遍同样的判断。
//
// 核心约定：**数据不足时显示「—」，不要显示 0**。
// 用户的刷题记录如果只来自错题夹（只有错题、没有答对），
// 那么正确率的分子天生就是 0 —— 显示 0% 会被读成「水平为 0」，属于误导。
// 覆盖率不受影响，仍然照常显示。

export const pct = (x: number) => `${Math.round(x * 100)}%`

/** 正确率/掌握度是否「算得出来」。算不出来就返回 false，界面上显示「—」。 */
export function accKnown(kpi?: { has_correct_records?: boolean; attempts?: number } | null): boolean {
  if (!kpi) return false
  if (kpi.has_correct_records === false && (kpi.attempts ?? 0) > 0) return false
  return true
}

/** 有数据就显示百分比，没有就显示「—」 */
export function pctOr(x: number, known: boolean) {
  return known ? pct(x) : '—'
}

/**
 * 展示用的标准答案文本。
 * 判断题在接口层被归一成 A/B（A=正确、B=错误），直接显示字母用户看不懂，
 * 所以这里翻译回中文。其它题型原样返回。
 */
export function answerLabel(q?: { qtype?: string; display_qtype?: string | null; answer?: string } | null): string {
  const a = (q?.answer ?? "").trim()
  if (!a) return "—"
  // 卷面上按 display_qtype 呈现：判断题编进单选大题后就是 A/B，不该翻成「正确/错误」
  const qt = q?.display_qtype ?? q?.qtype
  if (qt === "true_false") {
    if (a === "A") return "正确"
    if (a === "B") return "错误"
  }
  return a
}
