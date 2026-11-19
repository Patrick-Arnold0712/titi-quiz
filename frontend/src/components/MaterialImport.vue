<script setup lang="ts">
import { ref } from 'vue'
import { api, type MaterialDraft, type MaterialReport } from '@/api'

const props = defineProps<{ subjectId: number }>()
const emit = defineEmits<{ imported: [] }>()
const kind = ref<'textbook' | 'workbook'>('workbook')
const file = ref<File>()
const force = ref(false)
const draft = ref<MaterialDraft>()
const report = ref<MaterialReport>()
const page = ref(0)
const chapter = ref('')
const makePaper = ref(true)
const edited = ref(false)
const busy = ref('')
const error = ref('')
const success = ref('')

function reset() {
  draft.value = undefined; report.value = undefined; error.value = ''; success.value = ''
}
function pick(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0]
  reset()
}
async function run(action: string, fn: () => Promise<void>) {
  busy.value = action; error.value = ''; success.value = ''
  try { await fn() }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = '' }
}
async function preview() {
  if (!file.value) return
  const selected = file.value
  reset()
  await run('正在上传并识别资料，整本扫描教材可能需要较长时间，请保持页面打开…', async () => {
    const result = await api.previewMaterial(selected, props.subjectId, kind.value, force.value)
    draft.value = result; report.value = result; page.value = 0; edited.value = false
  })
}
function payload(d: MaterialDraft) {
  return { pages: d.pages, chapter: chapter.value.trim(), make_paper: makePaper.value }
}
async function check() {
  const d = draft.value
  if (!d) return
  await run('正在检查…', async () => {
    report.value = await api.checkMaterial(d.draft_id, payload(d))
    edited.value = false
  })
}
async function commit() {
  const d = draft.value
  if (!d || edited.value) return
  await run('正在入库…', async () => {
    const result = await api.commitMaterial(d.draft_id, payload(d))
    draft.value = undefined; report.value = undefined
    success.value = result.already_imported
      ? '同一学科已导入过这份资料，本次未新增。'
      : `已入库：${result.chunk_count} 个文本块、${result.question_count} 道新题；跳过 ${result.skipped} 道待修正题、${result.duplicates} 道重复题。`
    if (result.paper_id && !result.already_imported) success.value += ' 练习卷已加入试卷库。'
    emit('imported')
  })
}
</script>

<template>
  <section class="card material" aria-label="分科导入资料">
    <p class="muted">资料会导入顶部选中的学科。PDF 最多 256 MiB、1,000 页；DOCX、TXT、Markdown 和常用图片最多 30 MiB。OCR 在本机运行，不上传到第三方。</p>
    <div class="grid c2">
      <label>资料类型
        <select v-model="kind" :disabled="!!busy" @change="reset">
          <option value="workbook">习题册：识别题目和答案</option>
          <option value="textbook">教材：建立章节和原文索引</option>
        </select>
      </label>
      <label>选择资料
        <input type="file" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.bmp,.webp" :disabled="!!busy" @change="pick">
      </label>
    </div>
    <div class="toolbar">
      <label class="check"><input v-model="force" type="checkbox" :disabled="!!busy" @change="reset"> PDF 每页强制 OCR（较慢）</label>
      <button class="btn" :disabled="!!busy || !file" @click="preview">识别并预览</button>
    </div>
    <p class="muted">PDF 建议先不勾选强制 OCR，系统会优先读取文字层，并自动识别少字的扫描页。文字层乱码时再开启。</p>
    <details v-if="kind === 'workbook'">
      <summary>习题识别与校对格式</summary>
      <p class="muted">题干用「1.」等题号起行，选项用「A.」「B.」，题后写「答案：A」。也可在末尾用「参考答案」标题和独立的「1. A」答案行，题号须唯一。判断、填空和主观题请加题型标题。</p>
    </details>
    <div v-if="draft && report" class="review">
      <h3>校对后入库</h3>
      <p class="muted">{{ draft.filename }} · {{ draft.pages.length }} 页/段 · OCR {{ draft.ocr_pages.length }} 页</p>
      <div v-if="kind === 'workbook'" aria-live="polite">
        <p v-if="edited" class="muted">文字已改动，请重新检查后再入库。</p>
        <template v-else>
          <p>识别到 {{ report.candidate_count }} 题，可入库 {{ report.usable_count }} 题，待修正 {{ report.invalid_count }} 题。</p>
          <details v-if="report.issues.length">
            <summary>待修正原因（最多显示前 30 题，不入库）</summary>
            <ul>
              <li v-for="(issue, i) in report.issues" :key="i">
                <button class="btn ghost mini" :disabled="!!busy" @click="page = issue.page - 1">第 {{ issue.page }} 页 · 题号 {{ issue.number }}</button>
                {{ issue.issues.join('；') }}
              </li>
            </ul>
          </details>
          <details v-if="report.sample.length">
            <summary>查看前 {{ report.sample.length }} 道可入库样题</summary>
            <ul>
              <li v-for="(q, i) in report.sample" :key="i">{{ q.stem }}
                <div v-for="opt in q.options" :key="opt.key">{{ opt.key }}. {{ opt.text }}</div>
                <b>答案：{{ q.answer }}</b>
              </li>
            </ul>
          </details>
        </template>
      </div>
      <label v-if="draft.pages.length > 1">校对页码
        <select v-model.number="page" :disabled="!!busy">
          <option v-for="(_, index) in draft.pages" :key="index" :value="index">第 {{ index + 1 }} 页</option>
        </select>
      </label>
      <label>第 {{ page + 1 }} 页提取文字
        <textarea v-model="draft.pages[page]" rows="9" :disabled="!!busy" @input="edited = true"></textarea>
      </label>
      <label>指定章节（可选，填写后将整份归到该章节）
        <input v-model="chapter" type="text" maxlength="120" :disabled="!!busy" placeholder="不填则按标题识别">
      </label>
      <div class="toolbar">
        <label v-if="kind === 'workbook'" class="check"><input v-model="makePaper" type="checkbox" :disabled="!!busy"> 同时生成练习卷（不含填空题）</label>
      </div>
      <div class="toolbar">
        <button class="btn ghost" :disabled="!!busy" @click="check">重新检查</button>
        <button class="btn" :disabled="!!busy || edited || (kind === 'workbook' && !report.usable_count)" @click="commit">确认入库</button>
      </div>
    </div>
    <p v-if="busy" role="status" class="muted">{{ busy }}</p>
    <div v-if="error" role="alert" class="note bad">{{ error }}</div>
    <div v-if="success" role="status" class="note ok">{{ success }}</div>
  </section>
</template>

<style scoped>
.material { overflow-wrap: anywhere; }
.material p:first-child { margin-top: 0; }
label { display: grid; gap: 4px; min-width: 0; }
input:not([type=checkbox]), select, textarea {
  width: 100%; min-width: 0; font: inherit; color: var(--ink);
  padding: 8px; border: 1px solid var(--line); border-radius: 8px;
}
textarea { resize: vertical; }
.check { display: flex; align-items: center; gap: 8px; min-height: 44px; }
.btn { min-height: 44px; }
.review { border-top: 1px solid var(--line); margin-top: 16px; padding-top: 12px; }
.review > label, details, li { margin-top: 8px; }
</style>
