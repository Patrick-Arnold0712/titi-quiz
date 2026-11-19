<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { answerLabel } from '@/format'
import { useRoute, useRouter } from 'vue-router'
import { api, type ReviewRow } from '@/api'

const route = useRoute(); const router = useRouter()
const data = ref<{ score: number; detail: any; rows: ReviewRow[] } | null>(null)
const filter = ref<'all' | 'wrong' | 'pending'>('all')
const err = ref('')

onMounted(async () => {
  try { data.value = await api.review(Number(route.params.id)) }
  catch (e: any) { err.value = String(e.message ?? e) }
})

const rows = computed(() => {
  const r = data.value?.rows ?? []
  if (filter.value === 'wrong') return r.filter(x => x.is_correct === false)
  if (filter.value === 'pending') return r.filter(x => x.pending_manual)
  return r
})
</script>

<template>
  <div v-if="err" class="note bad">{{ err }}</div>
  <template v-if="data">
    <h1>试卷回看</h1>
    <div class="grid c3">
      <div class="card kpi"><div class="v">{{ data.score.toFixed(0) }}</div><div class="k">客观题得分</div></div>
      <div class="card kpi"><div class="v">{{ data.detail?.objective_total?.toFixed(0) ?? '-' }}</div><div class="k">客观题满分</div></div>
      <div class="card kpi"><div class="v">{{ data.detail?.subjective_total?.toFixed(0) ?? '-' }}</div><div class="k">主观题满分（待人工）</div></div>
      <div class="card kpi"><div class="v">{{ data.detail?.right ?? 0 }} / {{ (data.detail?.right ?? 0) + (data.detail?.wrong ?? 0) }}</div><div class="k">答对 / 总题</div></div>
    </div>

    <div class="note warn" v-if="data.detail?.defective" style="margin-bottom:12px">
      本卷有 <b>{{ data.detail.defective }}</b> 道题的题面不完整（选项没拆出来 / 设空丢了），
      合 {{ data.detail.defective_total?.toFixed(0) }} 分，<b>已从计分中剔除</b> ——
      这些题不是你不会，是题有毛病，所以不算错、也不进错题本。
      下面它们会被标成「题面残缺 · 无法判分」。
    </div>

    <div class="card">
      <h3 style="margin-top:0">分大题</h3>
      <div class="tscroll">
<table>
        <thead><tr><th>大题</th><th>得分</th><th>满分</th><th>正确</th><th>待人工</th><th>残缺</th></tr></thead>
        <tbody>
          <tr v-for="s in data.detail?.sections ?? []" :key="s.section">
            <td>{{ s.section }}</td>
            <td><b>{{ s.got.toFixed(1) }}</b></td>
            <td>{{ s.total.toFixed(0) }}</td>
            <td>{{ s.right }}/{{ s.count }}</td>
            <td>{{ s.pending || '' }}</td>
            <td>{{ s.defective || '' }}</td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>

    <div class="toolbar">
      <button class="chip" :class="{ on: filter === 'all' }" @click="filter = 'all'">全部 {{ data.rows.length }}</button>
      <button class="chip" :class="{ on: filter === 'wrong' }" @click="filter = 'wrong'">只看错题 {{ data.rows.filter(r => r.is_correct === false && r.quality !== 'defective').length }}</button>
      <button class="chip" :class="{ on: filter === 'pending' }" @click="filter = 'pending'">主观题 {{ data.rows.filter(r => r.pending_manual).length }}</button>
      <span style="flex:1"></span>
      <button class="btn ghost mini" @click="router.push({ name: 'papers' })">返回试卷库</button>
    </div>

    <div class="card" v-for="r in rows" :key="r.order_index">
      <div class="statline">
        <span class="pill">{{ r.section_name }}</span>
        <span class="pill">第 {{ r.order_index }} 题</span>
        <span class="pill">{{ r.score_per }} 分</span>
        <span class="pill" v-if="r.display_qtype === 'multi_choice'">多选（错选漏选不得分）</span>
        <span class="tag bad" v-if="r.quality === 'defective'">题面残缺 · 无法判分</span>
    <span class="tag" v-else-if="r.pending_manual">主观题 · 待人工</span>
        <span class="tag ok" v-else-if="r.is_correct">答对</span>
        <span class="tag bad" v-else-if="r.quality !== 'defective'">答错</span>
      </div>
      <div class="q-stem">{{ r.stem }}</div>
      <div v-for="o in r.options ?? []" :key="o.key" class="opt"
           :class="{ right: r.quality !== 'defective' && r.answer.includes(o.key),
              wrong: r.quality !== 'defective' && r.user_answer.includes(o.key) && !r.answer.includes(o.key) }"
           style="cursor:default">
        <span class="k">{{ o.key }}</span><span>{{ o.text }}</span>
      </div>
      <div class="note" style="margin-top:8px">
        <!-- 判断题的作答在库里统一存 A/B（见 data/normalize_true_false_attempts.py），
             直接显示「A」用户看不懂，要按题型翻译回「正确/错误」。
             和正确答案用的是同一个 answerLabel。 -->
        <b>你的答案：</b>{{
          r.user_answer
            ? answerLabel({ qtype: r.qtype, display_qtype: r.display_qtype, answer: r.user_answer })
            : '（未作答）'
        }}　
        <b>正确答案：</b>{{ r.answer ? answerLabel(r) : '（主观题见解析）' }}
      </div>
      <div class="note ok" v-if="r.explanation" style="margin-top:8px">
        <b>解析：</b>{{ r.explanation }}
      </div>
    </div>
  </template>
  <p v-else-if="!err" class="muted">加载中…</p>
</template>
