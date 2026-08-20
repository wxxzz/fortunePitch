<script setup lang="ts">
/**
 * 右侧抽屉(Quick Panel):悬浮展示进行中的滚球赛事与核心赔率变化,
 * 支持一键跳转到赛事深度分析页。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useMatchStore } from '@/stores/match'

interface Props {
  isOpen: boolean
}

defineProps<Props>()
const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const matchStore = useMatchStore()
const { games } = storeToRefs(matchStore)

/** 进行中的滚球赛事 */
const liveGames = computed(() => games.value.filter((g) => g.match_status === 'LIVE'))

function handleJump(matchId: string): void {
  emit('close')
  void router.push(`/match/${matchId}`)
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="quick-panel__mask"
      @click="emit('close')"
    />
    <aside
      class="quick-panel"
      :class="{ 'quick-panel--open': isOpen }"
      aria-label="滚球快讯"
    >
      <header class="quick-panel__header">
        <h3 class="quick-panel__title">滚球快讯</h3>
        <button type="button" class="quick-panel__close" @click="emit('close')">✕</button>
      </header>

      <div class="quick-panel__body">
        <p v-if="liveGames.length === 0" class="quick-panel__empty">
          当前没有进行中的比赛
        </p>
        <button
          v-for="game in liveGames"
          :key="game.match_id"
          type="button"
          class="quick-panel__item"
          @click="handleJump(game.match_id)"
        >
          <div class="quick-panel__item-top">
            <span class="quick-panel__match-id">{{ game.match_id }}</span>
            <span
              v-if="game.home_score !== null"
              class="quick-panel__score"
            >
              {{ game.home_score }} : {{ game.away_score }}
            </span>
          </div>
          <span class="quick-panel__jump">查看深度分析 →</span>
        </button>
      </div>

      <footer class="quick-panel__footer">
        赔率变化数据源接入后在此展示实时水位
      </footer>
    </aside>
  </Teleport>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.quick-panel {
  position: fixed;
  top: 0;
  right: 0;
  z-index: 100;
  display: flex;
  flex-direction: column;
  width: 320px;
  height: 100vh;
  background: vars.$color-surface;
  border-left: 1px solid vars.$color-border;
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.12);
  transform: translateX(100%);
  transition: transform 0.25s ease;

  &--open {
    transform: translateX(0);
  }

  &__mask {
    position: fixed;
    inset: 0;
    z-index: 99;
    background: rgba(0, 0, 0, 0.2);
  }

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: vars.$spacing-md vars.$spacing-lg;
    border-bottom: 1px solid vars.$color-border;
  }

  &__title {
    margin: 0;
    font-size: vars.$font-size-md;
  }

  &__close {
    border: none;
    background: transparent;
    color: vars.$color-text-secondary;
    cursor: pointer;
  }

  &__body {
    flex: 1;
    overflow-y: auto;
    padding: vars.$spacing-md;
  }

  &__item {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
    width: 100%;
    margin-bottom: vars.$spacing-sm;
    padding: vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-bg;
    text-align: left;
    cursor: pointer;

    &:hover {
      border-color: vars.$color-primary;
    }
  }

  &__item-top {
    display: flex;
    justify-content: space-between;
  }

  &__match-id {
    font-weight: 600;
  }

  &__score {
    color: vars.$color-positive;
    font-weight: 700;
  }

  &__jump {
    font-size: vars.$font-size-sm;
    color: vars.$color-primary;
  }

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
    padding: vars.$spacing-lg 0;
  }

  &__footer {
    padding: vars.$spacing-md vars.$spacing-lg;
    border-top: 1px solid vars.$color-border;
    font-size: 11px;
    color: vars.$color-text-secondary;
  }
}
</style>
