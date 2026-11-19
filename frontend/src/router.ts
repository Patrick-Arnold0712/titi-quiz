import { createRouter, createWebHashHistory } from 'vue-router'

// 用 hash 模式：构建产物由 FastAPI 静态托管，无需服务端 rewrite 规则
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', name: 'overview', meta: { title: '概览', icon: '◎', order: 0 }, component: () => import('./views/OverviewView.vue') },
    { path: '/practice', name: 'practice', meta: { title: '刷题', icon: '✎', order: 1 }, component: () => import('./views/PracticeView.vue') },
    { path: '/papers', name: 'papers', meta: { title: '押题卷', icon: '▤', order: 2 }, component: () => import('./views/PapersView.vue') },
    { path: '/wrong', name: 'wrong', meta: { title: '错题本', icon: '✗', order: 3 }, component: () => import('./views/WrongView.vue') },
    { path: '/graph', name: 'graph', meta: { title: '考点图谱', icon: '⧉', order: 4 }, component: () => import('./views/GraphView.vue') },
    { path: '/advice', name: 'advice', meta: { title: '备考建议', icon: '◆', order: 5 }, component: () => import('./views/AdviceView.vue') },
    // 简答 / 论述的考前背诵清单。导航里刻意叫「简答」两个字 ——
    // 底部导航已经 8 个入口，三字标签在 390px 宽的屏上会挤。
    { path: '/subjective', name: 'subjective', meta: { title: '简答', icon: '✍', order: 6 }, component: () => import('./views/SubjectiveView.vue') },
    { path: '/bits', name: 'bits', meta: { title: '搜索', icon: '⌕', order: 7 }, component: () => import('./views/BitsView.vue') },
    { path: '/library', name: 'library', meta: { title: '资料库', icon: '☰', order: 8 }, component: () => import('./views/LibraryView.vue') },
    { path: '/exam/:id', name: 'exam', meta: { title: '答题卡', hidden: true }, component: () => import('./views/ExamView.vue') },
    { path: '/review/:id', name: 'review', meta: { title: '试卷回看', hidden: true }, component: () => import('./views/ReviewView.vue') },
  ],
})
