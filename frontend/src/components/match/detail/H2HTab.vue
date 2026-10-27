<script setup lang="ts">
/**
 * 深度分析 · 历史交锋 Tab。
 *
 * 双方近期交手记录(由球队看板赛果交叉推导)与交锋战绩汇总。
 * 数据来自父组件持有的共享 insights 状态(与高阶数据 Tab 同一 payload)。
 */
import { computed } from 'vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import { formatMatchDate, RESULT_DOT_MODIFIER } from './constants'
import type { MatchInsightsState } from '@/composables/useMatchInsights'

const props = defineProps<{ state: MatchInsightsState }>()

const insights = computed(() => props.state.insights)
</script>

<template>
  <section class="h2h-tab">
    <p v-if="state.error" class="h2h-tab__error" role="alert">{{ state.error }}</p>
    <SkeletonBlock v-if="state.isLoading" :height="240" label="加载历史交锋…" />
    <template v-else-if="insights && insights.h2h.entries.length > 0">
      <div class="h2h-tab__summary">
        <span class="h2h-tab__badge h2h-tab__badge--home">
          {{ insights.home_team_name }} {{ insights.h2h.home_wins }} 胜
        </span>
        <span class="h2h-tab__badge h2h-tab__badge--draw">
          {{ insights.h2h.draws }} 平
        </span>
        <span class="h2h-tab__badge h2h-tab__badge--away">
          {{ insights.away_team_name }} {{ insights.h2h.away_wins }} 胜
        </span>
        <span v-if="insights.h2h.avg_total_goals !== null" class="h2h-tab__hint">
          近 {{ insights.h2h.entries.length }} 次交锋 ·
          场均总进球 {{ insights.h2h.avg_total_goals }}
        </span>
      </div>
      <table class="h2h-tab__table">
        <thead>
          <tr>
            <th>日期</th><th>对阵</th><th>比分</th><th>该场主队结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(entry, index) in insights.h2h.entries" :key="index">
            <td>{{ formatMatchDate(entry.match_time) }}</td>
            <td>{{ entry.home_team_name }} vs {{ entry.away_team_name }}</td>
            <td>{{ entry.score }}</td>
            <td>
              <span
                class="h2h-tab__form-dot"
                :class="`h2h-tab__form-dot--${RESULT_DOT_MODIFIER[entry.home_result] ?? 'd'}`"
              >
                {{ entry.home_result }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="h2h-tab__hint">
        历史交锋由双方球队看板赛果交叉推导(按本场主队视角统计) ·
        在“数据采集”页同步球队看板后更新
      </p>
    </template>
    <p v-else class="h2h-tab__hint">
      暂无历史交锋记录。请在“数据采集”页同步双方球队看板,两队交手记录将自动汇总。
    </p>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;
@use './detail-shared' as shared;

.h2h-tab {
  @include shared.panel;

  &__summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: vars.$spacing-sm;
  }

  &__badge {
    padding: vars.$spacing-xs vars.$spacing-md;
    border-radius: 999px;
    font-size: vars.$font-size-sm;
    font-weight: 600;

    &--home {
      background: rgba(214, 69, 65, 0.12);
      color: vars.$color-positive;
    }

    &--draw {
      background: vars.$color-surface-hover;
      color: vars.$color-text-secondary;
    }

    &--away {
      background: rgba(30, 100, 190, 0.12);
      color: #1e64be;
    }
  }
}
</style>
