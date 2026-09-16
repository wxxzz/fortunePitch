<script setup lang="ts">
/**
 * 页面D:个人复盘中心(User Dashboard)。
 * 核心指标卡片 + 收益走势折线图 + 分布饼图 + 历史决策列表(支持复盘回溯)
 * + 串关虚拟投注方案列表(可展开查看选注明细)。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { listBetSchemes, type BetScheme } from '@/api/strategy/betScheme'
import { useStrategyStore } from '@/stores/strategy'
import KpiCard from '@/components/retrospect/KpiCard.vue'
import ProfitCurveChart, {
  type ProfitPoint,
} from '@/components/retrospect/ProfitCurveChart.vue'
import DistributionPieChart, {
  type DistributionSlice,
} from '@/components/retrospect/DistributionPieChart.vue'

/** 演示用户 ID(与投注确认弹窗一致) */
const DEMO_USER_ID = 1

const router = useRouter()
const strategyStore = useStrategyStore()
const { decisions, isLoading, error } = storeToRefs(strategyStore)

// ---------- 串关虚拟投注方案 ----------

const schemes = ref<BetScheme[]>([])
const schemesError = ref('')
/** 当前展开明细的方案 ID */
const expandedSchemeId = ref<number | null>(null)

async function loadSchemes(): Promise<void> {
  try {
    schemes.value = await listBetSchemes({ user_id: DEMO_USER_ID, limit: 50 })
  } catch (err) {
    schemesError.value = err instanceof Error ? err.message : '串关方案加载失败'
  }
}

function toggleSchemeDetail(schemeId: number): void {
  expandedSchemeId.value = expandedSchemeId.value === schemeId ? null : schemeId
}

onMounted(() => {
  void strategyStore.fetchAll()
  void loadSchemes()
})

// ---------- 核心指标 ----------

const totalCount = computed(() => decisions.value.length)

const winRate = computed(() => {
  const wins = decisions.value.filter((d) => d.result_status === 'WIN').length
  if (totalCount.value === 0) return '0.0%'
  return `${((wins / totalCount.value) * 100).toFixed(1)}%`
})

/** ROI = 累计盈亏 / 累计模拟注额 */
const roi = computed(() => {
  const totalStake = decisions.value.reduce((s, d) => s + d.stake_amount, 0)
  const totalProfit = decisions.value.reduce((s, d) => s + (d.profit_loss ?? 0), 0)
  if (totalStake === 0) return '0.0%'
  return `${((totalProfit / totalStake) * 100).toFixed(1)}%`
})

/** 最大连红(连续 WIN 的最长长度) */
const maxWinStreak = computed(() => {
  let current = 0
  let best = 0
  for (const d of decisions.value) {
    if (d.result_status === 'WIN') {
      current += 1
      best = Math.max(best, current)
    } else {
      current = 0
    }
  }
  return `${best} 连红`
})

const totalProfit = computed(() =>
  decisions.value.reduce((s, d) => s + (d.profit_loss ?? 0), 0),
)

// ---------- 收益走势 ----------

const profitPoints = computed<ProfitPoint[]>(() => {
  if (decisions.value.length === 0) {
    // 演示走势
    return [
      { label: '1', cumulativeProfit: -50 },
      { label: '2', cumulativeProfit: 120 },
      { label: '3', cumulativeProfit: 60 },
      { label: '4', cumulativeProfit: 260 },
      { label: '5', cumulativeProfit: 180 },
      { label: '6', cumulativeProfit: 420 },
    ]
  }
  let cumulative = 0
  return decisions.value.map((d, index) => {
    cumulative += d.profit_loss ?? 0
    return { label: `${index + 1}`, cumulativeProfit: cumulative }
  })
})

// ---------- 分布饼图(演示数据) ----------

const leagueSlices = computed<DistributionSlice[]>(() => [
  { name: '英超', value: 12 },
  { name: '西甲', value: 8 },
  { name: '意甲', value: 6 },
  { name: '德甲', value: 5 },
  { name: '法甲', value: 4 },
])

const oddsRangeSlices = computed<DistributionSlice[]>(() => [
  { name: '低赔 (1.20-1.60)', value: 9 },
  { name: '中赔 (1.60-2.20)', value: 14 },
  { name: '高赔 (2.20+)', value: 12 },
])

const statusLabel: Record<string, string> = {
  WIN: '命中',
  LOSS: '未中',
  PUSH: '走盘',
}

/** 串关方案结算状态展示 */
const schemeStatusLabel: Record<string, string> = {
  PENDING: '待结算',
  WIN: '全部命中',
  LOSS: '未全中',
}

/** 方案创建时间展示(本地时区,精确到分钟) */
function formatSchemeTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number): string => `${n}`.padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function handleReview(recommendId: number): void {
  void router.push(`/match/rec-${recommendId}`)
}
</script>

<template>
  <section class="user-dashboard">
    <h2 class="user-dashboard__title">我的复盘中心</h2>

    <p v-if="error" class="user-dashboard__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="user-dashboard__hint">加载中…</p>

    <!-- 核心指标卡片 -->
    <div class="user-dashboard__kpis">
      <KpiCard label="总场次" :value="`${totalCount}`" />
      <KpiCard label="胜率" :value="winRate" tone="up" />
      <KpiCard
        label="ROI(投资回报率)"
        :value="roi"
        :tone="totalProfit >= 0 ? 'up' : 'down'"
      />
      <KpiCard label="最大连红" :value="maxWinStreak" />
    </div>

    <!-- 收益走势 -->
    <div class="user-dashboard__panel">
      <h3 class="user-dashboard__section-title">模拟资金收益走势(虚拟)</h3>
      <ProfitCurveChart :points="profitPoints" />
    </div>

    <!-- 分布饼图 -->
    <div class="user-dashboard__pies">
      <div class="user-dashboard__panel">
        <DistributionPieChart title="命中赛事联赛分布(演示)" :slices="leagueSlices" />
      </div>
      <div class="user-dashboard__panel">
        <DistributionPieChart title="命中赛事赔率区间分布(演示)" :slices="oddsRangeSlices" />
      </div>
    </div>

    <!-- 历史决策列表 -->
    <div class="user-dashboard__panel">
      <h3 class="user-dashboard__section-title">历史决策</h3>
      <table class="user-dashboard__table">
        <thead>
          <tr>
            <th>决策 ID</th><th>推荐 ID</th><th>玩法</th><th>注额(模拟)</th><th>状态</th><th>盈亏</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="decision in decisions" :key="decision.decision_id">
            <td>{{ decision.decision_id }}</td>
            <td>{{ decision.recommend_id }}</td>
            <td>{{ decision.user_bet_type }}</td>
            <td>{{ decision.stake_amount.toFixed(2) }}</td>
            <td
              class="user-dashboard__status"
              :class="`user-dashboard__status--${decision.result_status.toLowerCase()}`"
            >
              {{ statusLabel[decision.result_status] ?? decision.result_status }}
            </td>
            <td
              :class="
                (decision.profit_loss ?? 0) >= 0
                  ? 'user-dashboard__profit--pos'
                  : 'user-dashboard__profit--neg'
              "
            >
              {{ decision.profit_loss?.toFixed(2) ?? '-' }}
            </td>
            <td>
              <button
                class="user-dashboard__review-btn"
                type="button"
                @click="handleReview(decision.recommend_id)"
              >
                复盘
              </button>
            </td>
          </tr>
          <tr v-if="decisions.length === 0">
            <td colspan="7" class="user-dashboard__empty">暂无决策记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 串关虚拟投注方案列表 -->
    <div class="user-dashboard__panel">
      <h3 class="user-dashboard__section-title">串关方案(虚拟投注)</h3>
      <p v-if="schemesError" class="user-dashboard__error" role="alert">
        {{ schemesError }}
      </p>
      <table class="user-dashboard__table">
        <thead>
          <tr>
            <th>方案 ID</th><th>过关方式</th><th>注数</th><th>每注注额</th>
            <th>总投入</th><th>单注最高赔率</th><th>状态</th><th>创建时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="scheme in schemes" :key="scheme.scheme_id">
            <tr>
              <td>{{ scheme.scheme_id }}</td>
              <td>{{ scheme.parlay_size }}串1</td>
              <td>{{ scheme.bet_count }}</td>
              <td>{{ scheme.stake_per_bet.toFixed(2) }}</td>
              <td>{{ scheme.total_stake.toFixed(2) }}</td>
              <td>{{ scheme.max_odds?.toFixed(2) ?? '-' }}</td>
              <td
                class="user-dashboard__status"
                :class="`user-dashboard__status--${scheme.status.toLowerCase()}`"
              >
                {{ schemeStatusLabel[scheme.status] ?? scheme.status }}
              </td>
              <td>{{ formatSchemeTime(scheme.created_at) }}</td>
              <td>
                <button
                  class="user-dashboard__review-btn"
                  type="button"
                  @click="toggleSchemeDetail(scheme.scheme_id)"
                >
                  {{ expandedSchemeId === scheme.scheme_id ? '收起' : '明细' }}
                </button>
              </td>
            </tr>
            <tr v-if="expandedSchemeId === scheme.scheme_id">
              <td colspan="9" class="user-dashboard__scheme-items">
                <ul class="user-dashboard__scheme-list">
                  <li
                    v-for="item in scheme.items"
                    :key="item.item_id"
                    class="user-dashboard__scheme-item"
                  >
                    <span class="user-dashboard__scheme-match">{{ item.match_name }}</span>
                    <span>{{ item.play_name }}</span>
                    <span>{{ item.option_label }}</span>
                    <span class="user-dashboard__scheme-odds">@{{ item.odds.toFixed(2) }}</span>
                  </li>
                </ul>
              </td>
            </tr>
          </template>
          <tr v-if="schemes.length === 0">
            <td colspan="9" class="user-dashboard__empty">暂无串关方案</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.user-dashboard {
  max-width: 1080px;
  margin: 0 auto;

  &__title {
    margin: 0 0 vars.$spacing-lg;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__hint {
    color: vars.$color-text-secondary;
  }

  &__kpis {
    display: flex;
    gap: vars.$spacing-md;
    margin-bottom: vars.$spacing-lg;
  }

  &__panel {
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    margin-bottom: vars.$spacing-lg;
  }

  &__pies {
    display: flex;
    gap: vars.$spacing-lg;
  }

  &__section-title {
    margin: 0 0 vars.$spacing-sm;
    font-size: vars.$font-size-md;
  }

  &__table {
    width: 100%;
    border-collapse: collapse;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-md;
      border-bottom: 1px solid vars.$color-border;
      text-align: left;
    }

    th {
      color: vars.$color-text-secondary;
      font-weight: 600;
    }
  }

  // 红=利好(命中),绿=利空(未中)
  &__status--win {
    color: vars.$color-positive;
    font-weight: 600;
  }

  &__status--loss {
    color: vars.$color-negative;
    font-weight: 600;
  }

  &__profit--pos {
    color: vars.$color-positive;
  }

  &__profit--neg {
    color: vars.$color-negative;
  }

  &__review-btn {
    padding: vars.$spacing-xs vars.$spacing-sm;
    border: 1px solid vars.$color-primary;
    border-radius: vars.$border-radius;
    background: transparent;
    color: vars.$color-primary;
    cursor: pointer;

    &:hover {
      background: vars.$color-primary;
      color: #fff;
    }
  }

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
  }

  &__scheme-items {
    background: vars.$color-bg;
  }

  &__scheme-list {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  &__scheme-item {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
    font-size: vars.$font-size-sm;
  }

  &__scheme-match {
    min-width: 180px;
    font-weight: 600;
  }

  &__scheme-odds {
    margin-left: auto;
    color: vars.$color-positive;
    font-weight: 600;
  }
}
</style>
