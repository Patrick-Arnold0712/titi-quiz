<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Advice } from '@/api'
import { accKnown, pct, pctOr } from '@/format'

const props = defineProps<{ subjectId: number }>()
const router = useRouter()
const adv = ref<Advice | null>(null)
const days = ref(7); const minutes = ref(90); const err = ref('')

async function load() {
  try { adv.value = await api.advice(props.subjectId, days.value, minutes.value) }
  catch (e: any) { err.value = String(e.message ?? e) }
}
onMounted(load)

// 只有错题记录时，正确率/掌握度算不出来 —— 显示「—」而不是 0%
const known = computed(() => accKnown(adv.value?.kpi))

/** 与 planner 的 action 文案同一口径：今天做几道。 */
function planCount(it: any): number {
  const todo = Math.max(0, (it.total_q ?? 0) - (it.attempted ?? 0))
  return Math.max(1, Math.min(15, todo || 15))
}
/** 点冲刺清单 → 直接去刷这个考点的题（带上建议的题数） */
function goPractice(it: any) {
  router.push({ name: 'practice', query: { kp: String(it.kp_id), n: String(planCount(it)) } })
}
</script>

<template>
  <h1>备考建议</h1>
  <p class="muted" v-if="err">接口未就绪：{{ err }}</p>

  <div class="toolbar">
    <label class="muted">剩余天数 <input type="number" v-model.number="days" min="1" max="60" style="width:70px" /></label>
    <label class="muted">每天可用 <input type="number" v-model.number="minutes" min="10" max="600" style="width:80px" /> 分钟</label>
    <button class="btn mini" @click="load">重新生成</button>
  </div>

  <template v-if="adv">
    <div class="card">
      <h3 style="margin-top:0">现状</h3>
      <p><b>{{ adv.stage }}</b> —— {{ adv.readiness }}</p>
      <div class="statline">
        <span class="pill">覆盖 {{ pct(adv.kpi.coverage) }}</span>
        <span class="pill" :class="{ dim: !known }">正确率 {{ pctOr(adv.kpi.accuracy, known) }}</span>
        <span class="pill" :class="{ dim: !known }">掌握度 {{ pctOr(adv.kpi.mastery, known) }}</span>
        <span class="pill">作答 {{ adv.kpi.attempts }} 次</span>
      </div>
      <div class="note warn" v-if="adv.data_note" style="margin-top:10px">{{ adv.data_note }}</div>
    </div>

    <h2>冲刺清单（按失分风险排序）</h2>
    <div class="card risk" v-for="it in adv.roi_plan" :key="it.kp_id"
         role="button" tabindex="0"
         :title="`点开就去做「${it.name}」的题`"
         @click="goPractice(it)"
         @keydown.enter.prevent="goPractice(it)" @keydown.space.prevent="goPractice(it)">
      <div class="statline">
        <span class="tag bad">风险 {{ it.risk_score.toFixed(1) }} 分</span>
        <span class="tag grey">{{ it.chapter }}</span>
        <span class="tag grey" v-if="it.page">教材 p{{ it.page }}</span>
        <span class="spacer" style="flex:1"></span>
        <span class="muted">掌握度 {{ pctOr(it.mastery, known) }}</span>
      </div>
      <h3 style="margin:4px 0;color:var(--ink);font-size:15px">{{ it.rank }}. {{ it.name }}</h3>
      <p class="muted" style="margin:0 0 8px">{{ it.why }}</p>
      <div class="note">👉 {{ it.action }}</div>
      <div class="go">去做这 {{ planCount(it) }} 道题 →</div>
    </div>

    <h2>必背清单（按预估占分）</h2>
    <div class="card">
      <div class="tscroll">
<table>
        <thead><tr><th>考点</th><th>章</th><th>预估占分</th><th>掌握度</th></tr></thead>
        <tbody>
          <tr v-for="m in adv.must_know" :key="m.name">
            <td>{{ m.name }}</td><td>{{ m.chapter }}</td>
            <td>{{ m.est_score.toFixed(1) }}</td>
            <td>
              <span v-if="known" :style="{ color: m.mastery < 0.7 ? 'var(--bad)' : 'var(--ok)' }">{{ pct(m.mastery) }}</span>
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>

    <h2>{{ adv.schedule.days }} 天计划</h2>
    <div class="card">
      <div class="note warn">{{ adv.schedule.budget_advice }}</div>
      <div v-for="ph in adv.schedule.timeline" :key="ph.phase" style="margin-top:14px">
        <h3 style="color:var(--ink)">{{ ph.phase }}</h3>
        <p class="muted" style="margin:0 0 6px">{{ ph.note }}</p>
        <ul style="margin:0;padding-left:20px">
          <li v-for="f in ph.focus" :key="f.name">{{ f.name }} <span class="muted">（{{ f.chapter }}）</span></li>
        </ul>
      </div>
      <h3>执行规则</h3>
      <ul style="margin:0;padding-left:20px">
        <li v-for="r in adv.schedule.rules" :key="r">{{ r }}</li>
      </ul>
    </div>
  </template>
</template>

<style scoped>
.risk { cursor: pointer; transition: box-shadow .15s, border-color .15s; }
.risk:hover { border-color: var(--pri); box-shadow: 0 2px 10px rgba(18, 128, 92, .12); }
.risk:focus-visible { outline: 2px solid var(--pri); outline-offset: 2px; }
.risk .go { margin-top: 8px; font-size: 13px; font-weight: 600; color: var(--pri); }
</style>
