<script setup lang="ts">
import { computed, inject, onMounted, ref, type ComputedRef } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Advice } from '@/api'
import { accKnown, pct, pctOr } from '@/format'

const props = defineProps<{ subjectId: number }>()
const router = useRouter()
const adv = ref<Advice | null>(null)
const err = ref('')
const subjectCode = inject<ComputedRef<string>>('subjectCode', computed(() => ''))
const isMilitary = computed(() => subjectCode.value === 'military_theory')

onMounted(async () => {
  try { adv.value = await api.advice(props.subjectId, 7, 90) }
  catch (e: any) { err.value = String(e.message ?? e) }
})

// 正确率/掌握度能不能算出来。算不出来（只有错题、没有答对记录）就显示「—」，
// 否则 0% 会被读成「我一道题都没做对」，跟事实不符。
const known = computed(() => accKnown(adv.value?.kpi))

const barCls = (x: number, pass: number) => (x < pass ? 'bad' : x < 0.8 ? 'warn' : '')

/** 这张卡片建议今天做几道 —— 与 planner 的 action 文案用同一个口径。 */
function planCount(it: any): number {
  const todo = Math.max(0, (it.total_q ?? 0) - (it.attempted ?? 0))
  return Math.max(1, Math.min(15, todo || 15))
}

/** 点风险卡片 → 直接去刷这个考点的题。
 *  把「今天做几道」也带上，else 用户看到建议写 15 道、进去却是 100 道，会觉得两边对不上。 */
function goPractice(it: any) {
  router.push({ name: 'practice', query: { kp: String(it.kp_id), n: String(planCount(it)) } })
}

function onCardKey(e: KeyboardEvent, it: any) {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); goPractice(it) }
}
</script>

<template>
  <h1>概览</h1>
  <p class="muted" v-if="adv">当前阶段：<b>{{ adv.stage }}</b> —— {{ adv.readiness }}</p>
  <p class="muted" v-if="err">接口未就绪：{{ err }}（先启动后端 uvicorn）</p>

  <template v-if="adv">
    <div class="note warn" v-if="adv.data_note" style="margin-top:12px">
      <b>数据说明</b>：{{ adv.data_note }}
    </div>

    <div class="grid c3" style="margin-top:14px">
      <div class="card kpi">
        <div class="v">{{ pct(adv.kpi.coverage) }}</div>
        <div class="k">考点覆盖率（{{ adv.kpi.kp_attempted }}/{{ adv.kpi.kp_total }}）</div>
      </div>
      <div class="card kpi">
        <div class="v" :class="{ dim: !known }">{{ pctOr(adv.kpi.accuracy, known) }}</div>
        <div class="k">总正确率<span v-if="!known">（无答对记录）</span></div>
      </div>
      <div class="card kpi">
        <div class="v" :class="{ dim: !known }">{{ pctOr(adv.kpi.mastery, known) }}</div>
        <div class="k">加权掌握度<span v-if="!known">（数据不足）</span></div>
      </div>
      <div class="card kpi"><div class="v">{{ adv.kpi.attempts }}</div><div class="k">累计作答</div></div>
    </div>

    <div class="card">
      <div class="statline">
        <span class="pill">及格 {{ pct(adv.lines.pass) }}</span>
        <span class="pill">安全 {{ pct(adv.lines.safe) }}</span>
        <span class="pill">掌握 {{ pct(adv.lines.mastery) }}</span>
      </div>
      <template v-if="known">
        <div class="bar" :class="barCls(adv.kpi.accuracy, adv.lines.pass)">
          <i :style="{ width: Math.min(100, adv.kpi.accuracy * 100) + '%' }"></i>
        </div>
        <p class="muted" style="margin:6px 0 0">正确率相对及格线的位置</p>
      </template>
      <p class="muted" v-else style="margin:6px 0 0">
        正确率暂时无法计算（没有答对记录），所以这里不画进度条 —— 先用覆盖率判断进度。
      </p>
    </div>

    <h2>章节风险</h2>
    <div class="card">
      <div class="tscroll">
<table>
        <thead><tr><th>章</th><th>考点</th><th>预估占分</th><th>失分风险</th><th>正确率</th><th>覆盖</th></tr></thead>
        <tbody>
          <tr v-for="c in adv.chapter_risk" :key="c.chapter">
            <td>{{ c.chapter }}</td>
            <td>{{ c.kp }}</td>
            <td>{{ c.est_score.toFixed(1) }}</td>
            <td><b style="color:var(--bad)">{{ c.risk_score.toFixed(1) }}</b></td>
            <td>{{ pctOr(c.accuracy, known) }}</td>
            <td>{{ pct(c.coverage) }}</td>
          </tr>
        </tbody>
      </table>
      </div>
      <p class="muted" v-if="!known" style="margin:8px 0 0">
        失分风险目前是按「预估占分 × 覆盖率」估算的 —— 等有了答对记录，会自动切换成按掌握度算。
      </p>
    </div>

    <h2>马上要做的三件事</h2>
    <div class="grid c2">
      <div class="card risk" v-for="it in adv.roi_plan.slice(0, 3)" :key="it.kp_id"
           role="button" tabindex="0"
           :title="`点开就去做「${it.name}」的题`"
           @click="goPractice(it)" @keydown="onCardKey($event, it)">
        <div><span class="tag">风险 {{ it.risk_score.toFixed(1) }} 分</span><span class="tag grey">{{ it.chapter }}</span></div>
        <h3 style="margin:6px 0 4px;color:var(--ink);font-size:15px">{{ it.name }}</h3>
        <p class="muted" style="margin:0 0 8px">{{ it.why }}</p>
        <div class="note">{{ it.action }}</div>
        <div class="go">去做这 {{ planCount(it) }} 道题 →</div>
      </div>
    </div>

    <div class="toolbar" style="margin-top:16px">
      <button v-if="isMilitary" class="btn" @click="router.push({ name: 'papers' })">去组一套押题卷</button>
      <button class="btn ghost" @click="router.push({ name: 'advice' })">看完整备考建议</button>
    </div>
  </template>
</template>

<style scoped>
/* 风险卡片整块可点：从「看到风险」到「开始做题」中间不该再有一次点击 */
.risk { cursor: pointer; transition: box-shadow .15s, border-color .15s; }
.risk:hover { border-color: var(--pri); box-shadow: 0 2px 10px rgba(18, 128, 92, .12); }
.risk:focus-visible { outline: 2px solid var(--pri); outline-offset: 2px; }
.risk .go { margin-top: 8px; font-size: 13px; font-weight: 600; color: var(--pri); }
</style>
