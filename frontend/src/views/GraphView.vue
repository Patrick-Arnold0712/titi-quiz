<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import { accKnown, pct as fmtPct } from '@/format'

const props = defineProps<{ subjectId: number }>()
const detail = ref<any>(null)
const stats = ref<Record<number, any>>({})
const open = ref<number | null>(null)
const err = ref('')
// 只有错题记录时掌握度恒为 0，那是假数字 —— 这时整列显示「—」
const known = ref(true)

onMounted(async () => {
  try {
    detail.value = await api.subjectDetail(props.subjectId)
    const a = await api.adviceAnalysis(props.subjectId)
    for (const s of a.knowledge_points) stats.value[s.kp_id] = s
    known.value = accKnown(a.kpi)
    open.value = tree.value[0]?.id ?? null
  } catch (e: any) { err.value = String(e.message ?? e) }
})

// chapters 表里「章」和「节」是同一张表，靠 parent_id 区分：
// parent_id 为空的是章，其余是节。后端平铺返回，这里拼成两层树。
const tree = computed(() => {
  const all: any[] = detail.value?.chapters ?? []
  const sections = new Map<number, any[]>()
  for (const c of all) {
    if (c.parent_id == null) continue
    const list = sections.get(c.parent_id) ?? []
    list.push(c)
    sections.set(c.parent_id, list)
  }
  return all
    .filter((c) => c.parent_id == null)
    .map((c) => ({ ...c, children: sections.get(c.id) ?? [] }))
})

const summary = computed(() => {
  const units = tree.value.length
  const sections = tree.value.reduce((n, ch) => n + ch.children.length, 0)
  const kps = tree.value.reduce(
    (n, ch) => n + ch.children.reduce((m: number, sec: any) => m + (sec.knowledge_points?.length ?? 0), 0),
    0,
  )
  return `${units} 个单元 / ${sections} 节 / ${kps} 个考点`
})

const pct = fmtPct
// 一个章下的考点总数与已作答数，用来算章节覆盖率
function chapterAgg(ch: any) {
  let totalQ = 0, attempted = 0, kp = 0
  for (const sec of ch.children) {
    for (const k of (sec.knowledge_points ?? [])) {
      kp++
      totalQ += stats.value[k.id]?.total_q ?? 0
      attempted += stats.value[k.id]?.attempted ?? 0
    }
  }
  return { kp, cov: totalQ ? attempted / totalQ : 0 }
}
</script>

<template>
  <h1>考点图谱</h1>
  <p class="muted">{{ summary }}，每个考点都能溯源到教材页码。数字来自教材篇幅与题库覆盖。</p>
  <p class="muted" v-if="!known">当前没有答对记录，掌握度算不出来，整列显示「—」；覆盖率和权重不受影响。</p>
  <p class="muted" v-if="err">接口未就绪：{{ err }}</p>

  <template v-if="detail">
    <div class="card" v-for="ch in tree" :key="ch.id">
      <div style="display:flex;align-items:center;gap:10px;cursor:pointer" @click="open = open === ch.id ? null : ch.id">
        <h3 style="margin:0;color:var(--ink);font-size:15px">{{ ch.name }}</h3>
        <span class="muted" v-if="ch.page_start">p{{ ch.page_start }}</span>
        <span class="tag grey">{{ chapterAgg(ch).kp }} 个考点</span>
        <span class="spacer" style="flex:1"></span>
        <span class="muted">{{ open === ch.id ? '收起' : '展开' }}</span>
      </div>

      <div v-if="open === ch.id" style="margin-top:10px">
        <div v-for="sec in ch.children" :key="sec.id" style="margin-bottom:14px">
          <h4 style="margin:0 0 4px;color:var(--ink);font-size:13.5px">{{ sec.name }}</h4>
          <div class="tscroll">
<table>
            <thead><tr><th>考点</th><th>教材页</th><th>权重</th><th>掌握度</th><th>题量</th><th>覆盖</th></tr></thead>
            <tbody>
              <tr v-for="kp in (sec.knowledge_points ?? [])" :key="kp.id">
                <td>{{ kp.name }}</td>
                <td class="muted">p{{ kp.page_start }}<span v-if="kp.page_end">-{{ kp.page_end }}</span></td>
                <td>
                  <div class="bar" style="width:70px"><i :style="{ width: ((kp.importance ?? 0) * 100) + '%' }"></i></div>
                </td>
                <td>
                  <!-- 「没做过」和「做了全错」是两回事，不能都显示 0% -->
                  <span v-if="!stats[kp.id]" class="muted">—</span>
                  <span v-else-if="!stats[kp.id].attempted" class="muted" title="这个考点你一道题都没做过">未做</span>
                  <span v-else-if="!known" class="muted" title="缺少答对记录，掌握度算不出来">—</span>
                  <span v-else :style="{ color: stats[kp.id].mastery < 0.7 ? 'var(--bad)' : 'var(--ok)' }">
                    {{ pct(stats[kp.id].mastery) }}
                  </span>
                </td>
                <td class="muted">{{ stats[kp.id]?.total_q ?? 0 }}</td>
                <td class="muted">{{ stats[kp.id] ? pct(stats[kp.id].coverage) : '—' }}</td>
              </tr>
            </tbody>
          </table>
      </div>
        </div>
      </div>
    </div>
  </template>
</template>
