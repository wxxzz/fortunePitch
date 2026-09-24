<script setup lang="ts">
/**
 * 页面D:个人复盘中心(User Dashboard)。
 *
 * 打开时自动触发结算(按赛果判定输赢/计算盈亏),随后加载:
 * 核心指标卡片 + 收益走势折线图 + 维度分析(玩法/赔率区间/联赛命中率)
 * + 单关决策富明细(状态筛选)+ 串关虚拟投注方案列表(逐腿命中)。
 * 盈亏着色遵循项目语义:红=正向/命中,绿=负向/未中。
 */
import { computed, onMounted, ref } from 'vue'
import { listBetSchemes, type BetScheme } from '@/api/strategy/betScheme'
import {
  getReviewStats,
  listReviewDecisions,
  settleAll,
  type DimensionStat,
  type ReviewDecision,
  type ReviewStats,
} from '@/api/strategy/review'
import KpiCard from '@/components/retrospect/KpiCard.vue'
import ProfitCurveChart, {
  type ProfitPoint,
} from '@/components/retrospect/ProfitCurveChart.vue'
import DistributionPieChart, {
  type DistributionSlice,
} from '@/components/retrospect/DistributionPieChart.vue'

/** 演示用户 ID(与投注确认弹窗一致) */
const DEMO_USER_ID = 1

// ---------- 整体加载与结算 ----------

const stats = ref<ReviewStats | null>(null)
const decisions = ref<ReviewDecision[]>([])
const error = ref('')
const isLoading = ref(false)

const isSettling = ref(false)
/** 最近一次结算结果提示(空串表示尚未结算) */
const settleNote = ref('')

async function refresh(): Promise<void> {
  error.value = ''
  isLoading.value = true
  isSettling.value = true
  try {
    const result = await settleAll(DEMO_USER_ID)
    const settled =
      result.decision_wins +
      result.decision_losses +
      result.scheme_wins +
      result.scheme_losses
    settleNote.value =
      settled > 0 ? `本次结算 ${settled} 注` : '暂无可结算注单'
  } catch {
    // 结算失败不阻塞复盘数据展示
    settleNote.value = '结算失败,以下为历史数据'
  } finally {
    isSettling.value = false
  }
  await Promise.all([loadStats(), loadDecisions(), loadSchemes()])
  isLoading.value = false
}

async function loadStats(): Promise<void> {
  try {
    stats.value = await getReviewStats(DEMO_USER_ID)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '统计数据加载失败'
  }
}

// ---------- 单关决策富明细 ----------

type StatusFilter = 'ALL' | 'WIN' | 'LOSS' | 'PUSH'

const statusFilter = ref<StatusFilter>('ALL')

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: 'ALL', label: '全部' },
  { key: 'WIN', label: '已赢' },
  { key: 'LOSS', label: '已输' },
  { key: 'PUSH', label: '待结算' },
]

async function loadDecisions(): Promise<void> {
  try {
    decisions.value = await listReviewDecisions({
      user_id: DEMO_USER_ID,
      limit: 100,
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '决策明细加载失败'
  }
}

const filteredDecisions = computed(() =>
  statusFilter.value === 'ALL'
    ? decisions.value
    : decisions.value.filter((d) => d.result_status === statusFilter.value),
)

const statusLabel: Record<string, string> = {
  WIN: '命中',
  LOSS: '未中',
  PUSH: '走盘',
}

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

/** 串关方案结算状态展示 */
const schemeStatusLabel: Record<string, string> = {
  PENDING: '待结算',
  WIN: '全部命中',
  LOSS: '未全中',
}

onMounted(() => {
  void refresh()
})

// ---------- 核心指标 ----------

const kpi = computed(() => stats.value?.kpi ?? null)

const totalCountText = computed(() => `${kpi.value?.total_bets ?? 0}`)

const hitRateText = computed(() => {
  const rate = kpi.value?.hit_rate ?? 0
  return `${(rate * 100).toFixed(1)}%`
})

const totalProfit = computed(() => kpi.value?.total_profit ?? 0)

const totalProfitText = computed(() => formatSignedMoney(totalProfit.value))

const roiText = computed(() => {
  const roi = kpi.value?.roi ?? 0
  return `${(roi * 100).toFixed(1)}%`
})

const maxWinStreakText = computed(() => `${kpi.value?.max_win_streak ?? 0} 连红`)

// ---------- 收益走势 ----------

const profitPoints = computed<ProfitPoint[]>(() =>
  (stats.value?.profit_curve ?? []).map((p: { label: string; cumulative_profit: number }) => ({
    label: p.label,
    cumulativeProfit: p.cumulative_profit,
  })),
)

const hasCurve = computed(() => profitPoints.value.length > 0)

// ---------- 维度分析 ----------

const byPlay = computed<DimensionStat[]>(() => stats.value?.by_play ?? [])
const byOddsRange = computed<DimensionStat[]>(() =>
  stats.value?.by_odds_range ?? [],
)

const leagueSlices = computed<DistributionSlice[]>(() =>
  (stats.value?.by_league ?? []).map(
    (d: { name: string; count: number; hits: number; hit_rate: number }) => ({
      name: d.name,
      value: d.count,
    }),
  ),
)

// ---------- 展示辅助 ----------

function formatSignedMoney(value: number): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}`
}

function formatOdds(value: number | null): string {
  return value === null ? '-' : value.toFixed(2)
}

/** 比赛时间展示(本地时区,精确到分钟) */
function formatMatchTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number): string => `${n}`.padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 方案创建时间展示(本地时区,精确到分钟) */
function formatSchemeTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number): string => `${n}`.padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatHitRate(stat: DimensionStat): string {
  return `${(stat.hit_rate * 100).toFixed(1)}%(${stat.hits}/${stat.count})`
}

/** 维度条形宽度(命中率 0~100%) */
function hitRateWidth(stat: DimensionStat): string {
  return `${Math.min(stat.hit_rate * 100, 100)}%`
}
</script>

<template>
  <section class="user-dashboard">
    <div class="user-dashboard__header">
      <h2 class="user-dashboard__title">我的复盘中心</h2>
      <div class="user-dashboard__actions">
        <span v-if="settleNote" class="user-dashboard__settle-note">
          {{ settleNote }}
        </span>
        <span
          v-if="kpi && kpi.pending > 0"
          class="user-dashboard__pending-badge"
        >
          待结算 {{ kpi.pending }} 注
        </span>
        <button
          class="user-dashboard__settle-btn"
          type="button"
          :disabled="isSettling"
          @click="refresh()"
        >
          {{ isSettling ? '结算中…' : '立即结算' }}
        </button>
      </div>
    </div>

    <p v-if="error" class="user-dashboard__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="user-dashboard__hint">加载中…</p>

    <!-- 核心指标卡片 -->
    <div class="user-dashboard__kpis">
      <KpiCard label="总注数" :value="totalCountText" />
      <KpiCard label="命中率" :value="hitRateText" tone="up" />
      <KpiCard
        label="累计盈亏(模拟)"
        :value="totalProfitText"
        :tone="totalProfit >= 0 ? 'up' : 'down'"
      />
      <KpiCard
        label="ROI(投资回报率)"
        :value="roiText"
        :tone="totalProfit >= 0 ? 'up' : 'down'"
      />
      <KpiCard label="最大连红" :value="maxWinStreakText" />
    </div>

    <!-- 收益走势 -->
    <div class="user-dashboard__panel">
      <h3 class="user-dashboard__section-title">模拟资金收益走势(虚拟)</h3>
      <ProfitCurveChart v-if="hasCurve" :points="profitPoints" />
      <p v-else class="user-dashboard__empty">暂无已结算注单,结算后展示收益曲线</p>
    </div>

    <!-- 维度分析 -->
    <div class="user-dashboard__dims">
      <div class="user-dashboard__panel">
        <h3 class="user-dashboard__section-title">按玩法命中率</h3>
        <div
          v-for="stat in byPlay"
          :key="stat.name"
          class="user-dashboard__dim-row"
        >
          <span class="user-dashboard__dim-name">{{ stat.name }}</span>
          <span class="user-dashboard__dim-bar">
            <span
              class="user-dashboard__dim-fill"
              :style="{ width: hitRateWidth(stat) }"
            ></span>
          </span>
          <span class="user-dashboard__dim-value">{{ formatHitRate(stat) }}</span>
        </div>
        <p v-if="byPlay.length === 0" class="user-dashboard__empty">暂无数据</p>
      </div>
      <div class="user-dashboard__panel">
        <h3 class="user-dashboard__section-title">按赔率区间命中率</h3>
        <div
          v-for="stat in byOddsRange"
          :key="stat.name"
          class="user-dashboard__dim-row"
        >
          <span class="user-dashboard__dim-name">{{ stat.name }}</span>
          <span class="user-dashboard__dim-bar">
            <span
              class="user-dashboard__dim-fill"
              :style="{ width: hitRateWidth(stat) }"
            ></span>
          </span>
          <span class="user-dashboard__dim-value">{{ formatHitRate(stat) }}</span>
        </div>
        <p v-if="byOddsRange.length === 0" class="user-dashboard__empty">
          暂无数据
        </p>
      </div>
      <div class="user-dashboard__panel">
        <DistributionPieChart
          title="选注联赛分布"
          :slices="leagueSlices"
        />
        <p v-if="leagueSlices.length === 0" class="user-dashboard__empty">
          暂无数据
        </p>
      </div>
    </div>

    <!-- 单关决策明细 -->
    <div class="user-dashboard__panel">
      <div class="user-dashboard__table-head">
        <h3 class="user-dashboard__section-title">单关决策明细</h3>
        <div class="user-dashboard__filters" role="tablist">
          <button
            v-for="filterItem in STATUS_FILTERS"
            :key="filterItem.key"
            class="user-dashboard__filter-btn"
            :class="{ 'user-dashboard__filter-btn--active': statusFilter === filterItem.key }"
            type="button"
            role="tab"
            :aria-selected="statusFilter === filterItem.key"
            @click="statusFilter = filterItem.key"
          >
            {{ filterItem.label }}
          </button>
        </div>
      </div>
      <table class="user-dashboard__table">
        <thead>
          <tr>
            <th>赛事</th><th>时间</th><th>玩法</th><th>选项</th><th>赔率</th>
            <th>注额(模拟)</th><th>赛果</th><th>输赢</th><th>盈亏</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="decision in filteredDecisions" :key="decision.decision_id">
            <td>
              <span class="user-dashboard__match-name">{{ decision.match_name }}</span>
              <span class="user-dashboard__league-name">{{ decision.league_name }}</span>
            </td>
            <td>{{ formatMatchTime(decision.match_time) }}</td>
            <td>{{ decision.play_name }}</td>
            <td>{{ decision.option_label }}</td>
            <td>{{ formatOdds(decision.odds) }}</td>
            <td>{{ decision.stake_amount.toFixed(2) }}</td>
            <td>{{ decision.result_label ?? '待赛果' }}</td>
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
              {{ decision.profit_loss === null ? '-' : formatSignedMoney(decision.profit_loss) }}
            </td>
          </tr>
          <tr v-if="filteredDecisions.length === 0">
            <td colspan="9" class="user-dashboard__empty">暂无决策记录</td>
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
            <th>总投入</th><th>单注最高赔率</th><th>状态</th><th>盈亏</th>
            <th>创建时间</th><th>操作</th>
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
              <td
                :class="
                  (scheme.profit_loss ?? 0) >= 0
                    ? 'user-dashboard__profit--pos'
                    : 'user-dashboard__profit--neg'
                "
              >
                {{ scheme.profit_loss === null ? '-' : formatSignedMoney(scheme.profit_loss) }}
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
              <td colspan="10" class="user-dashboard__scheme-items">
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
                    <span
                      class="user-dashboard__scheme-result"
                      :class="`user-dashboard__scheme-result--${item.is_hit === null ? 'pending' : item.is_hit ? 'hit' : 'miss'}`"
                    >
                      {{ item.result_label ?? '待赛果' }}
                    </span>
                  </li>
                </ul>
              </td>
            </tr>
          </template>
          <tr v-if="schemes.length === 0">
            <td colspan="10" class="user-dashboard__empty">暂无串关方案</td>
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

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-md;
    margin-bottom: vars.$spacing-lg;
    flex-wrap: wrap;
  }

  &__title {
    margin: 0;
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
  }

  &__settle-note {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__pending-badge {
    padding: vars.$spacing-xs vars.$spacing-sm;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__settle-btn {
    padding: vars.$spacing-xs vars.$spacing-md;
    border: 1px solid vars.$color-primary;
    border-radius: vars.$border-radius;
    background: transparent;
    color: vars.$color-primary;
    cursor: pointer;

    &:hover:not(:disabled) {
      background: vars.$color-primary;
      color: #fff;
    }

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
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
    flex-wrap: wrap;
  }

  &__panel {
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    margin-bottom: vars.$spacing-lg;
  }

  &__dims {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: vars.$spacing-lg;
  }

  &__section-title {
    margin: 0 0 vars.$spacing-sm;
    font-size: vars.$font-size-md;
  }

  &__dim-row {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    margin-bottom: vars.$spacing-sm;
    font-size: vars.$font-size-sm;
  }

  &__dim-name {
    min-width: 88px;
    color: vars.$color-text-secondary;
  }

  &__dim-bar {
    flex: 1;
    height: 8px;
    border-radius: 4px;
    background: vars.$color-bg;
    overflow: hidden;
  }

  &__dim-fill {
    display: block;
    height: 100%;
    border-radius: 4px;
    background: vars.$color-primary;
    transition: width 0.3s ease;
  }

  &__dim-value {
    min-width: 96px;
    text-align: right;
    font-weight: 600;
  }

  &__table-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-md;
    flex-wrap: wrap;
    margin-bottom: vars.$spacing-sm;
  }

  &__filters {
    display: flex;
    gap: vars.$spacing-xs;
  }

  &__filter-btn {
    padding: vars.$spacing-xs vars.$spacing-sm;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: transparent;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &:hover {
      border-color: vars.$color-primary;
      color: vars.$color-primary;
    }

    &--active {
      border-color: vars.$color-primary;
      background: vars.$color-primary;
      color: #fff;
    }
  }

  &__table {
    width: 100%;
    border-collapse: collapse;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-md;
      border-bottom: 1px solid vars.$color-border;
      text-align: left;
      white-space: nowrap;
    }

    th {
      color: vars.$color-text-secondary;
      font-weight: 600;
    }
  }

  &__match-name {
    display: block;
    font-weight: 600;
    white-space: normal;
  }

  &__league-name {
    display: block;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    white-space: normal;
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

  &__scheme-result {
    min-width: 64px;
    text-align: center;
    padding: vars.$spacing-xs vars.$spacing-xs;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-sm;

    &--hit {
      color: vars.$color-positive;
      background: rgba(214, 69, 65, 0.08);
      font-weight: 600;
    }

    &--miss {
      color: vars.$color-negative;
      background: rgba(30, 142, 90, 0.08);
    }

    &--pending {
      color: vars.$color-text-secondary;
      background: vars.$color-bg;
    }
  }
}
</style>
