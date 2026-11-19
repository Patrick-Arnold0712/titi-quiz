<script setup lang="ts">
import { computed } from 'vue'

/**
 * 长文阅读组件：逐句分行 + 重点标注。
 *
 * 为什么不用后端标注：这是纯展示问题，规则可能随复习习惯调整，
 * 放前端改完刷新即可，不用动接口。
 *
 * 标注规则只挑**客观、低误报**的模式 —— 年份、书名号、序数、引号专有名词。
 * 试过拿「注意/关键」当规则，教材里这些词多是普通用法（「注意激励军队的士气」），
 * 标出来全是噪声，反而干扰阅读。
 */

const RE = new RegExp([
  // 1 年份 / 完整日期
  '((?:19|20)\\d{2}\\s*年(?:\\s*\\d{1,2}\\s*月)?(?:\\s*\\d{1,2}\\s*日)?)',
  // 2 书名号：法律、著作、文件
  '(《[^》]{1,30}》)',
  // 3 序数：第一个 / 第三次 / 第五艘
  '(第[一二三四五六七八九十百千0-9]+(?:个|次|位|颗|枚|艘|架|名|届|任|种|类|阶段|时期))',
  // 4 数量：三大 / 四项 / 两条 / 十个方面
  '([一二三四五六七八九十两]+(?:大|项|条|种|类|方面|原则|要素|特征|阶段))',
  // 5 具体数字带单位：1.8万千米 / 3000多万
  '(\\d+(?:\\.\\d+)?\\s*(?:万|亿)?\\s*(?:千米|公里|平方千米|年|个月|小时|万人|亿美元|万吨|马赫|米))',
  // 6 引号里的专有名词：“两弹一星”“岛链”
  '(“[^”]{1,24}”)',
  // 7 结论 / 定义标志词 —— 只标词不标整句，避免整段变色
  '((?:是指|指的是|标志着|被誉为|被称为|核心是|本质是|前提是|基础是|关键是|决定了|取决于))',
].join('|'), 'g')

const CLASSES = ['date', 'doc', 'num', 'num', 'num', 'term', 'key']

const ESC: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;' }
const esc = (s: string) => s.replace(/[&<>]/g, c => ESC[c])

function render(line: string): string {
  const out: string[] = []
  let last = 0
  RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = RE.exec(line)) !== null) {
    if (!m[0]) { RE.lastIndex++; continue }
    if (m.index > last) out.push(esc(line.slice(last, m.index)))
    const gi = m.slice(1).findIndex(x => x !== undefined)
    out.push(`<mark class="${CLASSES[gi] ?? 'key'}">${esc(m[0])}</mark>`)
    last = m.index + m[0].length
  }
  if (last < line.length) out.push(esc(line.slice(last)))
  return out.join('')
}

const props = withDefaults(defineProps<{ text?: string | null; sentence?: boolean }>(), {
  sentence: true,
})

// 先把 PDF 的「硬换行」接回去。
//
// 教材 chunk 是从 PDF 抽的，每一行原样带着一个 \n —— 那是排版换行，不是段落分隔。
// 直接按 \n 切，就会出现「每行一段、右边空一大块」的怪样子（第一版就是这个毛病）。
// 规则：行末不是句末标点的，说明只是折行，把换行删掉；是句末标点的才当分段。
function reflow(t: string): string {
  return t
    .replace(/\r/g, '')
    .split('\n')
    .map(l => l.replace(/[ \t]+$/g, ''))
    .join('\n')
    .replace(/([^。！？；\n])\n+/g, '$1')
    .replace(/\n+/g, '\n')
}

// 逐句分行：中文长段落最难扫，一句一行之后眼睛有落点
const lines = computed(() => {
  const raw = reflow((props.text ?? '').trim())
  if (!raw) return []
  const out: string[] = []
  for (const para of raw.split(/\n+/)) {
    const p = para.trim()
    if (!p) continue
    if (!props.sentence) { out.push(render(p)); continue }
    for (const s of p.match(/[^。！？；]*[。！？；]|[^。！？；]+$/g) ?? [p]) {
      const t = s.trim()
      if (t) out.push(render(t))
    }
  }
  return out
})
</script>

<template>
  <div class="rt">
    <p v-for="(l, i) in lines" :key="i" v-html="l"></p>
  </div>
</template>
