<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, type KnowledgeBit, type SearchResult, type KpDetail } from '@/api'
import RichText from '@/components/RichText.vue'

const props = defineProps<{ subjectId: number }>()

// 一个页面两种模式：
//   有输入 -> 全局搜索（BM25），结果全部可点开
//   无输入 -> 分类速查（知识链接 / 年份 / 法律 / 著作）

type Kind = 'link' | 'year' | 'law' | 'work'

const TABS: { k: Kind; label: string; icon: string; hint: string }[] = [
  { k: 'link', label: '知识链接', icon: '★', hint: '教材里的知识链接、补充材料' },
  { k: 'year', label: '年份', icon: '⏱', hint: '时间点速查。按教材/题目里提及次数排序' },
  { k: 'law', label: '法规文件', icon: '§', hint: '法规、文件的通过与施行时间' },
  { k: 'work', label: '著作名篇', icon: '❦', hint: '著作、名篇、作者与地位' },
]

const q = ref('')
const kind = ref<Kind>('link')
const rows = ref<KnowledgeBit[]>([])
const stats = ref<Record<string, number>>({})
const open = ref<number | null>(null)
const err = ref('')
const loading = ref(false)
const searching = ref(false)
const searched = ref<SearchResult | null>(null)

// ---- 搜索结果的各种展开状态 ----
const openKp = ref<number | null>(null)                       // 考点：展开看教材原文
const kpCache = ref<Record<number, KpDetail>>({})
const kpLoading = ref(false)
const openExcerpt = ref<Record<number, boolean>>({})          // 教材段落：展开全文
const openBit = ref<Record<number, boolean>>({})              // 速查条目：展开正文
const picks = ref<Record<number, string>>({})                 // 题目：已选项
const judged = ref<Record<number, { ok: boolean }>>({})       // 题目：已判分
const peeked = ref<Record<number, boolean>>({})               // 题目：直接看答案
const busy = ref<number | null>(null)

const inSearch = computed(() => q.value.trim().length > 0)
const cur = computed(() => TABS.find(t => t.k === kind.value)!)
const lines = (b: KnowledgeBit) => (b.detail ?? '').split('\n').filter(Boolean)
const defaultOpen = (b: KnowledgeBit) => b.kind === 'link'
const isOpen = (b: KnowledgeBit) => (open.value === b.id) || (open.value === null && defaultOpen(b))
const pageLabel = (b: KnowledgeBit) => (b.page_no ? `教材 p${b.page_no}` : '')

const QT: Record<string, string> = {
  single_choice: '单选', multi_choice: '多选', true_false: '判断',
  short_answer: '简答', essay: '论述',
}

// ---- 答题 ----
const isMulti = (t: any) => t.qtype === 'multi_choice'
const answered = (id: number) => !!judged.value[id] || !!peeked.value[id]
const reveal = (id: number) => answered(id)

function pick(t: any, key: string) {
  if (answered(t.id) || t.quality === 'defective') return
  if (isMulti(t)) {
    const s = new Set((picks.value[t.id] ?? '').split(''))
    s.has(key) ? s.delete(key) : s.add(key)
    picks.value[t.id] = [...s].sort().join('')
  } else picks.value[t.id] = key
}
const chosen = (t: any, key: string) => (picks.value[t.id] ?? '').includes(key)

async function submit(t: any) {
  if (!picks.value[t.id] || busy.value) return
  busy.value = t.id
  try {
    const a: any = await api.answerQuestion(t.id, picks.value[t.id])
    judged.value[t.id] = { ok: !!a.is_correct }
  } catch (e: any) { err.value = String(e.message ?? e) }
  finally { busy.value = null }
}

// ---- 考点展开 ----
async function toggleKp(id: number) {
  if (openKp.value === id) { openKp.value = null; return }
  openKp.value = id
  if (!kpCache.value[id]) {
    kpLoading.value = true
    try { kpCache.value[id] = await api.kpDetail(id) } catch { /* 拿不到就空着 */ }
    finally { kpLoading.value = false }
  }
}

async function loadKind() {
  loading.value = true; err.value = ''
  try {
    rows.value = await api.bits({ kind: kind.value, subject_id: props.subjectId, limit: 500 })
    stats.value = await api.bitsStats(props.subjectId)
  } catch (e: any) { err.value = String(e.message ?? e) }
  finally { loading.value = false }
}

async function runSearch() {
  const term = q.value.trim()
  if (!term) { searched.value = null; return }
  searching.value = true; err.value = ''
  try { searched.value = await api.search(term, 6, props.subjectId) }
  catch (e: any) { err.value = String(e.message ?? e) }
  finally { searching.value = false }
}

onMounted(async () => { await loadKind() })
watch([kind], () => { open.value = null; if (!inSearch.value) loadKind() })

let timer: number | undefined
function onInput() {
  if (timer) clearTimeout(timer)
  timer = window.setTimeout(runSearch, 280)
}
function clearSearch() {
  q.value = ''; searched.value = null
  openKp.value = null; openExcerpt.value = {}; openBit.value = {}
  picks.value = {}; judged.value = {}; peeked.value = {}
}

const safe = (s: string) => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!))
function highlight(text: string, terms: string[]) {
  let out = safe(text)
  const sorted = [...terms].filter(t => t.length >= 2).sort((a, b) => b.length - a.length)
  for (const t of sorted) out = out.split(safe(t)).join(`\u0003${safe(t)}\u0004`)
  return out.replace(/\u0003/g, '<b style="color:var(--pri-d);background:#e6f4ee;border-radius:3px;padding:0 2px">')
            .replace(/\u0004/g, '</b>')
}
</script>

<template>
  <h1>搜索</h1>
  <p class="muted">输入关键词，一次搜出<b>考点、教材原文、题目、速查条目</b>；不输入就是分类速查。</p>
  <p class="muted" v-if="err">接口未就绪：{{ err }}</p>

  <div class="toolbar" style="margin-bottom:12px">
    <input type="search" v-model="q" @input="onInput" autofocus
           placeholder="搜点东西，如 航母 / 国防法 / 孙子兵法"
           style="flex:1;min-width:200px;font-size:15px" />
    <button class="btn ghost mini" v-if="inSearch" @click="clearSearch">清空</button>
  </div>

  <!-- ================= 搜索结果 ================= -->
  <template v-if="inSearch">
    <p class="muted" v-if="searching">搜索中…</p>

    <template v-else-if="searched">
      <p class="muted">
        分词：<span class="tag grey" v-for="t in searched.terms" :key="t">{{ t }}</span>
        <span v-if="!searched.terms.length">没有可检索的词，换个更具体的词试试</span>
      </p>

      <!-- ---------- 考点：点开看该考点的教材原文 ---------- -->
      <template v-if="searched.kps.length">
        <h2>相关考点 <span class="muted" style="font-weight:400">点开看教材原文</span></h2>
        <div class="card" v-for="k in searched.kps" :key="k.id">
          <div style="display:flex;align-items:baseline;gap:8px;cursor:pointer"
               @click="toggleKp(k.id)">
            <b style="font-size:15px;color:var(--ink)">{{ k.name }}</b>
            <span class="tag grey">{{ k.via }}命中</span>
            <span style="flex:1"></span>
            <span class="muted" style="font-size:12px">{{ openKp === k.id ? '收起' : '展开' }}</span>
          </div>
          <div class="muted" style="font-size:13px;margin-top:2px">
            {{ k.chapter }}<span v-if="k.section"> / {{ k.section }}</span>
            <span v-if="k.page_start"> · 教材 p{{ k.page_start }}-{{ k.page_end }}</span>
          </div>

          <div v-if="openKp === k.id" style="margin-top:12px">
            <p class="muted" v-if="kpLoading && !kpCache[k.id]">加载中…</p>
            <template v-else-if="kpCache[k.id]">
              <div class="statline">
                <span class="pill">该考点共 {{ kpCache[k.id].total_questions }} 题</span>
                <span class="pill" :class="{ bad: kpCache[k.id].wrong_count }">
                  错题 {{ kpCache[k.id].wrong_count }} 道</span>
              </div>
              <template v-for="(e, i) in kpCache[k.id].excerpts" :key="i">
                <div v-if="i === 0 || kpCache[k.id].excerpts[i - 1].kp_id !== e.kp_id"
                     style="display:flex;align-items:center;gap:8px;margin:14px 0 8px;padding-top:10px;border-top:1px dashed var(--line)">
                  <span class="tag" :class="{ grey: !e.is_current }">{{ e.is_current ? '本题考点' : '相邻考点' }}</span>
                  <b style="font-size:14px;color:var(--ink)">{{ e.kp_name }}</b>
                </div>
                <div style="margin-bottom:12px">
                  <span class="tag grey" v-if="e.page_no">{{ e.file_page ? '文件第 ' + e.page_no + ' 页' : 'p' + e.page_no }}</span>
                  <div style="margin-top:6px"><RichText :text="e.text" /></div>
                </div>
              </template>
            </template>
          </div>
        </div>
      </template>

      <!-- ---------- 教材原文：展开全文 ---------- -->
      <template v-if="searched.excerpts.length">
        <h2>教材原文</h2>
        <div class="card" v-for="e in searched.excerpts" :key="e.id">
          <div class="statline" style="margin-bottom:6px">
            <span class="tag">{{ !e.page_no ? '教材原文' : e.file_page ? '文件第 ' + e.page_no + ' 页' : '教材 p' + e.page_no }}</span>
            <span class="tag grey" v-if="e.kp_name">{{ e.kp_name }}</span>
            <span style="flex:1"></span>
            <button class="chip" @click="openExcerpt[e.id] = !openExcerpt[e.id]">
              {{ openExcerpt[e.id] ? '收起' : '展开全文' }}</button>
          </div>
          <div v-if="openExcerpt[e.id]">
            <RichText :text="e.full || e.snippet" />
          </div>
          <div v-else style="font-size:14.5px;line-height:1.95;color:#24352d"
               v-html="highlight(e.snippet, searched.terms)"></div>
        </div>
      </template>

      <!-- ---------- 题目：直接在搜索结果里做 ---------- -->
      <template v-if="searched.questions.length">
        <h2>相关题目 <span class="muted" style="font-weight:400">点选项直接做</span></h2>
        <div class="card" v-for="t in searched.questions" :key="t.id">
          <div class="statline" style="margin-bottom:8px">
            <span class="tag grey">{{ QT[t.qtype ?? ''] ?? t.qtype }}</span>
            <span class="tag grey" v-if="t.kp_name">{{ t.kp_name }}</span>
            <span class="tag bad" v-if="t.quality === 'defective'">题面残缺</span>
            <span style="flex:1"></span>
            <span class="tag ok" v-if="reveal(t.id)">答案 {{ t.answer }}</span>
          </div>

          <div style="font-size:14.5px;line-height:1.85" v-html="highlight(t.stem ?? '', searched.terms)"></div>

          <div class="note bad" v-if="t.quality === 'defective'" style="margin-top:10px">
            题面不完整（设空丢了 / 选项没拆出来），不能作答。下面是解析。
          </div>

          <template v-else-if="t.options?.length">
            <div v-for="o in t.options" :key="o.key" class="opt" style="margin-top:7px"
                 :class="{ on: chosen(t, o.key) && !reveal(t.id),
                           right: reveal(t.id) && (t.answer ?? '').includes(o.key),
                           wrong: reveal(t.id) && chosen(t, o.key) && !(t.answer ?? '').includes(o.key) }"
                 @click="pick(t, o.key)">
              <span class="k">{{ o.key }}</span><span>{{ o.text }}</span>
            </div>

            <div class="toolbar" style="margin:10px 0 0">
              <button class="btn mini" v-if="!answered(t.id)"
                      :disabled="!picks[t.id] || busy === t.id" @click="submit(t)">
                {{ busy === t.id ? '判分中…' : '提交' }}</button>
              <button class="btn ghost mini" v-if="!answered(t.id)" @click="peeked[t.id] = true">直接看答案</button>
              <span class="tag ok" v-if="judged[t.id]?.ok">答对，已记录</span>
              <span class="tag bad" v-else-if="judged[t.id]">答错 —— 已进错题本</span>
              <span class="muted" v-if="answered(t.id) && !judged[t.id]" style="font-size:12.5px">
                你选 <b>{{ picks[t.id] || '（未作答）' }}</b></span>
            </div>
          </template>
          <p class="muted" v-else style="margin-top:8px">这道题没有可作答的选项。</p>

          <div class="note ok" style="margin-top:10px" v-if="reveal(t.id) && t.explanation">
            <b>解析：</b><div style="margin-top:4px"><RichText :text="t.explanation" /></div>
          </div>
        </div>
      </template>

      <!-- ---------- 速查条目：展开正文 ---------- -->
      <template v-if="searched.bits.length">
        <h2>速查条目</h2>
        <div class="card" v-for="b in searched.bits" :key="b.id" style="padding:12px 16px">
          <div style="display:flex;align-items:baseline;gap:8px;cursor:pointer"
               @click="openBit[b.id] = !openBit[b.id]">
            <b style="color:var(--ink)">
              <template v-if="b.bit_kind === 'year'">{{ b.key }}</template>
              <template v-else>《{{ b.key }}》</template>
            </b>
            <span class="tag grey" v-if="b.hits && b.hits > 1">×{{ b.hits }}</span>
            <span class="tag grey" v-if="b.page_no">教材 p{{ b.page_no }}</span>
            <span style="flex:1"></span>
            <span class="muted" style="font-size:12px">{{ openBit[b.id] ? '收起' : '展开' }}</span>
          </div>
          <div v-if="openBit[b.id]" style="margin-top:10px"><RichText :text="b.detail" /></div>
          <div v-else style="font-size:14px;line-height:1.9;color:#2b3a33;margin-top:6px"
               v-html="highlight((b.detail ?? '').split('\n')[0].slice(0, 150), searched.terms)"></div>
        </div>
      </template>

      <p v-if="!searched.kps.length && !searched.excerpts.length && !searched.questions.length && !searched.bits.length"
         class="note warn">没搜到。换个词试试，或者只输入关键词的一部分（比如「导弹」而不是「反舰导弹的型号」）。</p>
    </template>
  </template>

  <!-- ================= 分类速查 ================= -->
  <template v-else>
    <div class="toolbar">
      <button v-for="t in TABS" :key="t.k" class="chip" :class="{ on: kind === t.k }"
              @click="kind = t.k">{{ t.icon }} {{ t.label }}
        <span v-if="stats[t.k]" class="muted">{{ stats[t.k] }}</span>
      </button>
    </div>
    <div class="note" style="margin-bottom:12px">{{ cur.hint }}</div>
    <p class="muted" v-if="loading">加载中…</p>
    <div class="card" v-for="b in rows" :key="b.id" style="padding:12px 16px">
      <div style="display:flex;align-items:baseline;gap:8px;cursor:pointer"
           @click="open = open === b.id ? -1 : b.id">
        <b style="color:var(--ink);font-size:15px">
          <template v-if="b.kind === 'year'">{{ b.key }}</template>
          <template v-else>《{{ b.key }}》</template>
        </b>
        <span class="tag grey" v-if="b.hits > 1">×{{ b.hits }}</span>
        <span class="tag grey" v-if="pageLabel(b)">{{ pageLabel(b) }}</span>
        <span class="muted" style="font-size:12px" v-if="b.kp_name">{{ b.kp_name }}</span>
        <span style="flex:1"></span>
        <span class="muted" style="font-size:12px">{{ isOpen(b) ? '收起' : '展开' }}</span>
      </div>
      <div v-if="isOpen(b)" style="margin-top:10px"><RichText :text="b.detail" /></div>
      <p v-else class="muted" style="margin:6px 0 0;font-size:13px">{{ lines(b)[0]?.slice(0, 54) }}…</p>
    </div>
  </template>
</template>
