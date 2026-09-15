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
      path: '/base/team-dashboard/:teamId',
      name: 'team-dashboard',
      component: () => import('@/views/base/TeamDashboardView.vue'),
    },
    {
      path: '/collector',
      name: 'collector',
      component: () => import('@/views/collector/CollectorView.vue'),
    },
    {
      path: '/match',
      name: 'match-center',
      component: () => import('@/views/match/MatchCenterView.vue'),
    },
    {
      path: '/results',
      name: 'match-results',
      component: () => import('@/views/match/MatchResultsView.vue'),
    },
    {
      path: '/match/:matchId',
      name: 'match-detail',
      component: () => import('@/views/match/MatchDetailView.vue'),
    },
    {
      path: '/teams',
      name: 'team-profile',
      component: () => import('@/views/team/TeamProfileView.vue'),
    },
    {
      path: '/strategy',
      name: 'strategy',
      component: () => import('@/views/strategy/StrategyView.vue'),
    },
    {
      path: '/model',
      name: 'data-model',
      component: () => import('@/views/model/DataModelView.vue'),
    },
    {
      path: '/retrospect',
      name: 'user-dashboard',
      component: () => import('@/views/retrospect/UserDashboardView.vue'),
    },
  ],
})

export default router
