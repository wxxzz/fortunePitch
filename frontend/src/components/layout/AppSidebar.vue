<script setup lang="ts">
/**
 * 左侧导航栏(Sidebar):深色背景,提供五大全局入口。
 * 底部保留基础档案管理入口(数据维护用)。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()

const NAV_ITEMS = [
  { label: '赛事中心', route: '/match', icon: '⚽' },
  { label: '球队档案', route: '/teams', icon: '🛡' },
  { label: '策略推荐', route: '/strategy', icon: '📈' },
  { label: '数据模型', route: '/model', icon: '🧮' },
  { label: '我的复盘', route: '/retrospect', icon: '📒' },
] as const

const activeRoute = computed(() => route.path)

function handleNavigate(path: string): void {
  void router.push(path)
}
</script>

<template>
  <aside class="app-sidebar" aria-label="全局导航">
    <div class="app-sidebar__brand">
      <span class="app-sidebar__logo">FP</span>
      <div class="app-sidebar__brand-text">
        <strong>FortunePitch</strong>
        <span>财富绿茵 · 数据分析</span>
      </div>
    </div>

    <nav class="app-sidebar__nav">
      <button
        v-for="item in NAV_ITEMS"
        :key="item.route"
        type="button"
        class="app-sidebar__item"
        :class="{ 'app-sidebar__item--active': activeRoute === item.route }"
        @click="handleNavigate(item.route)"
      >
        <span class="app-sidebar__icon">{{ item.icon }}</span>
        {{ item.label }}
      </button>
    </nav>

    <div class="app-sidebar__footer">
      <button
        type="button"
        class="app-sidebar__item app-sidebar__item--minor"
        @click="handleNavigate('/collector')"
      >
        数据采集
      </button>
      <button
        type="button"
        class="app-sidebar__item app-sidebar__item--minor"
        @click="handleNavigate('/base')"
      >
        基础档案管理
      </button>
      <p class="app-sidebar__compliance">
        仅提供数据分析,不构成投注建议
      </p>
    </div>
  </aside>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.app-sidebar {
  display: flex;
  flex-direction: column;
  width: vars.$sidebar-width;
  flex-shrink: 0;
  background: vars.$color-sidebar-bg;
  color: vars.$color-sidebar-text;

  &__brand {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    padding: vars.$spacing-md vars.$spacing-lg;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  }

  &__logo {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: 8px;
    background: vars.$color-primary;
    color: #fff;
    font-weight: 700;
  }

  &__brand-text {
    display: flex;
    flex-direction: column;
    line-height: 1.3;

    strong {
      color: #fff;
    }

    span {
      font-size: 11px;
    }
  }

  &__nav {
    display: flex;
    flex-direction: column;
    padding: vars.$spacing-sm 0;
    gap: 2px;
  }

  &__item {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    padding: vars.$spacing-sm vars.$spacing-lg;
    border: none;
    border-left: 3px solid transparent;
    background: transparent;
    color: inherit;
    font-size: vars.$font-size-md;
    text-align: left;
    cursor: pointer;
    transition: background-color 0.15s ease;

    &:hover {
      background: rgba(255, 255, 255, 0.05);
      color: #fff;
    }

    &--active {
      background: vars.$color-sidebar-active-bg;
      border-left-color: vars.$color-primary;
      color: vars.$color-sidebar-text-active;
      font-weight: 600;
    }

    &--minor {
      font-size: vars.$font-size-sm;
      opacity: 0.75;
    }
  }

  &__footer {
    margin-top: auto;
    padding: vars.$spacing-md vars.$spacing-lg;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
  }

  &__compliance {
    margin: vars.$spacing-sm 0 0;
    font-size: 11px;
    opacity: 0.6;
    line-height: 1.4;
  }
}
</style>
