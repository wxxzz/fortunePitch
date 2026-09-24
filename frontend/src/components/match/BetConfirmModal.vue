<script setup lang="ts">
/**
 * 投注确认弹窗:
 * - 单关:批量写入用户模拟决策(fp_strategy_user_decisions);
 * - 串关/混合:选择过关方式(2串1~8串1),展示注数/总投入/单注最高赔率,
 *   确认后保存串关虚拟投注方案(fp_strategy_bet_schemes);
 * - 内嵌方案分析(隐含概率/中奖概率/期望值),随选注、注额与过关方式刷新。
 * 注额均为模拟数据,不涉及真实资金。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { analyzeBetPlan, type PlanAnalysis } from '@/api/strategy/planAnalysis'
import { saveBetScheme } from '@/api/strategy/betScheme'
import { createUserDecisionsBatch } from '@/api/strategy/userDecision'
import { useSelectionStore } from '@/stores/selection'
import { MAX_PARLAY_SIZE, MIN_PARLAY_SIZE, computeParlay } from '@/utils/parlay'

/** 演示用户 ID(当前无登录体系,模拟决策固定归属演示用户) */
const DEMO_USER_ID = 1

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'success', betCount: number): void
}>()

const selectionStore = useSelectionStore()
const { selectionList, count, mode } = storeToRefs(selectionStore)
const { clear } = selectionStore

const stakeAmount = ref<number>(100)
const isSubmitting = ref(false)
const errorMessage = ref('')

/** 串关/混合模式下的过关方式(N串1 的 N) */
const parlaySize = ref<number>(MIN_PARLAY_SIZE)

/** 是否走串关保存路径(混合模式同样按串关口径保存) */
const isParlayMode = computed<boolean>(() => mode.value !== 'single')

/** 已勾选的不同场次数 */
const distinctMatchCount = computed<number>(
  () => new Set(selectionList.value.map((item) => item.matchId)).size,
)

/** 可选的过关方式:2串1 ~ min(场次数, 8)串1 */
const parlayOptions = computed<number[]>(() => {
  const max = Math.min(distinctMatchCount.value, MAX_PARLAY_SIZE)
  const options: number[] = []
  for (let size = MIN_PARLAY_SIZE; size <= max; size++) options.push(size)
  return options
})

// 勾选变化后,若当前过关方式超出可选范围则回落到最大可选值
watch(
  () => parlayOptions.value.length,
  (length) => {
    const max = MIN_PARLAY_SIZE + Math.max(length - 1, 0)
    if (parlaySize.value > max) parlaySize.value = max
  },
)

/** 串关组合预览(注数/单注最高赔率),不满足串关规则时带 error */
const parlayCalc = computed(() => {
  if (!isParlayMode.value || count.value === 0) return null
  return computeParlay(selectionList.value, parlaySize.value)
})

/** 当前不可提交的原因(为空表示可提交) */
const invalidReason = computed<string>(() => {
  if (!isParlayMode.value) return ''
  if (parlayCalc.value?.error) return parlayCalc.value.error
  if (distinctMatchCount.value < MIN_PARLAY_SIZE) {
    return `串关至少需要勾选 ${MIN_PARLAY_SIZE} 个不同场次`
  }
  return ''
})

/** 单关展示注数;串关展示组合注数 */
const displayBetCount = computed<number>(() => {
  if (!isParlayMode.value) return count.value
  return parlayCalc.value?.betCount ?? 0
})

/** 串关总投入 = 每注注额 x 总注数 */
const totalStake = computed<number>(() => {
  if (!isParlayMode.value) return stakeAmount.value * count.value
  return stakeAmount.value * displayBetCount.value
})

/** 单关模式:各自独立结算,展示各注赔率合计口径无意义,直接提示 */
const oddsHint = computed<string>(() => {
  if (count.value === 0) return ''
  if (mode.value === 'single') return '单关:各注独立计算'
  if (invalidReason.value) return ''
  const maxOdds = parlayCalc.value?.maxOdds ?? 0
  return `单注最高赔率 ${maxOdds.toFixed(2)}`
})

// ---------- 方案分析(隐含概率 / 中奖概率 / 期望值) ----------

const analysis = ref<PlanAnalysis | null>(null)
const isAnalyzing = ref(false)
const analysisError = ref('')
let analysisTimer: ReturnType<typeof setTimeout> | null = null

/** 分析当前方案;选注为空或参数非法(串关规则/注额)时静默跳过 */
async function fetchAnalysis(): Promise<void> {
  const stakeValid =
    Number.isFinite(stakeAmount.value) && stakeAmount.value > 0
  if (count.value === 0 || invalidReason.value || !stakeValid) {
    analysis.value = null
    analysisError.value = ''
    return
  }
  isAnalyzing.value = true
  analysisError.value = ''
  try {
    analysis.value = await analyzeBetPlan({
      mode: mode.value,
      stake_per_bet: stakeAmount.value,
      parlay_size: isParlayMode.value ? parlaySize.value : undefined,
      selections: selectionList.value.map((item) => ({
        match_id: item.matchId,
        match_name: item.matchName,
        pool_code: item.poolCode,
        play_name: item.playName,
        option_code: item.optionCode,
        option_label: item.optionLabel,
        odds: item.odds,
      })),
    })
  } catch (error) {
    analysis.value = null
    analysisError.value =
      error instanceof Error ? error.message : '方案分析失败'
  } finally {
    isAnalyzing.value = false
  }
}

// 选注/模式/过关方式/注额变化后防抖重新分析
watch(
  () => [
    selectionList.value,
    mode.value,
    parlaySize.value,
    stakeAmount.value,
  ],
  () => {
    if (analysisTimer !== null) clearTimeout(analysisTimer)
    analysisTimer = setTimeout(fetchAnalysis, 400)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (analysisTimer !== null) clearTimeout(analysisTimer)
})

/** 概率展示为百分比(1 位小数) */
function formatProb(prob: number): string {
  return `${(prob * 100).toFixed(1)}%`
}

/** 带符号金额,如 +12.30 / -8.75 */
function formatSignedMoney(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}`
}

/** 带符号比率(1 位小数百分比),如 +2.5% / -9.1% */
function formatSignedPct(value: number): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

/** 带符号单位期望(4 位小数) */
function formatSignedUnit(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(4)}`
}

/** 期望值正负着色(正绿 / 负红) */
function evClass(value: number): string {
  return value >= 0
    ? 'bet-modal__value--positive'
    : 'bet-modal__value--negative'
}

async function handleConfirm(): Promise<void> {
  if (isSubmitting.value || count.value === 0) return
  if (!Number.isFinite(stakeAmount.value) || stakeAmount.value <= 0) {
    errorMessage.value = '请输入有效的模拟注额'
    return
  }
  if (invalidReason.value) {
    errorMessage.value = invalidReason.value
    return
  }
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    if (isParlayMode.value) {
      // 串关/混合:保存串关虚拟投注方案(服务端按同口径重算注数)
      const scheme = await saveBetScheme({
        user_id: DEMO_USER_ID,
        parlay_size: parlaySize.value,
        stake_per_bet: stakeAmount.value,
        items: selectionList.value.map((item) => ({
          match_id: item.matchId,
          match_name: item.matchName,
          pool_code: item.poolCode,
          play_name: item.playName,
          option_code: item.optionCode,
          option_label: item.optionLabel,
          odds: item.odds,
        })),
      })
      clear()
      emit('success', scheme.bet_count)
    } else {
      // 单关:批量写入用户模拟决策
      const result = await createUserDecisionsBatch({
        user_id: DEMO_USER_ID,
        stake_amount: stakeAmount.value,
        selections: selectionList.value.map((item) => ({
          match_id: item.matchId,
          pool_code: item.poolCode,
          option_code: item.optionCode,
          option_label: item.optionLabel,
        })),
      })
      clear()
      emit('success', result.decision_count)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '提交失败,请稍后重试'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      class="bet-modal"
      role="dialog"
      aria-modal="true"
      aria-label="投注方案确认"
      @click.self="emit('close')"
    >
      <div class="bet-modal__content">
        <header class="bet-modal__header">
          <h3 class="bet-modal__title">确认模拟投注方案</h3>
          <button
            class="bet-modal__close"
            type="button"
            aria-label="关闭"
            @click="emit('close')"
          >
            &times;
          </button>
        </header>

        <ul class="bet-modal__list">
          <li
            v-for="item in selectionList"
            :key="`${item.matchId}:${item.poolCode}:${item.optionCode}`"
            class="bet-modal__item"
          >
            <div class="bet-modal__item-match">{{ item.matchName }}</div>
            <div class="bet-modal__item-detail">
              <span class="bet-modal__item-play">{{ item.playName }}</span>
              <span class="bet-modal__item-option">{{ item.optionLabel }}</span>
              <span class="bet-modal__item-odds">@{{ item.odds.toFixed(2) }}</span>
            </div>
          </li>
        </ul>

        <div class="bet-modal__parlay">
          <label v-if="isParlayMode" class="bet-modal__parlay-label">
            过关方式
            <select v-model.number="parlaySize" class="bet-modal__parlay-select">
              <option
                v-for="size in parlayOptions"
                :key="size"
                :value="size"
              >
                {{ size }}串1
              </option>
            </select>
          </label>
          <span v-if="isParlayMode" class="bet-modal__parlay-hint">
            已选 {{ distinctMatchCount }} 场 / {{ count }} 个选项
          </span>
        </div>

        <div class="bet-modal__summary">
          <label class="bet-modal__stake">
            {{ isParlayMode ? '每注注额(元)' : '模拟注额(元)' }}
            <input
              v-model.number="stakeAmount"
              class="bet-modal__stake-input"
              type="number"
              min="1"
              max="10000"
              step="1"
            />
          </label>
          <div class="bet-modal__total">
            <span>共 {{ displayBetCount }} 注</span>
            <span v-if="isParlayMode && !invalidReason">
              总投入 {{ totalStake.toFixed(2) }} 元
            </span>
            <span v-if="oddsHint" class="bet-modal__odds">{{ oddsHint }}</span>
          </div>
        </div>

        <section
          v-if="analysis || isAnalyzing || analysisError"
          class="bet-modal__analysis"
          aria-label="方案分析"
        >
          <header class="bet-modal__analysis-header">
            <h4 class="bet-modal__analysis-title">方案分析</h4>
            <span class="bet-modal__analysis-hint">
              概率为赔率隐含概率(去水) · 模拟分析,不构成投注建议
            </span>
          </header>

          <p v-if="isAnalyzing" class="bet-modal__analysis-loading">
            分析中…
          </p>
          <p v-else-if="analysisError" class="bet-modal__analysis-loading">
            暂无法分析:{{ analysisError }}
          </p>

          <template v-else-if="analysis">
            <dl class="bet-modal__analysis-grid">
              <div class="bet-modal__analysis-metric">
                <dt>中奖概率</dt>
                <dd>{{ formatProb(analysis.win_prob) }}</dd>
              </div>
              <div class="bet-modal__analysis-metric">
                <dt>预计回报</dt>
                <dd>{{ analysis.expected_return.toFixed(2) }} 元</dd>
              </div>
              <div class="bet-modal__analysis-metric">
                <dt>期望值</dt>
                <dd :class="evClass(analysis.expected_value)">
                  {{ formatSignedMoney(analysis.expected_value) }} 元
                </dd>
              </div>
              <div class="bet-modal__analysis-metric">
                <dt>期望回报率</dt>
                <dd :class="evClass(analysis.ev_pct)">
                  {{ formatSignedPct(analysis.ev_pct) }}
                </dd>
              </div>
            </dl>

            <table class="bet-modal__analysis-table">
              <thead>
                <tr>
                  <th>选项</th>
                  <th>隐含概率</th>
                  <th>公平赔率</th>
                  <th>单位期望</th>
                  <th>凯利</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in analysis.selections"
                  :key="`${item.match_id}:${item.pool_code}:${item.option_code}`"
                >
                  <td class="bet-modal__analysis-option">
                    {{ item.match_name }} · {{ item.play_name }}
                    {{ item.option_label }}@{{ item.odds.toFixed(2) }}
                  </td>
                  <td>{{ formatProb(item.implied_prob) }}</td>
                  <td>{{ item.fair_odds.toFixed(2) }}</td>
                  <td :class="evClass(item.ev_per_unit)">
                    {{ formatSignedUnit(item.ev_per_unit) }}
                  </td>
                  <td>
                    {{
                      item.kelly_fraction > 0
                        ? formatProb(item.kelly_fraction)
                        : '—'
                    }}
                  </td>
                </tr>
              </tbody>
            </table>
          </template>
        </section>

        <p v-if="errorMessage" class="bet-modal__error">{{ errorMessage }}</p>

        <footer class="bet-modal__footer">
          <button class="bet-modal__cancel" type="button" @click="emit('close')">
            再想想
          </button>
          <button
            class="bet-modal__confirm"
            type="button"
            :disabled="isSubmitting || count === 0 || !!invalidReason"
            @click="handleConfirm"
          >
            {{ isSubmitting ? '提交中...' : '确认投注' }}
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.bet-modal {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: vars.$spacing-lg;
  background: rgba(15, 23, 18, 0.55);

  &__content {
    display: flex;
    flex-direction: column;
    width: min(520px, 100%);
    max-height: 80vh;
    border-radius: vars.$border-radius + 4px;
    background: vars.$color-surface;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
    overflow: hidden;
  }

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: vars.$spacing-md vars.$spacing-lg;
    background: linear-gradient(135deg, #1a7a4a, #0f5132);
    color: #fff;
  }

  &__title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }

  &__close {
    border: none;
    background: transparent;
    color: #fff;
    font-size: 20px;
    line-height: 1;
    cursor: pointer;
  }

  &__list {
    flex: 1;
    margin: 0;
    padding: vars.$spacing-md vars.$spacing-lg;
    list-style: none;
    overflow-y: auto;
  }

  &__item {
    padding: vars.$spacing-sm 0;
    border-bottom: 1px dashed vars.$color-border;

    &:last-child {
      border-bottom: none;
    }
  }

  &__item-match {
    font-size: vars.$font-size-md;
    font-weight: 600;
    color: vars.$color-text-primary;
  }

  &__item-detail {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
    margin-top: 2px;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__item-odds {
    margin-left: auto;
    color: vars.$color-positive;
    font-weight: 600;
  }

  &__parlay {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
    padding: vars.$spacing-sm vars.$spacing-lg;
    border-top: 1px solid vars.$color-border;
    background: vars.$color-bg;
  }

  &__parlay-label {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__parlay-select {
    padding: 4px vars.$spacing-sm;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-md;
    cursor: pointer;

    &:focus {
      outline: none;
      border-color: vars.$color-primary;
    }
  }

  &__parlay-hint {
    margin-left: auto;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-md;
    padding: vars.$spacing-md vars.$spacing-lg;
    border-top: 1px solid vars.$color-border;
    background: vars.$color-bg;
  }

  &__stake {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__stake-input {
    width: 90px;
    padding: 4px vars.$spacing-sm;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-md;
    text-align: right;

    &:focus {
      outline: none;
      border-color: vars.$color-primary;
    }
  }

  &__total {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__odds {
    color: vars.$color-positive;
    font-weight: 600;
  }

  &__analysis {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
    max-height: 220px;
    padding: vars.$spacing-md vars.$spacing-lg;
    border-top: 1px solid vars.$color-border;
    background: vars.$color-bg;
    overflow-y: auto;
  }

  &__analysis-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: vars.$spacing-sm;
  }

  &__analysis-title {
    margin: 0;
    font-size: vars.$font-size-md;
    font-weight: 600;
    color: vars.$color-text-primary;
  }

  &__analysis-hint {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__analysis-loading {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__analysis-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
    gap: vars.$spacing-sm;
    margin: 0;
  }

  &__analysis-metric {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: vars.$spacing-xs vars.$spacing-sm;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;

    dt {
      font-size: vars.$font-size-sm;
      color: vars.$color-text-secondary;
    }

    dd {
      margin: 0;
      font-size: vars.$font-size-md;
      font-weight: 600;
      color: vars.$color-text-primary;
    }
  }

  &__analysis-table {
    width: 100%;
    border-collapse: collapse;
    font-size: vars.$font-size-sm;

    th {
      padding: 2px vars.$spacing-xs;
      text-align: right;
      font-weight: 600;
      color: vars.$color-text-secondary;
      white-space: nowrap;

      &:first-child {
        text-align: left;
      }
    }

    td {
      padding: 3px vars.$spacing-xs;
      text-align: right;
      color: vars.$color-text-primary;
      white-space: nowrap;
      border-top: 1px dashed vars.$color-border;
    }
  }

  &__analysis-option {
    text-align: left !important;
    white-space: normal !important;
    color: vars.$color-text-secondary;
  }

  &__value--positive {
    color: vars.$color-positive;
  }

  &__value--negative {
    color: vars.$color-negative;
  }

  &__error {
    margin: 0;
    padding: 0 vars.$spacing-lg vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    color: vars.$color-danger;
  }

  &__footer {
    display: flex;
    gap: vars.$spacing-md;
    padding: vars.$spacing-md vars.$spacing-lg vars.$spacing-lg;
  }

  &__cancel,
  &__confirm {
    flex: 1;
    padding: 10px 0;
    border: none;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-md;
    font-weight: 600;
    cursor: pointer;
  }

  &__cancel {
    background: vars.$color-surface-hover;
    color: vars.$color-text-secondary;

    &:hover {
      background: vars.$color-border;
    }
  }

  &__confirm {
    background: vars.$color-primary;
    color: #fff;
    transition: background 0.2s;

    &:hover:not(:disabled) {
      background: #0f5132;
    }

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }
}
</style>
