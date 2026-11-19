'use strict'
const questions = [
  {id: 1, subject: '自然科学', stem: '哪种情况最容易在纸上看到清晰的影子？', choices: ['用手电照射不透明挡板，把纸放在挡板后', '关闭光源，只保留纸和挡板', '把纸放在手电与挡板之间'], answer: 0, note: '挡板阻止一部分光到达纸面。纸在挡板背光侧时，才容易看到由挡板产生的影子。'},
  {id: 2, subject: '自然科学', stem: '在水中溶解的盐还能通过什么办法取回？', choices: ['用滤纸过滤盐水', '让水蒸发', '让盐水静置片刻'], answer: 1, note: '盐溶解后不能用普通滤纸分离。水蒸发后，盐会留在容器内。'},
  {id: 3, subject: '自然科学', stem: '取两张一样湿的纸，哪张通常干得更快？', choices: ['揉成团放在桌上', '放进密封袋中', '摊开并放在通风处'], answer: 2, note: '摊开增大与空气接触的面积，通风带走纸面附近的水汽，两者都能加快蒸发。'},
  {id: 4, subject: '数学', stem: '两本同价笔记本一共 18 元，买三本需要多少元？', choices: ['24 元', '27 元', '36 元'], answer: 1, note: '先算每本的价格：18 ÷ 2 = 9 元，再算三本：9 × 3 = 27 元。'},
  {id: 5, subject: '数学', stem: '一个长方形长 7 厘米、宽 4 厘米，它的周长是多少？', choices: ['11 厘米', '28 厘米', '22 厘米'], answer: 2, note: '周长是四条边长度之和，即 2 × (7 + 4) = 22 厘米。28 平方厘米是面积。'},
  {id: 6, subject: '数学', stem: '甲杯喝去原有水量的 1/2，乙杯喝去原有水量的 1/3。能确定哪杯喝得更多吗？', choices: ['不能，需要知道两杯原有水量', '一定是甲杯', '一定是乙杯'], answer: 0, note: '分数必须乘以各自的原有水量。原有水量不一定相等，不能只比较分数。'}
]
const $ = id => document.getElementById(id)
const storageKey = 'titi-quiz.pages-demo.v1'
let progress = {}
try {
  const cached = JSON.parse(localStorage.getItem(storageKey))
  for (const q of questions) if (typeof cached?.[q.id] === 'boolean') progress[q.id] = cached[q.id]
} catch {}
let mode = 'all', ids = [], index = 0, marked = false
const scoped = q => $('subject').value === 'all' || $('subject').value === q.subject
const wrongCount = () => questions.filter(q => scoped(q) && progress[q.id] === false).length
function stats() {
  const results = Object.values(progress)
  $('done').textContent = results.length
  $('correct').textContent = results.length ? Math.round(100 * results.filter(Boolean).length / results.length) + '%' : '—'
  $('wrong').textContent = '错题本（' + wrongCount() + '）'
  for (const name of ['all', 'wrong']) $(name).setAttribute('aria-pressed', String(name === mode))
}
function render(focus = false) {
  stats()
  const q = ids[index]
  $('question').hidden = !q
  $('empty').hidden = Boolean(q)
  if (!q) return
  marked = false
  $('category').textContent = q.subject
  $('position').textContent = (index + 1) + ' / ' + ids.length + ' · 单选'
  $('stem').textContent = q.stem
  const field = $('options')
  field.disabled = false
  field.querySelectorAll('label').forEach(x => x.remove())
  q.choices.forEach((choice, i) => {
    const label = document.createElement('label')
    label.className = 'option'
    const input = document.createElement('input')
    input.type = 'radio'
    input.name = 'answer'
    input.value = i
    label.append(input, document.createTextNode(choice))
    field.append(label)
  })
  $('submit').disabled = true
  $('feedback').hidden = true
  $('next').textContent = index === ids.length - 1 ? '回到第一题' : '下一题'
  if (focus) $('stem').focus()
}
function switchMode(next) {
  mode = next
  ids = questions.filter(q => scoped(q) && (mode === 'all' || progress[q.id] === false))
  index = 0
  render()
}
$('all').onclick = $('back').onclick = () => switchMode('all')
$('wrong').onclick = () => switchMode('wrong')
$('subject').onchange = () => switchMode(mode)
$('form').onchange = () => { if (!marked) $('submit').disabled = false }
$('form').onsubmit = event => {
  event.preventDefault()
  const q = ids[index], input = $('form').querySelector('input:checked')
  if (!input || marked || !q) return
  const chosen = Number(input.value), correct = chosen === q.answer
  progress[q.id] = correct
  try { localStorage.setItem(storageKey, JSON.stringify(progress)) } catch {}
  marked = true
  $('submit').disabled = true
  $('options').disabled = true
  const labels = $('options').querySelectorAll('label')
  labels[q.answer].classList.add('good')
  if (!correct) labels[chosen].classList.add('bad')
  const summary = document.createElement('strong')
  summary.textContent = correct ? '回答正确' : '答错了 · 已加入错题本'
  const paragraph = document.createElement('p')
  paragraph.textContent = '正确答案：' + q.choices[q.answer] + '。' + q.note
  $('feedback').replaceChildren(summary, paragraph)
  $('feedback').hidden = false
  stats()
  if (mode === 'wrong' && correct) $('next').textContent = '查看剩余错题'
}
$('next').onclick = () => {
  if (mode === 'wrong' && marked && progress[ids[index].id] === true) {
    ids.splice(index, 1)
    if (index >= ids.length) index = 0
  } else {
    index = (index + 1) % ids.length
  }
  render(true)
}
switchMode('all')

