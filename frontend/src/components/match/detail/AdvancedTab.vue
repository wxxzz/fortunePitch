<script setup lang="ts">
/**
 * 深度分析 · 高阶数据 Tab。
 *
 * Elo 评分 / 近期状态 / 攻防强度(Dixon-Coles)/ 模型概率(泊松比分分布)。
 * 数据来自父组件持有的共享 insights 状态(与历史交锋 Tab 同一 payload)。
 */
import { computed } from 'vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import { pct, RESULT_DOT_MODIFIER } from './constants'
import type { MatchInsightsState } from '@/composables/useMatchInsights'

const props = defineProps<{ state: MatchInsightsState }>()

const insights = computed(() => props.state.insights)

/** Top 比分概率条宽度(相对最高概率归一,便于横向对比) */
function scoreBarWidth(probability: number): string {
  const top = insights.value?.poisson?.top_scores[0]?.probability ?? 0
  if (top <= 0) return '0%'
  return `${Math.round((probability / top) * 100)}%`
}
</script>

<template>
  <section class="advanced-tab">
    <p v-if="state.error" class="advanced-tab__error" role="alert">{{ state.error }}</p>
    <SkeletonBlock v-if="state.isLoading" :height="320" label="加载高阶数据…" />
    <template v-else-if="insights">
      <!-- Elo 评分 -->
      <h3 class="advanced-tab__section-title">Elo 评分</h3>
      <div class="advanced-tab__duel">
        <div class="advanced-tab__duel-side">
          <strong class="advanced-tab__duel-name">{{ insights.home_team_name }}</strong>
          <span class="advanced-tab__duel-value">
            {{ insights.elo.home_rating !== null ? insights.elo.home_rating.toFixed(0) : '未评分' }}
          </span>
          <span class="advanced-tab__hint">已计 {{ insights.elo.home_matches_played }} 场</span>
        </div>
        <div class="advanced-tab__duel-center">
          <span class="advanced-tab__duel-diff">
            {{
              insights.elo.rating_diff !== null
                ? `评分差 ${insights.elo.rating_diff > 0 ? '+' : ''}${insights.elo.rating_diff.toFixed(0)}`
                : '待重算'
            }}
          </span>
          <template v-if="insights.elo.home_expected_score !== null">
            <div class="advanced-tab__duel-bar" role="presentation">
              <span
                class="advanced-tab__duel-bar-home"
                :style="{ width: pct(insights.elo.home_expected_score) }"
              />
            </div>
            <span class="advanced-tab__hint">
              主队期望得分 {{ pct(insights.elo.home_expected_score) }}(含主场优势)
            </span>
          </template>
        </div>
        <div class="advanced-tab__duel-side">
          <strong class="advanced-tab__duel-name">{{ insights.away_team_name }}</strong>
          <span class="advanced-tab__duel-value">
            {{ insights.elo.away_rating !== null ? insights.elo.away_rating.toFixed(0) : '未评分' }}
          </span>
          <span class="advanced-tab__hint">已计 {{ insights.elo.away_matches_played }} 场</span>
        </div>
      </div>
      <p v-if="insights.elo.home_rating === null || insights.elo.away_rating === null" class="advanced-tab__hint">
        Elo 评分由球队看板赛果按时间序回放计算,同步看板数据并由系统重算后生成
      </p>

      <!-- 近期状态对比 -->
      <h3 class="advanced-tab__section-title">近期状态对比</h3>
      <div class="advanced-tab__form-grid">
        <article
          v-for="form in [insights.home_form, insights.away_form]"
          :key="form.team_id"
          class="advanced-tab__form-card"
        >
          <header class="advanced-tab__form-head">
            <strong>{{ form.team_name }}</strong>
            <span class="advanced-tab__form-streak">{{ form.streak_label }}</span>
          </header>
          <div v-if="form.results" class="advanced-tab__form-dots">
            <span
              v-for="(result, index) in form.results"
              :key="index"
              class="advanced-tab__form-dot"
              :class="`advanced-tab__form-dot--${RESULT_DOT_MODIFIER[result] ?? 'd'}`"
            >
              {{ result }}
            </span>
          </div>
          <p v-else class="advanced-tab__hint">无近期已赛记录</p>
          <p class="advanced-tab__form-stats">
            {{ form.wins }}胜 {{ form.draws }}平 {{ form.losses }}负 ·
            场均进 {{ form.goals_for_avg }} 失 {{ form.goals_against_avg }}
          </p>
        </article>
      </div>
      <p class="advanced-tab__hint">结果圆点按时间倒序排列(最左为最近一场):红=胜 / 灰=平 / 绿=负</p>

      <!-- 攻防强度 -->
      <h3 class="advanced-tab__section-title">攻防强度(Dixon-Coles)</h3>
      <table v-if="insights.strength.home_attack !== null" class="advanced-tab__table">
        <thead>
          <tr>
            <th>指标</th>
            <th>{{ insights.home_team_name }}</th>
            <th>{{ insights.away_team_name }}</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>进攻强度</td>
            <td>{{ insights.strength.home_attack?.toFixed(2) }}</td>
            <td>{{ insights.strength.away_attack?.toFixed(2) }}</td>
          </tr>
          <tr>
            <td>防守强度(失球比,越低越好)</td>
            <td>{{ insights.strength.home_defense?.toFixed(2) }}</td>
            <td>{{ insights.strength.away_defense?.toFixed(2) }}</td>
          </tr>
          <tr>
            <td>期望进球</td>
            <td>λ = {{ insights.strength.lam?.toFixed(2) }}</td>
            <td>μ = {{ insights.strength.mu?.toFixed(2) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="advanced-tab__hint">攻防数据不足(需联赛积分榜数据)</p>
      <p v-if="insights.strength.league_avg_home_goals !== null" class="advanced-tab__hint">
        1.00 = 联赛均值 · 联赛基准:主队场均
        {{ insights.strength.league_avg_home_goals.toFixed(2) }} 球 / 客队场均
        {{ insights.strength.league_avg_away_goals?.toFixed(2) }} 球
      </p>

      <!-- 模型概率 -->
      <h3 class="advanced-tab__section-title">模型概率(泊松比分分布)</h3>
      <template v-if="insights.poisson">
        <div class="advanced-tab__prob" role="presentation">
          <span
            class="advanced-tab__prob-seg advanced-tab__prob-seg--home"
            :style="{ width: pct(insights.poisson.home_win) }"
          >
            主胜 {{ pct(insights.poisson.home_win) }}
          </span>
          <span
            class="advanced-tab__prob-seg advanced-tab__prob-seg--draw"
            :style="{ width: pct(insights.poisson.draw) }"
          >
            平 {{ pct(insights.poisson.draw) }}
          </span>
          <span
            class="advanced-tab__prob-seg advanced-tab__prob-seg--away"
            :style="{ width: pct(insights.poisson.away_win) }"
          >
            客胜 {{ pct(insights.poisson.away_win) }}
          </span>
        </div>
        <div class="advanced-tab__insight-cols">
          <div class="advanced-tab__insight-col">
            <h4 class="advanced-tab__sub-title">最可能比分(Top 5)</h4>
            <ul class="advanced-tab__score-list">
              <li
                v-for="score in insights.poisson.top_scores"
                :key="`${score.home_goals}-${score.away_goals}`"
              >
                <span class="advanced-tab__score-label">{{ score.home_goals }} : {{ score.away_goals }}</span>
                <span class="advanced-tab__score-bar" role="presentation">
                  <span :style="{ width: scoreBarWidth(score.probability) }" />
                </span>
                <span class="advanced-tab__score-prob">{{ pct(score.probability) }}</span>
              </li>
            </ul>
          </div>
          <div class="advanced-tab__insight-col">
            <h4 class="advanced-tab__sub-title">总进球与大小球</h4>
            <p class="advanced-tab__form-stats">
              大于 2.5 球 {{ pct(insights.poisson.over_2_5) }} ·
              不大于 2.5 球 {{ pct(insights.poisson.under_2_5) }}
            </p>
            <p class="advanced-tab__form-stats">
              总进球期望 {{ insights.poisson.total_goals_expected.toFixed(2) }} 球
            </p>
          </div>
        </div>
        <p class="advanced-tab__hint">
          概率由 λ/μ 双泊松(Dixon-Coles 低分修正)推导,非外部数据 · 仅供参考
        </p>
      </template>
      <p v-else class="advanced-tab__hint">攻防数据不足,无法计算泊松概率</p>
    </template>
    <p v-else class="advanced-tab__hint">暂无高阶数据</p>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;
@use './detail-shared' as shared;

.advanced-tab {
  @include shared.panel;

  &__duel {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: vars.$spacing-lg;
    padding: vars.$spacing-lg;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__duel-side {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: vars.$spacing-xs;
  }

  &__duel-name {
    font-size: vars.$font-size-md;
  }

  &__duel-value {
    font-size: 26px;
    font-weight: 700;
    color: vars.$color-text-primary;
  }

  &__duel-center {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: vars.$spacing-xs;
    min-width: 200px;
  }

  &__duel-diff {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__duel-bar {
    width: 100%;
    height: 8px;
    background: rgba(30, 100, 190, 0.25);
    border-radius: 4px;
    overflow: hidden;
  }

  &__duel-bar-home {
    display: block;
    height: 100%;
    background: vars.$color-positive;
  }

  &__form-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: vars.$spacing-md;
  }

  &__form-card {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__form-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-sm;
  }

  &__form-streak {
    padding: 2px vars.$spacing-sm;
    border-radius: vars.$border-radius;
    background: vars.$color-primary-light;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
    white-space: nowrap;
  }

  &__form-dots {
    display: flex;
    flex-wrap: wrap;
    gap: vars.$spacing-xs;
  }

  &__form-stats {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__sub-title {
    margin: 0 0 vars.$spacing-sm;
    font-size: vars.$font-size-md;
  }

  &__insight-cols {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: vars.$spacing-md;
  }

  &__insight-col {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
  }

  &__prob {
    display: flex;
    height: 30px;
    border-radius: vars.$border-radius;
    overflow: hidden;
    font-size: vars.$font-size-sm;
    color: #fff;
  }

  &__prob-seg {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    white-space: nowrap;
    overflow: hidden;

    &--home {
      background: vars.$color-positive;
    }

    &--draw {
      background: vars.$color-neutral;
    }

    &--away {
      background: #1e64be;
    }
  }

  &__score-list {
    margin: 0;
    padding: 0;
    list-style: none;

    li {
      display: flex;
      align-items: center;
      gap: vars.$spacing-sm;
      padding: vars.$spacing-xs 0;
    }
  }

  &__score-label {
    min-width: 44px;
    font-weight: 600;
    text-align: center;
  }

  &__score-bar {
    flex: 1;
    height: 6px;
    background: vars.$color-border;
    border-radius: 3px;
    overflow: hidden;

    span {
      display: block;
      height: 100%;
      background: vars.$color-primary;
    }
  }

  &__score-prob {
    min-width: 40px;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    text-align: right;
  }
}
</style>
