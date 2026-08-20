<script setup lang="ts">
/**
 * 全局布局框架(App Shell):
 * 左侧深色导航栏 + 顶部状态栏 + 主内容区 + 右侧滚球抽屉。
 */
import { ref } from 'vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import TopBar from '@/components/layout/TopBar.vue'
import QuickPanel from '@/components/layout/QuickPanel.vue'

const isQuickPanelOpen = ref(false)
</script>

<template>
  <div class="app-shell">
    <AppSidebar />
    <div class="app-shell__main">
      <TopBar @toggle-panel="isQuickPanelOpen = !isQuickPanelOpen" />
      <main class="app-shell__content">
        <RouterView />
      </main>
      <footer class="app-shell__footer">
        <p>
          FortunePitch(财富绿茵)仅提供基于公开数据的量化分析与辅助决策,
          不构成任何投注建议,请理性看待分析结果。
        </p>
      </footer>
    </div>
    <QuickPanel :is-open="isQuickPanelOpen" @close="isQuickPanelOpen = false" />
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.app-shell {
  display: flex;
  min-height: 100vh;

  &__main {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
  }

  &__content {
    flex: 1;
    padding: vars.$spacing-lg;
  }

  &__footer {
    padding: vars.$spacing-md vars.$spacing-lg;
    border-top: 1px solid vars.$color-border;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    text-align: center;

    p {
      margin: 0;
    }
  }
}
</style>
