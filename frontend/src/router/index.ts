import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'match-center',
      component: () => import('@/views/MatchCenterView.vue'),
    },
    {
      path: '/retrospect',
      name: 'retrospect-center',
      component: () => import('@/views/RetrospectCenterView.vue'),
    },
  ],
})

export default router
