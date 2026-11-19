<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type Question, type KpDetail } from '@/api'
import { answerLabel } from '@/format'
import RichText from '@/components/RichText.vue'

const props = defineProps<{ subjectId: number }>()

const wrongs = ref<Question[]>([])
const analysis = ref<any>(null)
const err = ref('')
const order = ref<'risk' | 'count'>('risk')

// ---- 教材原文：按需展开，不预加载 ----
const kpCache = ref<Record<number, KpDetail>>({})
const openKp = ref<number | null>(null)

async function toggleKp(kpId: number) {
  if (openKp.value === kpId) { openKp.value = null; return }
  openKp.value = kpId
  if (!kpCache.value[kpId]) {
    try { kpCache.value[kpId] = await api.kpDetail(kpId) } catch { /* 拿不到就空着 */ }
  }
}

// ---- 重做模式 ----
// 关键点：不做额外开关。题做对了，后端记一条 correct 作答，
// 「最近一次仍错」的口径自然就把它移出错题本了 —— 后端一行都不用改。
const retry = ref(false)
const queue = ref<Question[]>([])
const idx = ref(0)
const picked = ref('')
const judged = ref<{ ok: boolean } | null>(null)
const busy = ref(false)
const fixedCount = ref(0)

const cur = computed(() => queue.value[idx.value])
const isMulti = computed(() => cur.value?.qtype === 'multi_choice')

function startRetry(shuffle = true) {
  queue.value = [...wrongs.value]
  if (shuffle) queue.value.sort(() => Math.random() - 0.5)
  idx.value = 0; picked.value = ''; judged.value = null; fixedCount.value = 0
  retry.value = true
}
function pick(k: string) {
  if (judged.value || !cur.value) return
  if (isMulti.value) {
    const s = new Set(picked.value.split(''))
    s.has(k) ? s.delete(k) : s.add(k)
    picked.value = [...s].sort().join('')
  } else picked.value = k
}
const chosen = (k: string) => picked.value.includes(k)

async function submit() {
  if (!cur.value || !picked.value || busy.value) return
  busy.value = true
  try {
    const a: any = await api.answerQuestion(cur.value.id, picked.value)
    judged.value = { ok: !!a.is_correct }
    if (a.is_correct) fixedCount.value++
  } catch (e: any) { err.value = String(e.message ?? e) }
  finally { busy.value = false }
}
function next() {
  if (idx.value < queue.value.length - 1) {
    idx.value++; picked.value = ''; judged.value = null
  } else { finish() }
}
async function finish() {
  retry.value = false
  await load()
}
function exitRetry() { retry.value = false }

// ---- 列表 ----
onMounted(load)
async function load() {
  try {
    wrongs.value = await api.questions({ subject_id: props.subjectId, wrong_only: true, limit: 1000 })
    analysis.value = await api.adviceAnalysis(props.subjectId)
  } catch (e: any) { err.value = String(e.message ?? e) }
}

const grouped = () => {
  const risk: Record<number, number> = {}
  for (const s of analysis.value?.knowledge_points ?? []) risk[s.kp_id] = s.risk_score
  const by: Record<number, Question[]> = {}
  for (const q of wrongs.value) { const k = q.kp_id ?? 0; (by[k] ||= []).push(q) }
  const rows = Object.entries(by).map(([k, list]) => ({ kp: Number(k), list, risk: risk[Number(k)] ?? 0 }))
  rows.sort((a, b) => order.value === 'risk' ? b.risk - a.risk : b.list.length - a.list.length)
  return rows
}
const kpName = (kp: number) =>
  analysis.value?.knowledge_points?.find((s: any) => s.kp_id === kp)?.name ?? '未归考点'
const typeLabel = (t: string) =>
  ({ single_choice: '单选', multi_choice: '多选', true_false: '判断', short_answer: '简答', essay: '论述' } as any)[t] ?? t
</script>

<template>
  <h1>错题本</h1>
  <p class="muted" v-if="err">接口未就绪：{{ err }}</p>

  <!-- ================= 重做模式 ================= -->
  <template v-if="retry && cur">
    <div class="toolbar">
      <span class="tag">重做 {{ idx + 1 }} / {{ queue.length }}</span>
      <span class="tag ok" v-if="fixedCount">已订正 {{ fixedCount }}</span>
      <span style="flex:1"></span>
      <button class="btn ghost mini" @click="exitRetry">退出重做</button>
    </div>
    <div class="bar" style="margin-bottom:12px">
      <i :style="{ width: ((idx + 1) / queue.length * 100) + '%' }"></i>
    </div>

    <div class="card">
      <div class="statline">
        <span class="pill">{{ kpName(cur.kp_id ?? 0) }}</span>
        <span class="pill">{{ typeLabel(cur.qtype) }}</span>
        <span class="pill" v-if="isMulti">多选（错选漏选不得分）</span>
      </div>

      <div class="q-stem">{{ cur.stem }}</div>

      <div v-for="o in cur.options ?? []" :key="o.key" class="opt"
           :class="{ on: chosen(o.key) && !judged,
                     right: judged && cur.answer.includes(o.key),
                     wrong: judged && chosen(o.key) && !cur.answer.includes(o.key) }"
           @click="pick(o.key)">
        <span class="k">{{ o.key }}</span><span>{{ o.text }}</span>
      </div>

      <div class="toolbar" style="margin:14px 0 0">
        <button class="btn" v-if="!judged" :disabled="!picked || busy" @click="submit">
          {{ busy ? '判分中…' : '提交' }}
        </button>
        <button class="btn" v-else @click="next">
          {{ idx < queue.length - 1 ? '下一题' : '完成' }}
        </button>
        <button class="btn ghost mini" @click="toggleKp(cur.kp_id ?? 0)"
                v-if="cur.kp_id">看教材 p{{ kpCache[cur.kp_id!]?.page_start ?? '' }}</button>
      </div>

      <div class="note" :class="judged?.ok ? 'ok' : 'bad'" style="margin-top:12px" v-if="judged">
        <b>{{ judged.ok ? '答对了 —— 已移出错题本' : '还是错的，留在错题本里' }}</b>
        <div style="margin-top:4px">你选 <b>{{ picked }}</b>　正确答案 <b>{{ answerLabel(cur) }}</b></div>
      </div>

      <div class="note ok" style="margin-top:10px" v-if="judged && cur.explanation">
        <b>解析：</b>
        <div style="margin-top:4px"><RichText :text="cur.explanation" /></div>
      </div>
    </div>

    <div class="card" v-if="cur.kp_id && openKp === cur.kp_id && kpCache[cur.kp_id]">
      <h3 style="margin-top:0">{{ kpCache[cur.kp_id].name }} · 教材原文</h3>
      <p class="muted" style="margin-top:0">
        本题考点是「{{ kpCache[cur.kp_id].name }}」。教材里相邻小节常与它交叉，
        所以把前后考点也一并列出 —— 带 <span class="tag">本题考点</span> 的才是主段。
      </p>
      <template v-for="(e, i) in kpCache[cur.kp_id].excerpts" :key="i">
        <div v-if="i === 0 || kpCache[cur.kp_id].excerpts[i - 1].kp_id !== e.kp_id"
             style="display:flex;align-items:center;gap:8px;margin:14px 0 8px;padding-top:10px;border-top:1px dashed var(--line)">
          <span class="tag" :class="{ grey: !e.is_current }">{{ e.is_current ? '本题考点' : '相邻考点' }}</span>
          <b style="font-size:14px;color:var(--ink)">{{ e.kp_name }}</b>
        </div>
        <div style="margin-bottom:12px">
          <span class="tag grey" v-if="e.page_no">{{ e.file_page ? '文件第 ' + e.page_no + ' 页' : 'p' + e.page_no }}</span>
          <div style="margin-top:6px"><RichText :text="e.text" /></div>
        </div>
      </template>
    </div>
  </template>

  <!-- ================= 列表模式 ================= -->
  <template v-else>
    <p class="muted">
      只收录「错过、且最近一次仍然答错」的题，按考点风险排序。点「重做」逐题订正 ——
      <b>答对就自动移出</b>，不用手动删。
    </p>

    <div class="toolbar">
      <span class="tag bad">共 {{ wrongs.length }} 道待回炉</span>
      <button class="btn mini" :disabled="!wrongs.length" @click="startRetry(true)">开始重做</button>
      <span style="flex:1"></span>
      <button class="chip" :class="{ on: order === 'risk' }" @click="order = 'risk'">按考点风险</button>
      <button class="chip" :class="{ on: order === 'count' }" @click="order = 'count'">按题量</button>
    </div>

    <div class="card" v-for="g in grouped()" :key="g.kp">
      <div class="statline">
        <span class="tag grey">{{ kpName(g.kp) }}</span>
        <span class="tag bad" v-if="g.risk">失分风险 {{ g.risk.toFixed(1) }} 分</span>
        <span style="flex:1"></span>
        <button class="chip" v-if="g.kp" @click="toggleKp(g.kp)">
          {{ openKp === g.kp ? '收起教材' : '看教材' }}</button>
        <span class="muted">{{ g.list.length }} 道</span>
      </div>

      <div v-if="g.kp && openKp === g.kp && kpCache[g.kp]" style="margin-bottom:10px">
        <div class="note" style="font-size:13px">
          {{ kpCache[g.kp].chapter }} / {{ kpCache[g.kp].section }} ·
          教材 p{{ kpCache[g.kp].page_start }}-{{ kpCache[g.kp].page_end }} ·
          该考点共 {{ kpCache[g.kp].total_questions }} 题，错 {{ kpCache[g.kp].wrong_count }} 题
        </div>
        <template v-for="(e, i) in kpCache[g.kp].excerpts" :key="i">
          <div v-if="i === 0 || kpCache[g.kp].excerpts[i - 1].kp_id !== e.kp_id"
               style="display:flex;align-items:center;gap:8px;margin:14px 0 8px;padding-top:10px;border-top:1px dashed var(--line)">
            <span class="tag" :class="{ grey: !e.is_current }">{{ e.is_current ? '本题考点' : '相邻考点' }}</span>
            <b style="font-size:14px;color:var(--ink)">{{ e.kp_name }}</b>
          </div>
          <div style="margin-bottom:12px">
            <span class="tag grey" v-if="e.page_no">{{ e.file_page ? '文件第 ' + e.page_no + ' 页' : 'p' + e.page_no }}</span>
            <div style="margin-top:6px"><RichText :text="e.text" /></div>
          </div>
        </template>
      </div>

      <div v-for="q in g.list" :key="q.id" style="border-top:1px solid var(--line);padding:9px 0">
        <div style="font-size:14px">{{ q.stem }}</div>
        <div class="muted" style="font-size:12.5px;margin-top:3px">
          {{ typeLabel(q.qtype) }} · 正确答案 <b>{{ answerLabel(q) }}</b>
          <span v-if="q.explanation">　{{ q.explanation.slice(0, 70) }}…</span>
        </div>
      </div>
    </div>

    <p v-if="!wrongs.length && !err" class="note ok">错题本是空的。去「刷题」或做一套「押题卷」吧。</p>
  </template>
</template>
