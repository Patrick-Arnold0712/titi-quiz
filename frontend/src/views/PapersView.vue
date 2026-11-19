<script setup lang="ts">
import { computed, inject, onMounted, reactive, ref, type ComputedRef } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Paper, type PaperBlueprint } from '@/api'

const props = defineProps<{ subjectId: number }>()
const router = useRouter()
const subjectCode = inject<ComputedRef<string>>('subjectCode', computed(() => ''))
const isMilitary = computed(() => subjectCode.value === 'military_theory')
const papers = ref<Paper[]>([])
const bp = ref<PaperBlueprint[]>([])
const busy = ref(false)
const err = ref('')
const open = ref<Record<number, boolean>>({})
const showParams = ref(false)

const MIX_LABEL: Record<string, string> = { real_exam: '真题', refsite_chapter: '章节题', predict: '自出题' }
const BUCKETS = ['real_exam', 'refsite_chapter', 'predict'] as const

// 默认配额与后端 DEFAULT_BLUEPRINT 一致。面板只改「题源配额」，
// 不动题数和分值 —— 卷面结构必须和官方蓝图一致。
const form = reactive({
  single: { real_exam: 9, refsite_chapter: 7, predict: 4 },
  multi: { real_exam: 5, refsite_chapter: 3, predict: 2 },
  // 主观题只有「真题」和「自出题」两类可配：
  // 自出题里优先选教材课后习题（题干就是教材原话，见 generator 的 W_HOMEWORK）
  short_answer: { real_exam: 1, predict: 1 },
  essay: { real_exam: 1, predict: 0 },
  auto_cloze: 3,
  minImp: 0,
  duration: 60,
})

const sectionCount = (qtype: string) =>
  bp.value.find(b => b.qtype === qtype)?.count ?? 0

const sum = (m: Record<string, number>, keys: readonly string[]) =>
  keys.reduce((s, k) => s + (m[k] || 0), 0)
const singleTotal = computed(() => sum(form.single, BUCKETS))
const multiTotal = computed(() => sum(form.multi, BUCKETS))
const subjTotal = (m: Record<string, number>) => sum(m, ['real_exam', 'predict'])
const mixWarn = computed(() => {
  const w: string[] = []
  if (singleTotal.value !== sectionCount('single_choice'))
    w.push(`单选配额合计 ${singleTotal.value}，应为 ${sectionCount('single_choice')}`)
  if (multiTotal.value !== sectionCount('multi_choice'))
    w.push(`不定项配额合计 ${multiTotal.value}，应为 ${sectionCount('multi_choice')}`)
  if (subjTotal(form.short_answer) !== sectionCount('short_answer'))
    w.push(`简答配额合计 ${subjTotal(form.short_answer)}，应为 ${sectionCount('short_answer')}`)
  if (subjTotal(form.essay) !== sectionCount('essay'))
    w.push(`论述配额合计 ${subjTotal(form.essay)}，应为 ${sectionCount('essay')}`)
  return w
})

async function load() {
  try {
    papers.value = await api.papers(props.subjectId)
    bp.value = await api.blueprint()
  } catch (e: any) { err.value = String(e.message ?? e) }
}
onMounted(load)

function resetParams() {
  form.single = { real_exam: 9, refsite_chapter: 7, predict: 4 }
  form.multi = { real_exam: 5, refsite_chapter: 3, predict: 2 }
  form.short_answer = { real_exam: 1, predict: 1 }
  form.essay = { real_exam: 1, predict: 0 }
  form.auto_cloze = 3; form.minImp = 0; form.duration = 60
}

async function generate() {
  busy.value = true; err.value = ''
  try {
    const name = `押题卷 ${new Date().toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}`
    const p = await api.generatePaper({
      subject_id: props.subjectId,
      name,
      seed: Math.floor(Math.random() * 100000),
      duration_min: form.duration,
      // 配额合计对不上时后端也只会「不够就顺延补足」，不会把卷子做短
      mix: {
        single_choice: { ...form.single },
        multi_choice: { ...form.multi },
        short_answer: { ...form.short_answer },
        essay: { ...form.essay },
      },
      auto_cloze: form.auto_cloze,
      min_kp_importance: form.minImp,
    })
    await load()
    router.push({ name: 'exam', params: { id: p.id } })
  } catch (e: any) { err.value = String(e.message ?? e) }
  finally { busy.value = false }
}

const totalOf = (p: Paper) => (p.blueprint ?? []).reduce((s, b) => s + (b.total ?? b.count * b.score_per), 0)
const done = (p: Paper) => (p.done_count ?? 0) > 0
function mixChips(p: Paper) {
  const m = p.source_mix ?? {}
  return Object.entries(m).filter(([, v]) => v > 0).map(([k, v]) => `${MIX_LABEL[k] ?? k} ${v}`)
}
const noteLines = (p: Paper) => (p.note ?? '').split('；').filter(x => x.trim())
const fmtTime = (s?: string | null) => s ? new Date(s).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
</script>

<template>
  <h1>{{ isMilitary ? '押题模拟' : '练习卷' }}</h1>
  <p v-if="isMilitary" class="muted">
    卷面结构固定按官方蓝图；题源只用<b>历年真题</b>、<b>参考站章节题</b>（题题带解析）和<b>自出题</b>，
    并按真题的章节分布配比。信度不够的题库不参与组卷。
  </p>
  <p v-else class="muted">从资料库导入习题册时，可同时创建一份练习卷。</p>
  <p class="muted" v-if="err">接口未就绪：{{ err }}</p>

  <div v-if="isMilitary" class="card">
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <h3 style="margin:0;flex:1">组卷参数</h3>
      <button class="btn ghost mini" @click="showParams = !showParams">{{ showParams ? '收起' : '展开' }}</button>
      <button class="btn" :disabled="busy" @click="generate">{{ busy ? '组卷中…' : '生成一套押题卷' }}</button>
    </div>

    <template v-if="showParams">
      <div class="grid c2" style="margin-top:12px">
        <div class="card tight" style="margin:0">
          <div style="font-weight:600">一、单项选择（{{ sectionCount('single_choice') }} 题）</div>
          <div class="params">
            <label v-for="k in BUCKETS" :key="k">{{ MIX_LABEL[k] }}
              <input type="number" min="0" v-model.number="form.single[k]">
            </label>
          </div>
          <div class="muted">合计 {{ singleTotal }} / {{ sectionCount('single_choice') }}</div>
        </div>
        <div class="card tight" style="margin:0">
          <div style="font-weight:600">二、不定项选择（{{ sectionCount('multi_choice') }} 题）</div>
          <div class="params">
            <label v-for="k in BUCKETS" :key="k">{{ MIX_LABEL[k] }}
              <input type="number" min="0" v-model.number="form.multi[k]">
            </label>
          </div>
          <div class="muted">合计 {{ multiTotal }} / {{ sectionCount('multi_choice') }}</div>
        </div>
        <div class="card tight" style="margin:0">
          <div style="font-weight:600">三、简答 / 四、论述（主观题）</div>
          <div class="params">
            <label>简答·真题 <input type="number" min="0" v-model.number="form.short_answer.real_exam"></label>
            <label>简答·自出题 <input type="number" min="0" v-model.number="form.short_answer.predict"></label>
          </div>
          <div class="muted">合计 {{ subjTotal(form.short_answer) }} / {{ sectionCount('short_answer') }}</div>
          <div class="params">
            <label>论述·真题 <input type="number" min="0" v-model.number="form.essay.real_exam"></label>
            <label>论述·自出题 <input type="number" min="0" v-model.number="form.essay.predict"></label>
          </div>
          <div class="muted">
            合计 {{ subjTotal(form.essay) }} / {{ sectionCount('essay') }}　
            自出题里优先选<b>教材课后思考题</b>（题干就是教材原话）。
          </div>
        </div>

        <div class="card tight" style="margin:0">
          <div style="font-weight:600">自出题</div>
          <div class="params">
            <label>本次现造（教材挖空）
              <input type="number" min="0" max="10" v-model.number="form.auto_cloze">
            </label>
            <label>考点重要度门槛
              <input type="number" min="0" max="1" step="0.1" v-model.number="form.minImp">
            </label>
            <label>考试时长（分钟）
              <input type="number" min="10" max="180" v-model.number="form.duration">
            </label>
          </div>
          <div class="muted">
            每次组卷会现造几道<b>依据教材原文</b>的单选题（年份 / 著作法律 / 考点术语三类轮转），
            题干是教材原句，不接模型也不会偏题。造好的题会入库复用。
          </div>
        </div>
        <div class="card tight" style="margin:0">
          <div style="font-weight:600">说明</div>
          <div class="muted" style="margin-top:6px">
            · 配额加起来不够该大题题数时，多出来的位置按「真题 → 章节题 → 自出题」顺延补足，卷子不会变短。<br>
            · 门槛调到 0.3 以上，就只从「真题常考 + 教材篇幅大」的考点里挖空。<br>
            · 每次结果都会写进下面每套卷的「命题说明」，可核对实际构成。
          </div>
          <div class="toolbar" style="margin-top:8px">
            <button class="btn ghost mini" @click="resetParams">恢复默认</button>
          </div>
        </div>
      </div>
      <div class="note warn" v-if="mixWarn.length" style="margin-top:10px">
        {{ mixWarn.join('；') }} —— 仍然可以组卷，差额会自动补足。
      </div>
    </template>
    <p class="muted" v-else style="margin:10px 0 0">
      默认：单选 真题9/章节7/自出4，不定项 真题5/章节3/自出2，每次现造 3 道自出题。
      点「展开」可自己调。
    </p>
  </div>

  <h2>试卷库（{{ papers.length }} 套）</h2>
  <div class="grid c2">
    <div class="card" v-for="p in papers" :key="p.id">
      <div>
        <span class="tag" :class="p.source_type === 'generated' ? 'warn' : ''">
          {{ p.source_type === 'generated' ? '押题卷' : p.source_type === 'own_material' ? '练习卷' : '真题' }}
        </span>
        <span class="tag grey" v-if="p.year">{{ p.year }}</span>
        <span class="tag grey" v-if="p.volume">{{ p.volume }}</span>
        <span class="tag ok" v-if="done(p)">已完成{{ (p.done_count ?? 0) > 1 ? ` ×${p.done_count}` : '' }}</span>
        <span class="tag grey" v-else-if="(p.attempt_count ?? 0) > 0">未交卷</span>
      </div>
      <h3 style="margin:6px 0 4px;color:var(--ink);font-size:15px">{{ p.name }}</h3>
      <div class="muted">{{ totalOf(p).toFixed(0) }} 分 / {{ p.duration_min }} 分钟　
        <span v-for="b in p.blueprint" :key="b.section">{{ b.section.replace(/^[一二三四五六]、/, '') }}×{{ b.count }}　</span>
      </div>

      <div class="statline" v-if="mixChips(p).length" style="margin-top:6px">
        <span class="pill" v-for="c in mixChips(p)" :key="c">{{ c }}</span>
      </div>

      <div class="muted" v-if="done(p)" style="margin-top:6px">
        最近一次 <b>{{ p.last_score?.toFixed(0) }}</b> 分
        <span v-if="p.last_submitted_at"> · {{ fmtTime(p.last_submitted_at) }}</span>
      </div>

      <div class="toolbar" style="margin:10px 0 0">
        <button class="btn mini" @click="router.push({ name: 'exam', params: { id: p.id } })">
          {{ (p.attempt_count ?? 0) > 0 && p.last_status === 'doing' ? '继续作答' : (done(p) ? '再做一遍' : '开始作答') }}
        </button>
        <button class="btn ghost mini" v-if="done(p) && p.last_attempt_id"
                @click="router.push({ name: 'review', params: { id: p.last_attempt_id } })">查看回看</button>
        <button class="btn ghost mini" v-if="noteLines(p).length" @click="open[p.id] = !open[p.id]">
          {{ open[p.id] ? '收起命题说明' : '命题说明' }}
        </button>
      </div>

      <div class="note" v-if="open[p.id]" style="margin-top:8px">
        <div v-for="(l, i) in noteLines(p)" :key="i">· {{ l }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.params { display: flex; flex-wrap: wrap; gap: 8px 14px; margin: 8px 0; }
.params label { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-2, #555); }
.params input { width: 62px; padding: 4px 6px; border: 1px solid var(--line); border-radius: 8px; font: inherit; }
</style>
