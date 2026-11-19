<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type PaperDetail } from '@/api'

const route = useRoute()
const router = useRouter()
const paper = ref<PaperDetail | null>(null)
const attemptId = ref<number | null>(null)
const answers = ref<Record<number, string>>({})
const flags = ref<Record<number, boolean>>({})
const cur = ref(0)
const left = ref(0)
const err = ref('')
const submitting = ref(false)
let timer: number | undefined
const startedAt = Date.now()

onMounted(async () => {
  try {
    const pid = Number(route.params.id)
    paper.value = await api.paper(pid, false)      // 不带答案，防作弊
    const a = await api.startAttempt(pid)
    attemptId.value = a.id
    left.value = (paper.value.duration_min || 60) * 60
    timer = window.setInterval(() => {
      left.value--
      if (left.value <= 0) doSubmit()
    }, 1000)
  } catch (e: any) { err.value = String(e.message ?? e) }
})
onUnmounted(() => { if (timer) clearInterval(timer) })

const items = computed(() => paper.value?.items ?? [])
const item = computed(() => items.value[cur.value])
const secs = computed(() => {
  const m = Math.max(0, Math.floor(left.value / 60))
  const s = Math.max(0, left.value % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})
// 卷面题型用 display_qtype，不用题目自身的 qtype：
// 判断题编进「一、单项选择题」后，卷面上就是单选题（A=正确/B=错误），
// 拿 qtype 判断会让它走进单选题以外的分支。
const dt = computed(() => item.value?.display_qtype ?? item.value?.question.qtype ?? '')
// 同时认短名：蓝图里存过 "multi" 这种写法（见后端 canon_qtype）。
// 这里留一层兜底，是因为「qtype 有两种写法」这件事本身就不该让前端猜第二次。
const isMulti = computed(() => ['multi_choice', 'multi'].includes(dt.value))
const isSubjective = computed(() => ['short_answer', 'short', 'essay'].includes(dt.value))
// 题面残缺的题（选项没拆出来、设空丢了）：不能渲染成可作答的样子，也不能记入作答。
// 否则用户答了也判不了分，交卷时还会被判错 —— 白白往错题本里灌脏数据。
const isDefective = computed(() => item.value?.question.quality === 'defective')
const answeredCount = computed(() => Object.values(answers.value).filter(v => v && v.trim()).length)

function pick(key: string) {
  if (!item.value || isDefective.value) return
  const qid = item.value.question.id
  if (isSubjective.value) return
  if (isMulti.value) {
    const set = new Set((answers.value[qid] ?? '').split(''))
    set.has(key) ? set.delete(key) : set.add(key)
    answers.value[qid] = [...set].sort().join('')
  } else {
    answers.value[qid] = key
  }
}
const chosen = (key: string) => (answers.value[item.value?.question.id] ?? '').includes(key)

async function doSubmit() {
  if (!attemptId.value || submitting.value) return
  if (timer) clearInterval(timer)
  submitting.value = true
  try {
    // 题面残缺的题不提交 —— 后端也会跳过它们，这里是双保险
    const payload = items.value
      .filter(it => it.question.quality !== 'defective')
      .map(it => ({
        question_id: it.question.id,
        user_answer: answers.value[it.question.id] ?? '',
      }))
    await api.submitAttempt(attemptId.value, payload, Date.now() - startedAt)
    router.push({ name: 'review', params: { id: attemptId.value } })
  } catch (e: any) { err.value = String(e.message ?? e); submitting.value = false }
}
</script>

<template>
  <div v-if="err" class="note bad">{{ err }}</div>
  <template v-if="paper && item">
    <div class="toolbar">
      <button class="btn ghost mini" @click="router.push({ name: 'papers' })">← 返回</button>
      <span class="tag">{{ paper.name }}</span>
      <span class="tag grey">已答 {{ answeredCount }} / {{ items.length }}</span>
      <span class="spacer" style="flex:1"></span>
      <span class="tag" :class="left < 300 ? 'bad' : 'ok'">⏱ {{ secs }}</span>
    </div>

    <div class="card">
      <h3 style="margin-top:0">答题卡</h3>
      <div class="sheet">
        <div v-for="(it, i) in items" :key="it.question.id"
             class="cell"
             :class="{ done: !!answers[it.question.id], cur: i === cur, flag: flags[it.question.id],
                       broken: it.question.quality === 'defective' }"
             :title="it.question.quality === 'defective' ? '题面残缺，无法作答' : (it.section_name ?? '')"
             @click="cur = i">{{ it.order_index }}</div>
      </div>
    </div>

    <div class="card">
      <div class="statline">
        <span class="pill">{{ item.section_name }}</span>
        <span class="pill">第 {{ item.order_index }} 题</span>
        <span class="pill">{{ item.score_per }} 分</span>
        <span class="pill" v-if="isMulti">多选（错选漏选不得分）</span>
      </div>

      <div class="note bad" v-if="isDefective" style="margin-bottom:10px">
        <b>这道题的题面不完整，无法作答。</b>
        题库里这道题{{ item.question.options?.length ? '的题干有问题' : '的选项没拆出来' }}，
        交卷时会跳过它、不计入成绩。请到「资料库」反馈或直接跳过。
      </div>

      <div class="q-stem">{{ item.question.stem }}</div>

      <template v-if="isDefective">
        <!-- 故意什么都不渲染：给出可点的选项反而会诱导用户作答 -->
      </template>
      <template v-else-if="item.question.options?.length && !isSubjective">
        <div v-for="o in item.question.options" :key="o.key"
             class="opt" :class="{ on: chosen(o.key) }" @click="pick(o.key)">
          <span class="k">{{ o.key }}</span><span>{{ o.text }}</span>
        </div>
      </template>
      <template v-else>
        <textarea v-model="answers[item.question.id]" rows="6"
                  style="width:100%;font-family:inherit;font-size:14px;border:1px solid var(--line);border-radius:10px;padding:10px"
                  placeholder="主观题作答（本次不做自动批改，交卷后给参考答案）"></textarea>
      </template>

      <div class="toolbar" style="margin:14px 0 0">
        <button class="btn ghost mini" :disabled="cur === 0" @click="cur--">上一题</button>
        <button class="btn ghost mini" :disabled="cur >= items.length - 1" @click="cur++">下一题</button>
        <button class="btn ghost mini" @click="flags[item.question.id] = !flags[item.question.id]">
          {{ flags[item.question.id] ? '取消标记' : '标记待定' }}
        </button>
        <span class="spacer" style="flex:1"></span>
        <button class="btn" :disabled="submitting" @click="doSubmit">{{ submitting ? '交卷中…' : '交卷' }}</button>
      </div>
    </div>
  </template>
  <p v-else-if="!err" class="muted">加载中…</p>
</template>
