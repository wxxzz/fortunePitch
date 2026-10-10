<script setup lang="ts">
/**
 * AI 单场推荐清单组件:
 * 工具条(置信度阈值 + 生成推荐按钮 + 批次摘要)+ 推荐表格
 * (场次/对阵/玩法/选项@赔率/置信度/EV/凯利/逆向标记/转模拟决策)。
 *
 * 转换后的决策进入结算/复盘闭环;注额均为模拟数据,
 * 分析结果仅供参考,不构成投注建议。
 */
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useStrategyStore } from '@/stores/strategy'
import { convertAiPick } from '@/api/strategy/aiPick'

const strategyStore = useStrategyStore()
const { aiPicks, aiBatch, aiBusinessDate, isGenerating } =
  storeToRefs(strategyStore)

/** 置信度阈值选项(后端按该值过滤 AI 分析推荐) */
const CONFIDENCE_OPTIONS = [0.5, 0.55, 0.6, 0.65, 0.7] as const
const minConfidence = ref<number>(0.55)

/** 默认模拟注额 */
const DEFAULT_STAKE = 100
const stakes = ref<Record<number, number>>({})
const convertingIds = ref<Set<number>>(new Set())
const convertMessage = ref<string | null>(null)

async function handleGenerate(): Promise<void> {
  await strategyStore.generateAi(minConfidence.value)
}

/** 售卖日切换:按新日期重拉清单与串关候选 */
async function handleDateChange(): Promise<void> {
  await strategyStore.fetchAiRecommendations()
}

async function handleConvert(pickId: number): Promise<void> {
  convertingIds.value = new Set(convertingIds.value).add(pickId)
  convertMessage.value = null
  try {
    const result = await convertAiPick(pickId, {
      stake_amount: stakes.value[pickId] ?? DEFAULT_STAKE,
    })
    convertMessage.value = result.created
      ? `已转为模拟决策 #${result.decision.decision_id},可在复盘中心查看结算`
      : `该推荐已转换过(决策 #${result.decision.decision_id})`
    // 转换状态与决策清单同步刷新
    await strategyStore.fetchAll()
  } catch (err) {
    convertMessage.value = err instanceof Error ? err.message : '转换失败'
  } finally {
    const next = new Set(convertingIds.value)
    next.delete(pickId)
    convertingIds.value = next
  }
}

/** EV 着色:正期望绿色、负期望红色 */
function evClass(ev: number): string {
  if (ev > 0) return 'ai-pick-table__ev--positive'
  if (ev < 0) return 'ai-pick-table__ev--negative'
  return ''
}

function formatTime(matchTime: string): string {
  return new Date(matchTime).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <div class="ai-pick-table">
    <div class="ai-pick-table__toolbar">
      <label class="ai-pick-table__field">
        <span>售卖日</span>
        <input
          v-model="aiBusinessDate"
          type="date"
          aria-label="售卖日筛选"
          title="缺省为当天;清空 = 查询最近生效批次"
          @change="handleDateChange"
        />
      </label>
      <label class="ai-pick-table__field">
        <span>置信度阈值</span>
        <select v-model.number="minConfidence">
          <option
            v-for="option in CONFIDENCE_OPTIONS"
            :key="option"
            :value="option"
          >
            {{ (option * 100).toFixed(0) }}%
          </option>
        </select>
      </label>
      <button
        class="ai-pick-table__generate"
        type="button"
        :disabled="isGenerating"
        @click="handleGenerate"
      >
        {{ isGenerating ? '生成中…' : '生成推荐' }}
      </button>
      <p v-if="aiBatch" class="ai-pick-table__summary">
        {{ aiBatch.business_date }} 批次 #{{ aiBatch.batch_id }}:
        入选 {{ aiBatch.pick_count }} 条 / 跳过 {{ aiBatch.skipped_count }} 条 /
        串关候选 {{ aiBatch.plan_count }} 个
      </p>
    </div>

    <p v-if="convertMessage" class="ai-pick-table__message" role="status">
      {{ convertMessage }}
    </p>

    <table class="ai-pick-table__table">
      <thead>
        <tr>
          <th>场次</th>
          <th>对阵</th>
          <th>玩法</th>
          <th>推荐</th>
          <th>置信度</th>
          <th>隐含</th>
          <th>EV</th>
          <th>凯利</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="pick in aiPicks" :key="pick.pick_id">
          <td>
            <div class="ai-pick-table__num">{{ pick.match_num_str }}</div>
            <div class="ai-pick-table__time">{{ formatTime(pick.match_time) }}</div>
          </td>
          <td>
            <div class="ai-pick-table__match">{{ pick.home_team_name }} vs {{ pick.away_team_name }}</div>
            <div class="ai-pick-table__league">{{ pick.league_name }}</div>
          </td>
          <td>{{ pick.play_name }}</td>
          <td>
            <div class="ai-pick-table__option">
              {{ pick.option_label }} @ {{ pick.odds.toFixed(2) }}
              <span
                v-if="pick.is_contrarian"
                class="ai-pick-table__contrarian"
                title="模型置信度低于市场隐含概率"
              >
                逆向
              </span>
            </div>
            <div class="ai-pick-table__reasoning" :title="pick.reasoning">
              {{ pick.recommendation }}
            </div>
          </td>
          <td>{{ (pick.confidence * 100).toFixed(0) }}%</td>
          <td>{{ (pick.implied_prob * 100).toFixed(0) }}%</td>
          <td :class="evClass(pick.ev)">{{ (pick.ev * 100).toFixed(1) }}%</td>
          <td>{{ (pick.kelly * 100).toFixed(1) }}%</td>
          <td>
            <template v-if="pick.decision_id !== null">
              <span class="ai-pick-table__done">已转决策 #{{ pick.decision_id }}</span>
            </template>
            <template v-else>
              <div class="ai-pick-table__convert">
                <input
                  v-model.number="stakes[pick.pick_id]"
                  type="number"
                  min="1"
                  max="10000"
                  :placeholder="String(DEFAULT_STAKE)"
                  aria-label="模拟注额"
                />
                <button
                  type="button"
                  :disabled="convertingIds.has(pick.pick_id)"
                  @click="handleConvert(pick.pick_id)"
                >
                  {{ convertingIds.has(pick.pick_id) ? '转换中…' : '转模拟决策' }}
                </button>
              </div>
            </template>
          </td>
        </tr>
        <tr v-if="aiPicks.length === 0">
          <td colspan="9" class="ai-pick-table__empty">
            暂无推荐 · 选择售卖日后点击「生成推荐」汇总该日各场最新 AI 分析
          </td>
        </tr>
      </tbody>
    </table>

    <p class="ai-pick-table__footer">
      EV = 置信度 × 赔率 − 1;隐含概率为去水归一口径。模拟投注 · 分析结果仅供参考,不构成投注建议。
    </p>
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.ai-pick-table {
  &__toolbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: vars.$spacing-lg;
    margin-bottom: vars.$spacing-md;
  }

  &__field {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;

    select {
      padding: vars.$spacing-xs vars.$spacing-sm;
      border: 1px solid vars.$color-border;
      border-radius: vars.$border-radius;
      background: vars.$color-surface;
    }
  }

  &__generate {
    padding: vars.$spacing-sm vars.$spacing-lg;
    border: none;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    color: #fff;
    cursor: pointer;

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }

  &__summary {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__message {
    margin: 0 0 vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    color: vars.$color-primary;
  }

  &__table {
    width: 100%;
    border-collapse: collapse;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-md;
      border-bottom: 1px solid vars.$color-border;
      text-align: left;
      vertical-align: top;
    }

    th {
      background: vars.$color-surface-hover;
      white-space: nowrap;
    }
  }

  &__num {
    font-weight: 600;
    white-space: nowrap;
  }

  &__time,
  &__league,
  &__reasoning {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__reasoning {
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__match {
    font-weight: 600;
    white-space: nowrap;
  }

  &__option {
    font-weight: 600;
    white-space: nowrap;
  }

  &__contrarian {
    margin-left: vars.$spacing-xs;
    padding: vars.$spacing-xs vars.$spacing-sm;
    border-radius: vars.$border-radius;
    background: vars.$color-warning;
    color: #fff;
    font-size: vars.$font-size-sm;
    font-weight: 400;
  }

  &__ev--positive {
    color: vars.$color-positive;
    font-weight: 600;
  }

  &__ev--negative {
    color: vars.$color-danger;
    font-weight: 600;
  }

  &__convert {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;

    input {
      width: 80px;
      padding: vars.$spacing-xs vars.$spacing-sm;
      border: 1px solid vars.$color-border;
      border-radius: vars.$border-radius;
    }

    button {
      padding: vars.$spacing-xs vars.$spacing-sm;
      border: 1px solid vars.$color-primary;
      border-radius: vars.$border-radius;
      background: vars.$color-surface;
      color: vars.$color-primary;
      cursor: pointer;
      white-space: nowrap;

      &:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
    }
  }

  &__done {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    white-space: nowrap;
  }

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
  }

  &__footer {
    margin: vars.$spacing-sm 0 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }
}
</style>
