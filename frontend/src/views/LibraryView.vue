<script setup lang="ts">
import { computed, inject, onMounted, ref, type ComputedRef } from 'vue'
import { api, type NetInfo } from '@/api'
import MaterialImport from '@/components/MaterialImport.vue'

const props = defineProps<{ subjectId: number }>()
const subjectCode = inject<ComputedRef<string>>('subjectCode', computed(() => ''))
const isMilitary = computed(() => subjectCode.value === 'military_theory')
const docs = ref<any[]>([])
const payload = ref('')
const preview = ref<any>(null)
const result = ref<any>(null)
const busy = ref(false)
const importErr = ref('')
const replace = ref(false)
const createSubject = inject<(name: string) => Promise<void>>('createSubject')
const newSubject = ref('')
const creating = ref(false)
const subjectErr = ref('')
async function addSubject() {
  if (!createSubject || !newSubject.value.trim()) return
  creating.value = true; subjectErr.value = ''
  try { await createSubject(newSubject.value.trim()) }
  catch (e) { subjectErr.value = e instanceof Error ? e.message : String(e) }
  finally { creating.value = false }
}

async function doPreview() {
  busy.value = true; importErr.value = ''; result.value = null
  try { preview.value = await api.importJlq(payload.value, props.subjectId, false) }
  catch (e: any) { importErr.value = String(e.message ?? e) }
  finally { busy.value = false }
}
async function doImport() {
  busy.value = true; importErr.value = ''; preview.value = null
  try {
    result.value = await api.importJlq(payload.value, props.subjectId, true, replace.value)
    await load()
  } catch (e: any) { importErr.value = String(e.message ?? e) }
  finally { busy.value = false }
}
const counts = ref({ total: 0, withAnswer: 0, withExplain: 0, withKp: 0 })
const err = ref('')

// ---- 手机访问 ----
const net = ref<NetInfo | null>(null)
const picked = ref('')
const copied = ref(false)
const qrUrl = computed(() =>
  picked.value ? `/api/net/qr?url=${encodeURIComponent(picked.value)}&scale=4` : '')

async function loadNet() {
  try {
    net.value = await api.netInfo()
    picked.value = net.value.urls[0] ?? ''
  } catch { /* 拿不到就不显示这张卡 */ }
}
async function copyUrl() {
  try {
    await navigator.clipboard.writeText(picked.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1600)
  } catch { copied.value = false }
}

async function load() {
  try {
    await loadNet()
    docs.value = await api.documents({ subject_id: props.subjectId })
    const qs = await api.questions({ subject_id: props.subjectId, limit: 5000 })
    counts.value = {
      total: qs.length,
      withAnswer: qs.filter(q => (q.answer ?? '').trim()).length,
      withExplain: qs.filter(q => (q.explanation ?? '').trim()).length,
      withKp: qs.filter(q => q.kp_id).length,
    }
  } catch (e: any) { err.value = String(e.message ?? e) }
}
onMounted(load)
</script>

<template>
  <h1>资料库</h1>
  <p class="muted" v-if="err">接口未就绪：{{ err }}</p>

  <div class="grid c3" v-if="counts.total">
    <div class="card kpi"><div class="v">{{ counts.total }}</div><div class="k">题目总数</div></div>
    <div class="card kpi"><div class="v">{{ counts.withAnswer }}</div><div class="k">有答案</div></div>
    <div class="card kpi"><div class="v">{{ counts.withExplain }}</div><div class="k">有解析</div></div>
    <div class="card kpi"><div class="v">{{ counts.withKp }}</div><div class="k">已挂考点</div></div>
  </div>

  <h2>手机访问</h2>
  <div class="card" v-if="net">
    <template v-if="net.lan_enabled">
      <p class="muted" style="margin-top:0">
        用手机扫下面这个码，或者手动输入地址。手机要和这台电脑连同一个 WiFi。
      </p>
      <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start">
        <img v-if="qrUrl" :src="qrUrl" alt="扫码打开"
             style="width:150px;height:150px;border:1px solid var(--line);border-radius:10px;background:#fff" />
        <div style="flex:1;min-width:200px">
          <div class="toolbar" style="margin:0 0 8px">
            <button v-for="u in net.urls" :key="u" class="chip" :class="{ on: picked === u }"
                    @click="picked = u">{{ u }}</button>
          </div>
          <div class="toolbar" style="margin:0">
            <button class="btn mini" @click="copyUrl">{{ copied ? '已复制' : '复制地址' }}</button>
            <a class="btn ghost mini" :href="picked" target="_blank" rel="noreferrer">本机打开</a>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="note warn" style="margin-top:0">{{ net.hint_bound_local_only }}</div>

    <details style="margin-top:12px">
      <summary class="muted" style="cursor:pointer">手机打不开？看这里</summary>
      <p class="muted">{{ net.hint_firewall }}</p>
      <p class="muted">{{ net.hint_isolation }}</p>
    </details>
  </div>

  <h2>导入教材或习题册</h2>
  <details v-if="createSubject" class="card">
    <summary>新建学科</summary>
    <form class="toolbar" @submit.prevent="addSubject">
      <label>学科名称 <input v-model="newSubject" maxlength="128" :disabled="creating" /></label>
      <button class="btn" :disabled="creating || !newSubject.trim()">{{ creating ? '正在创建…' : '新建并切换' }}</button>
    </form>
    <p v-if="subjectErr" role="alert" class="note bad">{{ subjectErr }}</p>
  </details>
  <MaterialImport :subject-id="subjectId" @imported="load" />

  <h2 v-if="isMilitary">导入刷题记录</h2>
  <div class="card" v-if="isMilitary">
    <p class="muted" style="margin-top:0">
      把参考站（zhongshanjunli）的刷题记录导进来，你的错题本和备考建议才会用真实数据。
    </p>
    <div class="note warn">
      <b>怎么取数据：</b>在电脑上打开参考站 →
      按 <b>F12</b> → Console 里执行 <code>copy(localStorage.getItem('jlq_v1'))</code> →
      粘贴到下面的框。<br>
      <span class="muted">（信息最全，含答题历史与心得。也可以直接粘贴点「导出」下载的 .txt，但只要错题和收藏。）</span>
    </div>
    <textarea v-model="payload" rows="5"
              style="width:100%;margin-top:10px;font-family:ui-monospace,monospace;font-size:12.5px;border:1px solid var(--line);border-radius:10px;padding:10px"
              placeholder='{"answers": {...}, "wrong": {...}, "fav": {...}, "notes": {...}}'></textarea>
    <div class="toolbar" style="margin:10px 0 0">
      <button class="btn ghost mini" :disabled="busy || !payload.trim()" @click="doPreview">预览</button>
      <button class="btn mini" :disabled="busy || !payload.trim()" @click="doImport">{{ busy ? '处理中…' : '导入' }}</button>
      <label class="muted" style="display:flex;align-items:center;gap:5px;cursor:pointer">
        <input type="checkbox" v-model="replace" /> 先清空已有记录
      </label>
      <span style="flex:1"></span>
      <span class="muted" v-if="preview">
        识别为 <b>{{ preview.format === 'json' ? 'jlq_v1 JSON' : '导出文本' }}</b>：
        <span v-for="(v, k) in preview.counts" :key="k" style="margin-right:8px">{{ k }} {{ v }} 条</span>
      </span>
    </div>
    <div class="note bad" v-if="importErr" style="margin-top:10px">{{ importErr }}</div>
    <div class="note ok" v-if="result" style="margin-top:10px">
      导入完成：作答 {{ result.answered }} 条（对 {{ result.correct }} / 错 {{ result.wrong }}）·
      收藏 {{ result.fav }} · 心得 {{ result.notes }} ·
      未匹配 {{ result.unmatched }}
    </div>
  </div>

  <h2>资料（{{ docs.length }} 份）</h2>
  <div class="card">
    <div class="tscroll">
<table>
      <thead><tr><th>资料</th><th>类型</th><th>来源</th><th>年份</th><th>状态</th></tr></thead>
      <tbody>
        <tr v-for="d in docs" :key="d.id">
          <td>{{ d.title }}</td>
          <td class="muted">{{ d.doc_type }}</td>
          <td><span class="tag" :class="d.source_type === 'real_exam' ? 'warn' : 'grey'">{{ d.source_type }}</span></td>
          <td class="muted">{{ d.year || '—' }}</td>
          <td class="muted">{{ d.status }}</td>
        </tr>
      </tbody>
    </table>
      </div>
  </div>
</template>
