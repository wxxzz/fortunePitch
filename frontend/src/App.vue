<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

const NAV_ITEMS = [
  { label: '基础档案', route: '/base' },
  { label: '赛事中心', route: '/match' },
  { label: '数据分析', route: '/analytics' },
  { label: '策略与赔率', route: '/strategy' },
] as const
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="app-header__brand">
        <h1 class="app-header__title">FortunePitch</h1>
        <span class="app-header__subtitle">财富绿茵 · 数据分析辅助工具</span>
      </div>
      <nav class="app-header__nav" aria-label="主导航">
        <button
          v-for="item in NAV_ITEMS"
          :key="item.route"
          type="button"
          class="app-header__nav-btn"
          :class="{ 'app-header__nav-btn--active': router.currentRoute.value.path === item.route }"
          @click="router.push(item.route)"
        >
          {{ item.label }}
        </button>
      </nav>
    </header>
    <main class="app-main">
      <RouterView />
    </main>
    <footer class="app-footer">
      <p>FortunePitch 仅提供基于公开数据的量化分析,不构成任何投注建议,请理性看待分析结果。</p>
    </footer>
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: vars.$spacing-md vars.$spacing-lg;
  border-bottom: 1px solid vars.$color-border;

  &__title {
    margin: 0;
    font-size: vars.$font-size-lg;
    color: vars.$color-primary;
  }

  &__subtitle {
    margin-left: vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__nav-btn {
    margin-left: vars.$spacing-sm;
    padding: vars.$spacing-xs vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: transparent;
    color: vars.$color-text-primary;
    cursor: pointer;
    transition: background-color 0.2s ease;

    &:hover {
      background-color: vars.$color-surface-hover;
    }

    &--active {
      background-color: vars.$color-primary;
      border-color: vars.$color-primary;
      color: #fff;
    }
  }
}

.app-main {
  flex: 1;
  padding: vars.$spacing-lg;
}

.app-footer {
  padding: vars.$spacing-md vars.$spacing-lg;
  border-top: 1px solid vars.$color-border;
  font-size: vars.$font-size-sm;
  color: vars.$color-text-secondary;
  text-align: center;
}
</style>
