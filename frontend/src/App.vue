<script setup lang="ts">
import { computed, onMounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type Subject } from '@/api'

const route = useRoute()
const router = useRouter()

const allNavItems = computed(() =>
  router.getRoutes().filter(r => r.meta?.title && !r.meta?.hidden)
    .sort((a, b) => (a.meta!.order as number ?? 99) - (b.meta!.order as number ?? 99)),
)
const current = computed(() => route.name as string)

const subjects = ref<Subject[]>([])
const subjectId = ref(1)
const active = computed(() => subjects.value.find(s => s.id === subjectId.value))

// 主观题背诵清单是军理专用；其他学科的试卷入口只展示本学科练习卷。
const navItems = computed(() => {
  const code = active.value?.code
  const hidden = code && code !== 'military_theory' ? new Set(['subjective']) : new Set<string>()
  return allNavItems.value.filter(r => !hidden.has(r.name as string))
})

provide('subjectCode', computed(() => active.value?.code ?? ''))
provide('createSubject', async (name: string) => {
  if (subjects.value.some(s => s.name === name)) throw new Error('学科名称已存在')
  const subject = await api.createSubject(name)
  subjects.value = [...subjects.value, subject]
  subjectId.value = subject.id
})
const navTitle = (name: unknown, title: unknown) =>
  name === 'papers' && active.value?.code !== 'military_theory' ? '练习卷' : title

onMounted(async () => {
  try {
    subjects.value = await api.subjects()
    let saved = 1
    try { saved = Number(localStorage.getItem('ttk.subject') || 1) } catch { /* 隐私模式无妨 */ }
    subjectId.value = subjects.value.some(s => s.id === saved)
      ? saved
      : (subjects.value[0]?.id ?? 1)
  } catch { /* 后端未启动时保持默认学科，页面自己会提示 */ }
})

watch(subjectId, (id) => {
  try { localStorage.setItem('ttk.subject', String(id)) } catch { /* ignore */ }
  if (navItems.value.length && !navItems.value.some(n => n.name === current.value)) {
    router.push({ name: 'overview' })
  }
})
</script>

<template>
  <header class="top">
    <div class="inner">
      <div class="brand">
        <span class="logo">题</span>
        题题的库
        <em>{{ active?.name ?? '题库' }}</em>
      </div>
      <nav class="topnav">
        <button v-for="n in navItems" :key="n.name as string"
                :class="{ on: current === n.name }"
                @click="router.push({ name: n.name as string })">
          {{ n.meta!.icon }} {{ navTitle(n.name, n.meta!.title) }}
        </button>
      </nav>
      <div class="spacer"></div>
      <select v-if="subjects.length > 1" v-model.number="subjectId" class="subject-pick" aria-label="选择学科">
        <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <span class="pill">{{ active?.exam_name ?? '多学科题库' }}</span>
    </div>
  </header>

  <main class="wrap">
    <router-view :subject-id="subjectId" :key="subjectId" />
  </main>

  <nav class="bnav">
    <div class="inner">
      <button v-for="n in navItems" :key="n.name as string"
              :class="{ on: current === n.name }"
              @click="router.push({ name: n.name as string })">
        <span class="ic">{{ n.meta!.icon }}</span>
        <span>{{ navTitle(n.name, n.meta!.title) }}</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.subject-pick {
  background: #fff; color: var(--ink); border: 0; border-radius: 8px;
  padding: 5px 8px; font-size: 12.5px; max-width: 190px;
}
</style>
