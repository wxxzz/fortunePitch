<script setup lang="ts">
/**
 * 联赛多维度分析面板:对该联赛已完赛场次做结果分布统计。
 *
 * 维度:胜平负分布、进球(场均/3 球及以上/双方进球)、总进球分布、
 * 半全场分布、让球胜平负分布、热门命中(胜平负 SP 最低项的开奖命中率)。
 * 组件挂载即拉取;结果为数据分析参考,不构成投注建议。
 */
import { computed, onMounted, ref } from 'vue'
import { getLeagueInsights, type LeagueInsights } from '@/api/base/leagueInsights'

const props = defineProps<{
  leagueId: number
}>()

const insights = ref<LeagueInsights | null>(null)
const isLoading = ref(false)
const errorMessage = ref('')

async function fetchInsights(): Promise<void> {
  if (isLoading.value) return
  isLoading.value = true
  errorMessage.value = ''
  try {
    insights.value = await getLeagueInsights(props.leagueId)
  } catch (err) {
    insights.value = null
    errorMessage.value = err instanceof Error ? err.message : '多维度分析加载失败'
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  void fetchInsights()
})

/** 占比(0~1)转百分数文案,空值显示 — */
function pctText(rate: number | null): string {
  return rate !== null ? `${(rate * 100).toFixed(1)}%` : '—'
}

/** 标签分布行的条形宽度百分比(相对已赛场次) */
function barWidth(count: number): string {
  const total = insights.value?.finished_count ?? 0
  return total > 0 ? `${(count / total) * 100}%` : '0%'
}

/** 胜平负三行(标签/计数/占比) */
const resultRows = computed(() => {
  const data = insights.value
  if (data === null) return []
  return [
    { label: '主胜', count: data.home_win, rate: data.home_win_rate, tone: 'home' },
    { label: '平', count: data.draw, rate: data.draw_rate, tone: 'draw' },
    { label: '客胜', count: data.away_win, rate: data.away_win_rate, tone: 'away' },
  ]
})

/** 概览统计瓦片 */
const statTiles = computed(() => {
  const data = insights.value
  if (data === null) return []
  return [
    { label: '已赛场次', value: `${data.finished_count} 场` },
    {
      label: '场均进球',
      value: data.avg_total_goals !== null ? data.avg_total_goals.toFixed(2) : '—',
      sub:
        data.avg_home_goals !== null && data.avg_away_goals !== null
          ? `主 ${data.avg_home_goals.toFixed(2)} · 客 ${data.avg_away_goals.toFixed(2)}`
          : '',
    },
    {
      label: '3 球及以上',
      value: pctText(data.over2_5_rate),
      sub: `${data.over2_5_count} 场`,
    },
    {
      label: '双方进球',
      value: pctText(data.btts_rate),
      sub: `${data.btts_count} 场`,
    },
  ]
})
</script>

<template>
  <section class="league-insights">
    <div class="league-insights__toolbar">
      <h3 class="league-insights__title">多维度分析</h3>
      <span class="league-insights__meta">
        样本 {{ insights?.finished_count ?? 0 }} 场已完赛 · {{ insights?.season ?? '' }} 赛季口径
      </span>
      <button
        class="league-insights__refresh"
        type="button"
        :disabled="isLoading"
        @click="fetchInsights"
      >
        {{ isLoading ? '统计中…' : '刷新' }}
      </button>
    </div>

    <p v-if="errorMessage" class="league-insights__error" role="alert">{{ errorMessage }}</p>
    <p v-if="isLoading && insights === null" class="league-insights__hint" role="status">统计中…</p>

    <template v-if="insights !== null">
      <p v-if="insights.finished_count === 0" class="league-insights__empty">
        该联赛暂无已完赛场次,可在同步看板数据并完赛后查看多维度分析。
      </p>

      <template v-else>
        <!-- 概览统计瓦片 -->
        <div class="league-insights__tiles">
          <div v-for="tile in statTiles" :key="tile.label" class="league-insights__tile">
            <span class="league-insights__tile-label">{{ tile.label }}</span>
            <strong class="league-insights__tile-value">{{ tile.value }}</strong>
            <span v-if="tile.sub" class="league-insights__tile-sub">{{ tile.sub }}</span>
          </div>
        </div>

        <!-- 胜平负分布 -->
        <h4 class="league-insights__section-title">胜平负分布</h4>
        <div class="league-insights__bars">
          <div
            v-for="row in resultRows"
            :key="row.label"
            class="league-insights__bar-row"
          >
            <span class="league-insights__bar-label">{{ row.label }}</span>
            <div class="league-insights__bar-track">
              <div
                class="league-insights__bar"
                :class="`league-insights__bar--${row.tone}`"
                :style="{ width: barWidth(row.count) }"
              ></div>
            </div>
            <span class="league-insights__bar-value">
              {{ row.count }} 场 ({{ pctText(row.rate) }})
            </span>
          </div>
        </div>

        <div class="league-insights__grid">
          <!-- 总进球分布 -->
          <div>
            <h4 class="league-insights__section-title">总进球分布</h4>
            <div class="league-insights__bars">
              <div
                v-for="row in insights.total_goals"
                :key="row.label"
                class="league-insights__bar-row"
              >
                <span class="league-insights__bar-label">{{ row.label }} 球</span>
                <div class="league-insights__bar-track">
                  <div class="league-insights__bar" :style="{ width: barWidth(row.count) }"></div>
                </div>
                <span class="league-insights__bar-value">{{ row.count }} 场</span>
              </div>
            </div>
          </div>

          <!-- 半全场 / 让球分布 -->
          <div>
            <h4 class="league-insights__section-title">半全场分布</h4>
            <div class="league-insights__bars">
              <div
                v-for="row in insights.half_full"
                :key="row.label"
                class="league-insights__bar-row"
              >
                <span class="league-insights__bar-label">{{ row.label }}</span>
                <div class="league-insights__bar-track">
                  <div class="league-insights__bar" :style="{ width: barWidth(row.count) }"></div>
                </div>
                <span class="league-insights__bar-value">{{ row.count }} 场</span>
              </div>
              <p v-if="insights.half_full.length === 0" class="league-insights__hint">
                暂无半全场开奖数据
              </p>
            </div>

            <h4 class="league-insights__section-title">让球胜平负分布</h4>
            <div class="league-insights__bars">
              <div
                v-for="row in insights.handicap"
                :key="row.label"
                class="league-insights__bar-row"
              >
                <span class="league-insights__bar-label">{{ row.label }}</span>
                <div class="league-insights__bar-track">
                  <div
                    class="league-insights__bar league-insights__bar--handicap"
                    :style="{ width: barWidth(row.count) }"
                  ></div>
                </div>
                <span class="league-insights__bar-value">{{ row.count }} 场</span>
              </div>
              <p v-if="insights.handicap.length === 0" class="league-insights__hint">
                暂无让球玩法开奖数据
              </p>
            </div>
          </div>
        </div>

        <!-- 热门命中 -->
        <h4 class="league-insights__section-title">热门命中(SP 最低项)</h4>
        <p v-if="insights.favorite !== null" class="league-insights__favorite">
          统计 {{ insights.favorite.count }} 场 · 命中 {{ insights.favorite.hit_count }} 场
          ({{ pctText(insights.favorite.hit_rate) }}) · 热门项平均 SP
          {{ insights.favorite.avg_sp?.toFixed(2) ?? '—' }}
        </p>
        <p v-else class="league-insights__hint">暂无胜平负 SP 数据,无法统计热门命中。</p>
      </template>

      <p class="league-insights__footer">
        统计口径为该联赛全部已完赛且有比分的场次;数据仅用于分析参考,不构成投注建议。
      </p>
    </template>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.league-insights {
  &__toolbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: vars.$spacing-md;
    margin-bottom: vars.$spacing-md;
  }

  &__title {
    margin: 0;
  }

  &__meta {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__refresh {
    margin-left: auto;
    padding: vars.$spacing-xs vars.$spacing-md;
    border: 1px solid vars.$color-primary;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &:hover:not(:disabled) {
      background: vars.$color-primary-light;
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  &__section-title {
    margin: vars.$spacing-lg 0 vars.$spacing-sm;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__hint,
  &__footer {
    margin: vars.$spacing-sm 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__empty {
    padding: vars.$spacing-lg;
    border: 1px dashed vars.$color-border;
    border-radius: vars.$border-radius;
    color: vars.$color-text-secondary;
    text-align: center;
  }

  // ---------- 概览瓦片 ----------

  &__tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: vars.$spacing-md;
  }

  &__tile {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__tile-label {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__tile-value {
    font-size: vars.$font-size-lg;
    color: vars.$color-text-primary;
  }

  &__tile-sub {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  // ---------- 分布条形 ----------

  &__grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: vars.$spacing-lg;
    align-items: start;
  }

  &__bars {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
  }

  &__bar-row {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
  }

  &__bar-label {
    min-width: 72px;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    text-align: right;
    white-space: nowrap;
  }

  &__bar-track {
    flex: 1;
    height: 12px;
    border-radius: vars.$border-radius;
    background: vars.$color-surface-hover;
    overflow: hidden;
  }

  &__bar {
    height: 100%;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    transition: width 0.3s ease;

    &--draw,
    &--away {
      background: vars.$color-neutral;
    }

    &--handicap {
      background: vars.$color-info;
    }
  }

  &__bar-value {
    min-width: 96px;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-primary;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  &__favorite {
    margin: 0;
    padding: vars.$spacing-sm vars.$spacing-md;
    border-radius: vars.$border-radius;
    background: vars.$color-primary-light;
    color: vars.$color-primary;
    font-size: vars.$font-size-md;
  }
}
</style>
