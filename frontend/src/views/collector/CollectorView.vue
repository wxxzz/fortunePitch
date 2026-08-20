<script setup lang="ts">
/**
 * 数据采集视图:从中国竞彩网联赛资料同步联赛信息。
 *
 * 当前支持按联赛名称手动触发同步(先支持西甲,其他联赛按需输入名称),
 * 同步结果幂等写入联赛档案表。
 */
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { syncLeague, type LeagueSyncResult } from '@/api/collector/league'
import { useBaseStore } from '@/stores/base'

const baseStore = useBaseStore()
const { leagues, isLoading } = storeToRefs(baseStore)

const leagueName = ref('西甲')
const isSyncing = ref(false)
const syncError = ref<string | null>(null)
const syncResult = ref<LeagueSyncResult | null>(null)

/** 快捷入口:竞彩网热门联赛简称 */
const QUICK_LEAGUES = ['西甲', '英超', '德甲', '意甲', '法甲'] as const

const canSubmit = computed(() => leagueName.value.trim().length > 0 && !isSyncing.value)

const actionText = computed(() => {
  if (syncResult.value === null) return ''
  return syncResult.value.action === 'created' ? '新建档案' : '更新档案'
})

onMounted(() => {
  void baseStore.fetchAll()
})

/** 触发联赛同步,成功后刷新联赛列表 */
async function handleSync(): Promise<void> {
  const name = leagueName.value.trim()
  if (!name || isSyncing.value) return
  isSyncing.value = true
  syncError.value = null
  syncResult.value = null
  try {
    syncResult.value = await syncLeague(name)
    await baseStore.fetchAll()
  } catch (err) {
    syncError.value = err instanceof Error ? err.message : '联赛同步失败'
  } finally {
    isSyncing.value = false
  }
}
</script>

<template>
  <section class="collector">
    <header class="collector__header">
      <h2 class="collector__title">数据采集 · 联赛同步</h2>
      <p class="collector__subtitle">
        数据来源:中国竞彩网联赛资料(sporttery.cn/zqlszl),按名称同步联赛档案,
        重复同步时更新已有记录。
      </p>
    </header>

    <div class="collector__panel">
      <div class="collector__form">
        <label class="collector__label" for="league-name-input">联赛名称</label>
        <input
          id="league-name-input"
          v-model="leagueName"
          class="collector__input"
          type="text"
          maxlength="128"
          placeholder="如:西甲"
          :disabled="isSyncing"
          @keyup.enter="handleSync"
        />
        <button
          class="collector__btn"
          type="button"
          :disabled="!canSubmit"
          @click="handleSync"
        >
          {{ isSyncing ? '同步中…' : '同步' }}
        </button>
      </div>

      <div class="collector__quick">
        <span class="collector__quick-label">快捷选择:</span>
        <button
          v-for="name in QUICK_LEAGUES"
          :key="name"
          class="collector__chip"
          :class="{ 'collector__chip--active': leagueName === name }"
          type="button"
          :disabled="isSyncing"
          @click="leagueName = name"
        >
          {{ name }}
        </button>
      </div>

      <p v-if="isSyncing" class="collector__hint">正在从竞彩网拉取联赛信息…</p>
      <p v-if="syncError" class="collector__error" role="alert">{{ syncError }}</p>

      <div v-if="syncResult" class="collector__result">
        <div class="collector__result-head">
          <span class="collector__result-badge">{{ actionText }}</span>
          <strong>{{ syncResult.league.league_name }}</strong>
          <span class="collector__result-source">来源:{{ syncResult.source }}</span>
        </div>
        <dl class="collector__result-fields">
          <div>
            <dt>国家/地区</dt>
            <dd>{{ syncResult.league.country }}</dd>
          </div>
          <div>
            <dt>级别</dt>
            <dd>{{ syncResult.league.tier === 1 ? '顶级' : '次级' }}</dd>
          </div>
          <div>
            <dt>当前赛季</dt>
            <dd>{{ syncResult.league.season }}</dd>
          </div>
          <div>
            <dt>竞彩联赛 ID</dt>
            <dd>{{ syncResult.uniform_league_id }}</dd>
          </div>
        </dl>
      </div>
    </div>

    <h3 class="collector__section-title">已同步联赛</h3>
    <p v-if="isLoading" class="collector__hint">加载中…</p>
    <table v-else class="collector__table">
      <thead>
        <tr>
          <th>ID</th><th>名称</th><th>国家/地区</th><th>级别</th><th>赛季</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="league in leagues" :key="league.league_id">
          <td>{{ league.league_id }}</td>
          <td>{{ league.league_name }}</td>
          <td>{{ league.country }}</td>
          <td>{{ league.tier === 1 ? '顶级' : '次级' }}</td>
          <td>{{ league.season }}</td>
        </tr>
        <tr v-if="leagues.length === 0">
          <td colspan="5" class="collector__empty">暂无数据,输入联赛名称开始同步</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.collector {
  max-width: 1080px;
  margin: 0 auto;

  &__header {
    margin-bottom: vars.$spacing-lg;
  }

  &__title {
    margin: 0 0 vars.$spacing-xs;
  }

  &__subtitle {
    margin: 0;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-md;
  }

  &__panel {
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    padding: vars.$spacing-lg;
    margin-bottom: vars.$spacing-lg;
  }

  &__form {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    flex-wrap: wrap;
  }

  &__label {
    font-size: vars.$font-size-md;
    color: vars.$color-text-secondary;
  }

  &__input {
    flex: 1;
    min-width: 200px;
    padding: vars.$spacing-sm vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-md;
    background: vars.$color-bg;

    &:focus {
      outline: none;
      border-color: vars.$color-primary;
    }
  }

  &__btn {
    padding: vars.$spacing-sm vars.$spacing-lg;
    border: none;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-md;
    cursor: pointer;
    transition: opacity 0.15s ease;

    &:hover:not(:disabled) {
      opacity: 0.9;
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  &__quick {
    display: flex;
    align-items: center;
    gap: vars.$spacing-xs;
    margin-top: vars.$spacing-md;
    flex-wrap: wrap;
  }

  &__quick-label {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__chip {
    padding: 2px vars.$spacing-sm;
    border: 1px solid vars.$color-border;
    border-radius: 999px;
    background: transparent;
    color: vars.$color-text-primary;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &--active {
      border-color: vars.$color-primary;
      color: vars.$color-primary;
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  &__hint {
    margin: vars.$spacing-md 0 0;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
  }

  &__error {
    margin: vars.$spacing-md 0 0;
    color: vars.$color-danger;
    font-size: vars.$font-size-md;
  }

  &__result {
    margin-top: vars.$spacing-lg;
    padding: vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface-hover;
  }

  &__result-head {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    margin-bottom: vars.$spacing-sm;
  }

  &__result-badge {
    padding: 2px vars.$spacing-sm;
    border-radius: 4px;
    background: vars.$color-positive;
    color: #fff;
    font-size: vars.$font-size-sm;
  }

  &__result-source {
    margin-left: auto;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
  }

  &__result-fields {
    display: flex;
    gap: vars.$spacing-lg;
    margin: 0;
    flex-wrap: wrap;

    dt {
      font-size: vars.$font-size-sm;
      color: vars.$color-text-secondary;
      margin-bottom: 2px;
    }

    dd {
      margin: 0;
      font-size: vars.$font-size-md;
    }
  }

  &__section-title {
    margin: vars.$spacing-lg 0 vars.$spacing-sm;
  }

  &__table {
    width: 100%;
    border-collapse: collapse;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    margin-bottom: vars.$spacing-md;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-md;
      border-bottom: 1px solid vars.$color-border;
      text-align: left;
      font-size: vars.$font-size-md;
    }

    th {
      background: vars.$color-surface-hover;
    }
  }

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
  }
}
</style>
