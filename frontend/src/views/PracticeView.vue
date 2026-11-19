<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { answerLabel } from '@/format'
import { api, type Question, type Chapter } from '@/api'

const props = defineProps<{ subjectId: number }>()
const route = useRoute()
const router = useRouter()
const chapters = ref<Chapter[]>([])
const qs = ref<Question[]>([])
const idx = ref(0)
const picked = ref('')
const revealed = ref(false)
const err = ref('')
const kpFilter = ref<number | null>(null)
const kpName = ref('')
// 从「备考建议 / 概览」的失分风险卡片点进来时带上的：这次要刷几道
const planLimit = ref<number | null>(null)
// 考点 chip 有 72 个，全展开会把屏幕铺满、把题目挤到看不见。
// 从风险卡片点进来时默认**收起**——用户此刻要的是做题，不是挑考点。
const showChips = ref(true)

onMounted(async () => {
  try {
    const d = await api.subjectDetail(props.subjectId)
    chapters.value = d.chapters ?? []
    await applyRoute()
  } catch (e: any) { err.value = String(e.message ?? e) }
})

// 同一个页面组件在 ?kp= 变化时不会重新 mount，
// 所以必须监听 query —— 否则「点了第二张风险卡片，题目没换」。
watch(() => [route.query.kp, route.query.n].join('|'), () => {
  if (route.name === 'practice') applyRoute()
})

/** 按 URL 上的 ?kp=<考点>&n=<题数> 决定这次刷什么。 */
async function applyRoute() {
  const kpId = route.query.kp ? Number(route.query.kp) : null
  const n = route.query.n ? Number(route.query.n) : null
  planLimit.value = n && n > 0 ? n : null
  if (kpId) {
    showChips.value = false
    await loadByKp(kpId, kpNameOf(kpId) || `考点 ${kpId}`, planLimit.value)
  } else {
    showChips.value = true
    await loadAll()
  }
  window.scrollTo({ top: 0 })
}

function kpNameOf(id: number): string {
  for (const ch of chapters.value)
    for (const kp of ch.knowledge_points ?? [])
      if (kp.id === id) return kp.name
  return ''
}

async function loadAll() {
  kpFilter.value = null; kpName.value = ''; planLimit.value = null
  qs.value = await api.questions({ subject_id: props.subjectId, limit: 1000 })
  reset()
}
async function loadByKp(id: number, name: string, limit: number | null = null) {
  kpFilter.value = id; kpName.value = name
  const rows = await api.questions({ subject_id: props.subjectId, kp_id: id, limit: 100 })
  qs.value = limit ? rows.slice(0, limit) : rows
  reset()
}
function reset() { idx.value = 0; picked.value = ''; revealed.value = false }

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push({ name: 'advice' })
}

const q = computed(() => qs.value[idx.value])
const isMulti = computed(() => q.value?.qtype === 'multi_choice')
// 填空可能有多种正确表述，沿用对照参考答案的方式，不据字符串相似度记错题。
const isSubjective = computed(() => ['short_answer', 'essay', 'fill_blank'].includes(q.value?.qtype ?? ''))
// 题面残缺：不能让用户答。答了也判不了分，还会被记进错题本。
const isDefective = computed(() => q.value?.quality === 'defective')
const ok = computed(() => {
  const a = (q.value?.answer ?? '').toUpperCase().split('').sort().join('')
  const u = picked.value.toUpperCase().split('').sort().join('')
  return a && a === u
})

function pick(k: string) {
  if (revealed.value || isDefective.value) return
  if (isMulti.value) {
    const s = new Set(picked.value.split(''))
    s.has(k) ? s.delete(k) : s.add(k)
    picked.value = [...s].sort().join('')
  } else picked.value = k
}
const on = (k: string) => picked.value.includes(k)

async function reveal() {
  revealed.value = true
  // 记录作答：错题本和掌握度统计都依赖它。
  // 残缺题不记 —— 记了就是拿一道坏题给用户扣分。
  if (q.value && !isSubjective.value && !isDefective.value) {
    try { await api.answerQuestion(q.value.id, picked.value) } catch { /* 记录失败不影响刷题 */ }
  }
}
function next() { if (idx.value < qs.value.length - 1) { idx.value++; picked.value = ''; revealed.value = false } }
function prev() { if (idx.value > 0) { idx.value--; picked.value = ''; revealed.value = false } }
</script>

<template>
  <h1>刷题</h1>
  <p class="muted" v-if="err">接口未就绪：{{ err }}</p>

  <div class="toolbar" v-if="kpFilter">
    <!-- 这个入口不只从备考建议来（简答清单的「做相关题目」也走 ?kp=），
         所以按来路返回；没有历史时兜底回备考建议。 -->
    <button class="btn ghost mini" @click="goBack()">← 返回</button>
    <span class="muted">
      正在按考点「<b>{{ kpName }}</b>」刷题<template v-if="planLimit">（本次 {{ qs.length }} 道）</template>
    </span>
  </div>

  <div class="toolbar">
    <button class="btn ghost mini" @click="showChips = !showChips">
      {{ showChips ? '收起考点' : '换考点' }}
    </button>
    <span class="muted" v-if="!showChips && kpFilter">当前：<b>{{ kpName }}</b></span>
  </div>

  <div class="toolbar" v-show="showChips">
    <button class="chip" :class="{ on: kpFilter === null }" @click="loadAll()">全部</button>
    <template v-for="ch in chapters" :key="ch.id">
      <button v-for="kp in (ch.knowledge_points ?? [])" :key="kp.id"
              class="chip" :class="{ on: kpFilter === kp.id }"
              @click="loadByKp(kp.id, kp.name); showChips = false">{{ kp.name }}</button>
    </template>
  </div>

  <template v-if="q">
    <div class="statline">
      <span class="pill">{{ kpName || '全部题目' }}</span>
      <span class="pill">{{ idx + 1 }} / {{ qs.length }}</span>
      <span class="tag grey">{{ { single_choice: '单选', multi_choice: '多选', true_false: '判断', fill_blank: '填空', short_answer: '简答', essay: '论述' }[q.qtype] ?? q.qtype }}</span>
      <span class="tag bad" v-if="isDefective">题面残缺</span>
      <span class="tag grey" v-if="q.source_type === 'real_exam'">真题</span>
      <span class="tag grey" v-if="q.year">{{ q.year }}</span>
    </div>

    <div class="card">
      <div class="note bad" v-if="isDefective" style="margin-bottom:10px">
        <b>这道题的题面不完整，跳过它。</b>
        题库里这道题的{{ q.options?.length ? '题干有问题' : '选项没拆出来' }}，
        作答也不会被记录。点「下一题」继续。
      </div>

      <div class="q-stem">{{ q.stem }}</div>
      <template v-if="isDefective">
        <!-- 残缺题不给选项，避免诱导作答 -->
      </template>
      <template v-else-if="q.options?.length && !isSubjective">
        <div v-for="o in q.options" :key="o.key" class="opt"
             :class="{ on: on(o.key) && !revealed,
                       right: revealed && q.answer.includes(o.key),
                       wrong: revealed && on(o.key) && !q.answer.includes(o.key) }"
             @click="pick(o.key)">
          <span class="k">{{ o.key }}</span><span>{{ o.text }}</span>
        </div>
      </template>
      <div v-else class="note">先在心里作答，再点「看答案」对照参考答案。</div>

      <div class="toolbar" style="margin:12px 0 0">
        <button class="btn ghost mini" :disabled="idx === 0" @click="prev">上一题</button>
        <button class="btn" v-if="!revealed" :disabled="isDefective || (!picked && !isSubjective)" @click="reveal">看答案</button>
        <button class="btn ghost mini" v-else @click="next">下一题</button>
        <span class="spacer" style="flex:1"></span>
        <span v-if="revealed && !isSubjective" class="tag" :class="ok ? 'ok' : 'bad'">{{ ok ? '答对' : '答错' }}</span>
      </div>
    </div>

    <div class="card" v-if="revealed">
      <div class="note" :class="isSubjective ? '' : (ok ? 'ok' : 'bad')">
        <b>正确答案：</b>{{ q.answer ? answerLabel(q) : '见解析' }}
      </div>
      <div class="note ok" v-if="q.explanation" style="margin-top:8px"><b>解析：</b>{{ q.explanation }}</div>
      <p class="muted" v-else style="margin:8px 0 0">这道题暂无解析。</p>
    </div>
  </template>
  <p v-else-if="!err" class="muted">这个筛选下没有题目。</p>
</template>
