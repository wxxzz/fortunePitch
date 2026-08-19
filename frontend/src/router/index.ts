import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/match',
    },
    {
      path: '/base',
      name: 'base-data',
      component: () => import('@/views/base/BaseDataView.vue'),
    },
    {
      path: '/match',
      name: 'match-center',
      component: () => import('@/views/match/MatchCenterView.vue'),
    },
    {
      path: '/analytics',
      name: 'analytics',
      component: () => import('@/views/analytics/AnalyticsView.vue'),
    },
    {
      path: '/strategy',
      name: 'strategy',
      component: () => import('@/views/strategy/StrategyView.vue'),
    },
  ],
})

export default router
