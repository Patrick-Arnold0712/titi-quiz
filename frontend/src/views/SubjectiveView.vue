<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type SubjChecklist, type SubjItem, type SubjTier } from '@/api'

// 主观题易考清单：简答 2×5 分 + 论述 1×20 分。
//
// 排序依据全部来自库里的数据，不是人工排的：
//   1. 考点权重 —— analyze_subject 算的「该考点在 100 分卷里的预估占分」
//   2. 知识体系 —— 考点 → 节 → 章 的路径，反向拆出「章 · 节」
// 默认按「优先分」降序（预估占分 × 题型系数），也可以切回教材章节顺序。
//
// 要点默认收起：先自己回想一遍再点开，比直接读有效得多。展开状态记在 localStorage。

const router = useRouter()
const data = ref<SubjChecklist | null>(null)
const err = ref('')
const sort = ref<'weight' | 'chapter'>('weight')

const tier = ref<SubjTier | 'all'>('all')
const chapter = ref<string>('all')
const open = reactive<Record<string, boolean>>({})
const allOpen = ref(false)

const TIER_LABEL: Record<SubjTier, string> = { S: 'S 必背', A: 'A 高频', B: 'B 补充' }
const TIER_CLASS: Record<SubjTier, string> = { S: 'bad', A: 'warn', B: 'grey' }

const items = computed(() => data.value?.items ?? [])
const shown = computed(() => {
  const rows = items.value.filter(it =>
    (tier.value === 'all' || it.tier === tier.value) &&
    (chapter.value === 'all' || it.root_chapter === chapter.value))
  // 按权重：优先分降序，同分的 S 在前
  return sort.value === 'weight'
    ? [...rows].sort((a, b) => (b.priority - a.priority) || a.tier.localeCompare(b.tier))
    : rows
})
/** 两种排序统一成「小节列表」，模板里只写一遍卡片。
    按权重时只有一节（标题为空，不渲染 h2）；按章节时每章一节，沿用清单里的章序。 */
const sections = computed<{ title: string; rows: SubjItem[] }[]>(() =>
  sort.value === 'weight'
    ? [{ title: '', rows: shown.value }]
    : (data.value?.chapters ?? [])
        .map(ch => ({ title: ch, rows: shown.value.filter(it => it.root_chapter === ch) }))
        .filter(sec => sec.rows.length > 0),
)
const countOf = (t: SubjTier) => items.value.filter(it => it.tier === t).length
const chapterCount = (ch: string) => items.value.filter(it => it.root_chapter === ch).length
// 没有作答记录时不显示 0% —— 那是「算不出来」，不是「水平为零」
const pctText = (v?: number | null) =>
  (!data.value?.has_records || v === null || v === undefined) ? '—' : `${Math.round(v * 100)}%`

function isOpen(it: SubjItem) { return !!open[it.id] }
function toggle(id: string) { open[id] = !open[id] }
function toggleAll() {
  allOpen.value = !allOpen.value
  for (const it of items.value) open[it.id] = allOpen.value
  try { localStorage.setItem('subj.open', allOpen.value ? '1' : '0') } catch { /* 隐私模式无妨 */ }
}
/** 跳去刷这个考点的题。q_total=0 的考点不跳 —— 不做「点了空手回来」的事。 */
function practice(kpId: number, qTotal: number) {
  if (!qTotal) return
  router.push({ name: 'practice', query: { kp: String(kpId), n: String(Math.min(15, qTotal)) } })
}

onMounted(async () => {
  try {
    data.value = await api.subjectiveChecklist()
    let pref = '0'
    try { pref = localStorage.getItem('subj.open') ?? '0' } catch { /* ignore */ }
    if (pref === '1') { allOpen.value = true; for (const it of items.value) open[it.id] = true }
  } catch (e: any) { err.value = String(e.message ?? e) }
})
</script>

<template>
  <h1>主观题易考清单</h1>
  <p class="muted">
    简答题 2×5 分 + 论述题 1×20 分。排序依据是<b>考点权重</b>（预估占分）与
    <b>知识体系</b>（考点 → 节 → 章），不是人工排的。每题标了教材页码与历年命中。
  </p>
  <p class="muted" v-if="err">接口未就绪：{{ err }}</p>

  <template v-if="data">
    <div class="card">
      <h3 style="margin-top:0">考情（近 5 年）</h3>
      <ul style="margin:0 0 10px;padding-left:20px">
        <li v-for="f in data.meta.exam_facts" :key="f">{{ f }}</li>
      </ul>
      <div class="statline">
        <span class="tag bad">{{ data.meta.legend.S }}</span>
        <span class="tag warn">{{ data.meta.legend.A }}</span>
        <span class="tag grey">{{ data.meta.legend.B }}</span>
      </div>
      <div class="note warn">{{ data.meta.warn }}</div>
      <p class="muted" style="margin:10px 0 0">依据：{{ data.meta.sources.join('；') }}</p>
      <p class="muted" style="margin:6px 0 0">{{ data.weights.note }}</p>
    </div>

    <div class="toolbar">
      <button class="chip" :class="{ on: tier === 'all' }" @click="tier = 'all'">全部 {{ items.length }}</button>
      <button v-for="t in (['S', 'A', 'B'] as SubjTier[])" :key="t"
              class="chip" :class="{ on: tier === t }" @click="tier = t">
        {{ TIER_LABEL[t] }} {{ countOf(t) }}
      </button>
      <span style="flex:1"></span>
      <button class="btn ghost mini" @click="toggleAll">
        {{ allOpen ? '全部收起要点' : '全部展开要点' }}
      </button>
    </div>

    <div class="toolbar">
      <button class="chip" :class="{ on: chapter === 'all' }" @click="chapter = 'all'">全五章</button>
      <button v-for="ch in data.chapters" :key="ch" class="chip"
              :class="{ on: chapter === ch }" @click="chapter = ch">
        {{ ch }} {{ chapterCount(ch) }}
      </button>
    </div>

    <div class="toolbar">
      <span class="muted">排序</span>
      <button class="chip" :class="{ on: sort === 'weight' }" @click="sort = 'weight'">按权重（预估占分）</button>
      <button class="chip" :class="{ on: sort === 'chapter' }" @click="sort = 'chapter'">按教材章节</button>
    </div>

    <template v-for="sec in sections" :key="sec.title || 'all'">
      <h2>
        {{ sec.title || '全部条目' }}
        <span class="muted" style="font-weight:400">
          {{ sec.rows.length }} 条{{ sec.title ? '' : '，按优先分降序' }}
        </span>
      </h2>
      <div class="card subj" v-for="it in sec.rows" :key="it.id">
        <div class="statline">
          <span class="tag" :class="TIER_CLASS[it.tier]">{{ TIER_LABEL[it.tier] }}</span>
          <span class="tag grey">{{ it.root_chapter }} · {{ it.section }}</span>
          <span class="tag grey">{{ it.page }}</span>
          <span class="tag warn">预估 {{ it.est_score.toFixed(2) }} 分</span>
          <span class="tag ok">优先 {{ it.priority.toFixed(2) }}</span>
          <span class="muted">掌握度 {{ pctText(it.mastery) }}</span>
          <span style="flex:1"></span>
          <button class="btn ghost mini" @click="toggle(it.id)">{{ isOpen(it) ? '收起' : '看答案要点' }}</button>
        </div>

        <h3 class="stem">{{ it.stem }}</h3>
        <p class="muted" style="margin:2px 0 8px" v-if="it.asked.length">
          命中：{{ it.asked.join(' ｜ ') }}
        </p>

        <template v-if="isOpen(it)">
          <p v-if="it.lead" class="lead">{{ it.lead }}</p>
          <ol class="points">
            <li v-for="(p, i) in it.points" :key="i">{{ p }}</li>
          </ol>
          <div class="note" v-if="it.tip">应试提示：{{ it.tip }}</div>
        </template>
        <p class="muted" style="margin:0" v-else>
          {{ it.points.length }} 个要点<span v-if="it.lead"> + 1 句总起</span>，先自己说一遍。
          <span style="display:block">依据：{{ it.evidence }}</span>
        </p>

        <div class="foot">
          <span class="muted">考点：{{ it.kp_name || '未映射' }}</span>
          <span style="flex:1"></span>
          <button class="btn mini" :disabled="!it.q_total" @click="practice(it.kp_id, it.q_total)">
            {{ it.q_total ? `做相关题目（${it.q_total} 道可练）→` : '该考点暂无题' }}
          </button>
        </div>
      </div>
    </template>

    <h2 v-if="data.gaps.length">权重盲区（清单没覆盖，但占分不低）</h2>
    <div class="card" v-if="data.gaps.length">
      <p class="muted" style="margin-top:0">
        把库里的考点按预估占分排一遍，挑出清单里没有的高权重考点。这些不一定考简答，
        但权重摆在这里 —— 至少把教材那几页看一眼。
      </p>
      <div class="gap" v-for="g in data.gaps" :key="g.kp_id">
        <div class="statline" style="margin-bottom:4px">
          <span class="tag warn">预估 {{ g.est_score.toFixed(2) }} 分</span>
          <span class="tag grey">{{ g.chapter }}</span>
          <span class="tag grey" v-if="g.page_start">教材 p{{ g.page_start }}</span>
          <span class="muted">掌握度 {{ pctText(g.mastery) }}</span>
        </div>
        <b>{{ g.name }}</b>
        <button class="btn ghost mini" style="margin-left:8px" :disabled="!g.total_q"
                @click="practice(g.kp_id, g.total_q)">
          {{ g.total_q ? `做这 ${g.total_q} 道题 →` : '暂无题' }}
        </button>
      </div>
    </div>

    <h2>{{ data.essay.title }}</h2>
    <div class="card">
      <p style="margin-top:0">{{ data.essay.intro }}</p>
      <div class="note warn">{{ data.essay.time }}</div>
    </div>

    <div class="card">
      <h3 style="margin-top:0">近 5 年考过的论述题</h3>
      <ul class="hist">
        <li v-for="(h, i) in data.essay.history" :key="i">
          <span class="tag grey">{{ h.year }}</span> {{ h.stem }}
        </li>
      </ul>
    </div>

    <div class="card">
      <h3 style="margin-top:0">20 分四步模板</h3>
      <div class="step" v-for="(m, i) in data.essay.model" :key="i">
        <h4>{{ m.step }}</h4>
        <p style="margin:0">{{ m.body }}</p>
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0">大概率再考的四个母题</h3>
      <div class="theme" v-for="(b, i) in data.essay.bank" :key="i">
        <h4>{{ b.theme }}</h4>
        <p class="muted" style="margin:0 0 6px">已考过：{{ b.hits }}</p>
        <div class="note">骨架：{{ b.skeleton }}</div>
      </div>
    </div>
  </template>
</template>

<style scoped>
.toolbar { margin-bottom: 10px; }
.subj { padding: 12px 14px; }
.subj .stem { margin: 0 0 4px; color: var(--ink); font-size: 15.5px; line-height: 1.45; }
.subj .lead {
  margin: 0 0 8px; padding: 8px 10px; border-radius: 8px;
  background: var(--pri-l); font-size: 13.5px; line-height: 1.7;
}
/* 要点列表：行距放宽 —— 清单是要一条条看进去的，不是扫的 */
.subj .points { margin: 0 0 10px; padding-left: 20px; }
.subj .points li { margin-bottom: 5px; line-height: 1.75; font-size: 14px; }
.subj .foot { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.hist { margin: 0; padding-left: 0; list-style: none; }
.hist li { margin-bottom: 7px; line-height: 1.7; }
.step, .theme { margin-bottom: 12px; }
.step:last-child, .theme:last-child { margin-bottom: 0; }
.step h4, .theme h4 { margin: 0 0 4px; font-size: 14.5px; color: var(--pri-d); }
.step p { font-size: 13.5px; line-height: 1.75; }
.gap { padding: 8px 0; border-top: 1px solid var(--line); }
.gap:first-of-type { border-top: 0; }
</style>
