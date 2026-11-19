// 后端 API 客户端。统一在这里管，视图里不直接写 fetch。
const BASE = '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText} ${text.slice(0, 200)}`)
  }
  return res.json() as Promise<T>
}

const qs = (o: Record<string, any>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export interface MaterialReport {
  candidate_count: number; usable_count: number; invalid_count: number
  issues: { number: number; page: number; issues: string[] }[]
  sample: { stem: string; answer: string; options: { key: string; text: string }[] }[]
}
export interface MaterialDraft extends MaterialReport {
  draft_id: string; filename: string; pages: string[]; ocr_pages: number[]
}
interface MaterialReview { pages: string[]; chapter: string; make_paper: boolean }
interface MaterialResult {
  document_id: number; already_imported: boolean; chunk_count: number
  question_count: number; duplicates: number; skipped: number; paper_id: number | null
}

// ---------- 类型 ----------
export interface SearchHit {
  id: number; score: number; snippet: string; matched: string[]
  // 考点命中时说明它是「考点名」直接命中，还是「教材段落 / 题目」带出来的
  via?: string
  name?: string; chapter?: string; section?: string
  page_start?: number; page_end?: number
  page_no?: number | null; file_page?: boolean; kp_id?: number; kp_name?: string
  qtype?: string; stem?: string; answer?: string; explanation?: string
  bit_kind?: string; key?: string; detail?: string; hits?: number
  // 教材段落：full 是剥了页眉的完整正文（snippet 只是检索窗口）
  full?: string
  options?: { key: string; text: string }[] | null
  quality?: 'ok' | 'suspect' | 'defective'
}
export interface SearchResult {
  q: string; terms: string[]
  kps: SearchHit[]; excerpts: SearchHit[]; questions: SearchHit[]; bits: SearchHit[]
  total: Record<string, number>
}
export interface KnowledgeBit {
  id: number; kind: 'link' | 'year' | 'law' | 'work'
  key: string; detail: string; page_no?: number | null
  kp_id?: number | null; kp_name?: string | null; hits: number
}
export interface KpDetail {
  id: number; name: string; importance: number
  page_start?: number | null; page_end?: number | null
  section?: string | null; chapter?: string | null
  total_questions: number; wrong_count: number
  // 摘录含「当前考点 + 同节相邻考点」，每条标出归属
  excerpts: { page_no: number | null; file_page?: boolean; text: string; kp_id?: number; kp_name?: string; is_current?: boolean }[]
  siblings?: { id: number; name: string; page_start?: number; page_end?: number
               is_current: boolean; included: boolean }[]
}
export interface NetInfo {
  port: number; current_host: string
  // 后端只绑 127.0.0.1 时 lan_enabled=false、urls 为空 —— 手机访问不到
  lan_enabled: boolean
  urls: string[]
  hint_bound_local_only: string
  hint_firewall: string
  hint_isolation: string
}
export interface Subject { id: number; name: string; code: string; exam_name?: string; description?: string }
export interface KP { id: number; name: string; chapter_id?: number; importance: number; frequency: number; page_start?: number; page_end?: number }
export interface Chapter { id: number; name: string; order_index: number; summary?: string; page_start?: number; knowledge_points?: KP[] }

export interface QuestionOption { key: string; text: string }
// 题面体检结论：ok 正常 / suspect 可疑但能做 / defective 残缺，不能作答
export type QuestionQuality = 'ok' | 'suspect' | 'defective'
export interface Question {
  id: number; chapter_id?: number; kp_id?: number; qtype: string; stem: string
  quality?: QuestionQuality
  options?: QuestionOption[] | null; answer: string; explanation?: string | null
  difficulty: number; score: number; source_type: string; year?: string | null; tags?: string | null
}

export interface PaperBlueprint {
  section: string; qtype: string; count: number; score_per: number; total?: number
  // 每个大题的题源配额（题数）：{real_exam: 9, refsite_chapter: 7, predict: 4}
  mix?: Record<string, number>
}
export interface Paper {
  id: number; subject_id?: number; name: string; year?: string | null; volume?: string | null
  source_type: string; duration_min: number; total_score: number; blueprint?: PaperBlueprint[] | null; note?: string | null
  // 题源构成：押题卷只从真题 / 章节题 / 自出题取
  source_mix?: Record<string, number> | null
  // 做过没有。done_count 是「交过几次卷」——界面上「已完成」以它为准，
  // attempt_count 含做了一半丢在那儿的。
  attempt_count?: number; done_count?: number
  last_attempt_id?: number | null; last_status?: string | null
  last_score?: number | null; last_submitted_at?: string | null
}
export interface PaperItem {
  order_index: number; section_name?: string; score_per: number
  // 卷面上按什么题型呈现。判断题在单选大题里就是单选，别按 qtype 显示成「判断」
  display_qtype?: string | null
  question: Question
}
export interface PaperDetail extends Paper { items: PaperItem[] }

export interface PaperAttempt {
  id: number; paper_id: number; status: string
  score: number; objective_total: number; subjective_total: number; detail?: any
}
export interface ReviewRow {
  order_index: number; section_name?: string; score_per: number; qtype?: string
  display_qtype?: string | null
  stem: string; options?: QuestionOption[] | null; answer: string; explanation?: string | null
  user_answer: string; is_correct: boolean | null; awarded_score: number; pending_manual: boolean
  quality?: QuestionQuality
}

export interface AdviceROI {
  rank: number; kp_id: number; name: string; chapter: string; page?: number
  est_score: number; mastery: number; coverage: number; accuracy: number
  risk_score: number; roi_per_page: number; total_q: number; attempted: number
  weak_count: number; action: string; why: string
}
export interface AdviceKpi {
  kp_total: number; kp_attempted: number; coverage: number
  attempts: number; accuracy: number; mastery: number
  // correct_records=0 且 attempts>0 时，说明数据只来自错题夹 ——
  // 这时 accuracy / mastery 恒为 0，不是「水平为 0」，前端必须显示成「—」
  correct_records?: number
  has_correct_records?: boolean
}
export interface Advice {
  kpi: AdviceKpi
  data_note?: string
  lines: { pass: number; safe: number; mastery: number }
  stage: string; readiness: string
  roi_plan: AdviceROI[]
  chapter_risk: any[]
  must_know: any[]
  schedule: { days: number; daily_minutes: number; stage: string; budget_advice: string; timeline: any[]; rules: string[] }
}

// ---------- 接口 ----------
// ---------- 主观题易考清单 ----------
// 简答 / 论述的考前背诵清单，数据来自后端包内的 checklist.json
export type SubjTier = 'S' | 'A' | 'B'
export interface SubjItem {
  id: string
  tier: SubjTier
  chapter: string          // 清单里写的章（人工归类）
  root_chapter: string     // 知识体系里还原出的章（以库为准）
  section: string | null   // 知识体系里的「节」
  kp_id: number
  kp_name?: string | null
  importance?: number | null   // 考点权重（0~1）
  est_score: number            // 该考点在 100 分卷里的预估占分
  mastery?: number | null      // 掌握度（0~1），无作答记录时是 0
  priority: number             // 优先分 = 预估占分 × 题型系数（S 1.0 / A 0.6 / B 0.3）
  page_start?: number | null
  q_total: number          // 该考点能做的题数；0 说明没题可练
  stem: string
  page: string             // 教材页码
  asked: string[]          // 历年命中 / 教材课后题出处
  evidence: string         // 答案依据：教材原文核对 / 历年卷参考答案
  lead?: string            // 总起句（先背这一句）
  points: string[]         // 分点答案要点
  tip?: string
}
/** 权重盲区：高权重但清单没覆盖的考点 */
export interface SubjGap {
  kp_id: number; name: string; chapter: string
  est_score: number; mastery: number; total_q: number; page_start?: number | null
}
export interface SubjChecklist {
  meta: {
    title: string; updated: string
    exam_facts: string[]
    legend: Record<string, string>
    sources: string[]
    warn: string
  }
  chapters: string[]
  items: SubjItem[]
  essay: {
    title: string; intro: string
    history: { year: string; stem: string }[]
    model: { step: string; body: string }[]
    bank: { theme: string; hits: string; skeleton: string }[]
    time: string
  }
  gaps: SubjGap[]
  // 库里有作答记录吗。没有时掌握度算不出来，页面显示「—」而不是 0%
  has_records: boolean
  weights: { total_score: number; tier_factor: Record<string, number>; note: string }
}

export const api = {
  health: () => req<any>('/health'),
  // 局域网访问信息：给「手机扫码打开」用
  netInfo: () => req<NetInfo>('/net/info'),
  subjects: () => req<Subject[]>('/subjects'),
  createSubject: (name: string) => req<Subject>('/subjects', {
    method: 'POST', body: JSON.stringify({ name, code: `user_${Date.now()}_${Math.random().toString(36).slice(2, 8)}` }),
  }),
  previewMaterial: (file: File, subject: number, kind: string, force: boolean) => {
    const data = new FormData()
    data.set('file', file)
    data.set('subject_id', String(subject))
    data.set('kind', kind)
    data.set('force_ocr', String(force))
    return req<MaterialDraft>('/material-import/preview', { method: 'POST', headers: {}, body: data })
  },
  checkMaterial: (id: string, data: MaterialReview) =>
    req<MaterialReport>(`/material-import/${id}/check`, { method: 'POST', body: JSON.stringify(data) }),
  commitMaterial: (id: string, data: MaterialReview) =>
    req<MaterialResult>(`/material-import/${id}/commit`, { method: 'POST', body: JSON.stringify(data) }),
  subjectDetail: (id: number) => req<any>(`/subjects/${id}`),

  questions: (p: Record<string, any> = {}) => req<Question[]>(`/questions${qs(p)}`),
  // 记录单题作答 —— 刷题时的作答也要进统计，否则掌握度算不准
  answerQuestion: (questionId: number, userAnswer: string) =>
    req<any>(`/questions/${questionId}/attempt`, {
      method: 'POST',
      body: JSON.stringify({ question_id: questionId, user_answer: userAnswer }),
    }),

  documents: (p: Record<string, any> = {}) => req<any[]>(`/documents${qs(p)}`),

  // 考前速查：教材知识链接 / 年份 / 法律 / 著作
  bits: (p: Record<string, any> = {}) => req<KnowledgeBit[]>(`/bits${qs(p)}`),
  bitsStats: (subjectId = 1) => req<Record<string, number>>(`/bits/stats${qs({ subject_id: subjectId })}`),
  // 站内搜索：BM25 相关度排序，一次搜出考点 / 教材原文 / 题目 / 速查
  search: (q: string, perKind = 6, subjectId = 1) =>
    req<SearchResult>(`/search${qs({ q, per_kind: perKind, subject_id: subjectId })}`),
  // 考点详情（含教材原文），错题订正用
  kpDetail: (kpId: number) => req<KpDetail>(`/kp/${kpId}`),
  // 主观题易考清单（简答 / 论述）
  subjectiveChecklist: () => req<SubjChecklist>('/subjective/checklist'),
  analysis: (subjectId: number) => req<any>(`/analysis/${subjectId}`),

  adviceAnalysis: (subjectId: number, totalScore = 100) =>
    req<any>(`/advice/${subjectId}/analysis${qs({ total_score: totalScore })}`),
  advice: (subjectId: number, days = 7, dailyMinutes = 90, totalScore = 100) =>
    req<Advice>(`/advice/${subjectId}${qs({ days, daily_minutes: dailyMinutes, total_score: totalScore })}`),

  papers: (subjectId?: number) => req<Paper[]>(`/papers${qs({ subject_id: subjectId })}`),
  paper: (id: number, withAnswer = false) => req<PaperDetail>(`/papers/${id}${qs({ with_answer: withAnswer })}`),
  blueprint: () => req<PaperBlueprint[]>('/papers/blueprint/default'),
  // 组卷参数：mix 覆盖各题源配额；auto_cloze = 本次现造几道教材挖空自出题
  generatePaper: (body: {
    subject_id: number; name: string; duration_min?: number; seed?: number
    mix?: Record<string, Record<string, number>>
    auto_cloze?: number; min_kp_importance?: number
  }) => req<Paper>('/papers/generate', { method: 'POST', body: JSON.stringify(body) }),

  startAttempt: (paperId: number) => req<PaperAttempt>(`/papers/${paperId}/attempts`, { method: 'POST' }),
  submitAttempt: (attemptId: number, answers: { question_id: number; user_answer: string }[], durationMs = 0) =>
    req<PaperAttempt>(`/papers/attempts/${attemptId}/submit`, {
      method: 'POST',
      body: JSON.stringify({ answers, duration_ms: durationMs }),
    }),
  importJlq: (payload: string, subjectId = 1, apply = false, replace = false) =>
    req<any>('/import/jlq', {
      method: 'POST',
      body: JSON.stringify({ subject_id: subjectId, payload, apply, replace }),
    }),

  review: (attemptId: number) => req<{ attempt_id: number; paper_id: number; score: number; detail: any; rows: ReviewRow[] }>(
    `/papers/attempts/${attemptId}/review`),
}
