<script setup lang="ts">
/**
 * 数据采集视图:从中国竞彩网同步 联赛 / 球队 / 球员 档案与在售赛程。
 *
 * 档案类同步按联赛名称手动触发,后端幂等 upsert;
 * 球队/球员同步会自动先同步联赛档案,可独立执行。
 * 赛事同步按售卖日触发,来源为竞彩网赛程赛果页。
 */
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import {
  syncLeague,
  syncPlayers,
  syncTeams,
  type LeagueSyncResult,
  type PlayerSyncResult,
  type TeamSyncResult,
} from '@/api/collector/league'
import {
  syncMatches,
  syncResults,
  type MatchSyncResult,
  type ResultSyncResult,
} from '@/api/collector/match'
import { useBaseStore } from '@/stores/base'

const baseStore = useBaseStore()
const { leagues, teams, players, isLoading } = storeToRefs(baseStore)

type SyncKind = 'league' | 'team' | 'player' | 'match' | 'result'

const leagueName = ref('西甲')
const matchDate = ref(todayIso())
const resultDate = ref(todayIso())
const isSyncing = ref(false)
/** 当前正在执行的同步类型(用于按钮态与提示文案) */
const syncingKind = ref<SyncKind | null>(null)
const syncError = ref<string | null>(null)

const leagueResult = ref<LeagueSyncResult | null>(null)
const teamResult = ref<TeamSyncResult | null>(null)
const playerResult = ref<PlayerSyncResult | null>(null)
const matchResult = ref<MatchSyncResult | null>(null)
const resultSyncOutcome = ref<ResultSyncResult | null>(null)

/** 快捷入口:竞彩网热门联赛简称 */
const QUICK_LEAGUES = ['西甲', '英超', '德甲', '意甲', '法甲'] as const

const canSubmit = computed(() => leagueName.value.trim().length > 0 && !isSyncing.value)
const canSubmitMatch = computed(() => matchDate.value !== '' && !isSyncing.value)
const canSubmitResult = computed(() => resultDate.value !== '' && !isSyncing.value)

const syncingHint = computed(() => {
  switch (syncingKind.value) {
    case 'league':
      return '正在从竞彩网拉取联赛信息…'
    case 'team':
      return '正在拉取联赛档案与积分榜球队清单…'
    case 'player':
      return '正在扫描比赛数据收集球员名单,可能需要数十秒…'
    case 'match':
      return '正在拉取竞彩网在售赛程…'
    case 'result':
      return '正在拉取竞彩网赛果开奖数据…'
    default:
      return ''
  }
})

/** 本地时区的今天(YYYY-MM-DD),避免 UTC 偏移导致日期错位 */
function todayIso(): string {
  const now = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

onMounted(() => {
  void baseStore.fetchAll()
})

/** 统一的同步执行入口:互斥执行,完成后刷新档案列表 */
async function runSync(kind: SyncKind, task: () => Promise<void>): Promise<void> {
  if (isSyncing.value) return
  if (kind !== 'match' && kind !== 'result' && !leagueName.value.trim()) return
  isSyncing.value = true
  syncingKind.value = kind
  syncError.value = null
  try {
    await task()
    await baseStore.fetchAll()
  } catch (err) {
    syncError.value = err instanceof Error ? err.message : '同步失败'
  } finally {
    isSyncing.value = false
    syncingKind.value = null
  }
}

/** 清空除 keep 外的同步结果卡片 */
function clearResults(keep: SyncKind): void {
  if (keep !== 'league') leagueResult.value = null
  if (keep !== 'team') teamResult.value = null
  if (keep !== 'player') playerResult.value = null
  if (keep !== 'match') matchResult.value = null
  if (keep !== 'result') resultSyncOutcome.value = null
}

function handleSyncLeague(): Promise<void> {
  return runSync('league', async () => {
    leagueResult.value = await syncLeague(leagueName.value.trim())
    clearResults('league')
  })
}

function handleSyncTeams(): Promise<void> {
  return runSync('team', async () => {
    teamResult.value = await syncTeams(leagueName.value.trim())
    clearResults('team')
  })
}

function handleSyncPlayers(): Promise<void> {
  return runSync('player', async () => {
    playerResult.value = await syncPlayers(leagueName.value.trim())
    clearResults('player')
  })
}

function handleSyncMatch(): Promise<void> {
  return runSync('match', async () => {
    matchResult.value = await syncMatches(matchDate.value)
    clearResults('match')
  })
}

function handleSyncResult(): Promise<void> {
  return runSync('result', async () => {
    resultSyncOutcome.value = await syncResults(resultDate.value)
    clearResults('result')
  })
}
</script>

<template>
  <section class="collector">
    <header class="collector__header">
      <h2 class="collector__title">数据采集 · 竞彩网档案同步</h2>
      <p class="collector__subtitle">
        数据来源:中国竞彩网。联赛/球队/球员档案来自联赛资料(sporttery.cn/zqlszl),
        在售赛程来自赛程赛果页(sporttery.cn/jc/zqszsc),赛果开奖来自
        赛果开奖页(sporttery.cn/jc/zqsgkj)。重复同步时更新已有记录。
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
          @keyup.enter="handleSyncLeague"
        />
        <div class="collector__actions">
          <button
            class="collector__btn"
            type="button"
            :disabled="!canSubmit"
            @click="handleSyncLeague"
          >
            同步联赛
          </button>
          <button
            class="collector__btn"
            type="button"
            :disabled="!canSubmit"
            @click="handleSyncTeams"
          >
            同步球队
          </button>
          <button
            class="collector__btn"
            type="button"
            :disabled="!canSubmit"
            @click="handleSyncPlayers"
          >
            同步球员
          </button>
        </div>
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

      <div class="collector__divider" role="separator"></div>

      <div class="collector__form">
        <label class="collector__label" for="match-date-input">售卖日期</label>
        <input
          id="match-date-input"
          v-model="matchDate"
          class="collector__input collector__input--date"
          type="date"
          :disabled="isSyncing"
        />
        <div class="collector__actions">
          <button
            class="collector__btn"
            type="button"
            :disabled="!canSubmitMatch"
            @click="handleSyncMatch"
          >
            同步赛事
          </button>
        </div>
      </div>
      <p class="collector__quick-label collector__match-hint">
        售卖日与竞彩赛程页的日期一致;次日凌晨开赛的比赛归属前一个售卖日。
        联赛与球队须已先入库,未入库的联赛会在结果中提示。
      </p>

      <div class="collector__divider" role="separator"></div>

      <div class="collector__form">
        <label class="collector__label" for="result-date-input">比赛日期(赛果)</label>
        <input
          id="result-date-input"
          v-model="resultDate"
          class="collector__input collector__input--date"
          type="date"
          :disabled="isSyncing"
        />
        <div class="collector__actions">
          <button
            class="collector__btn"
            type="button"
            :disabled="!canSubmitResult"
            @click="handleSyncResult"
          >
            同步赛果
          </button>
        </div>
      </div>
      <p class="collector__quick-label collector__match-hint">
        比赛日与竞彩赛果开奖页(sporttery.cn/jc/zqsgkj)的日期一致。
        场次须已在赛事档案中,比分有效的场次会同步回写比赛比分与完赛状态;
        同步后可在"赛果开奖"页查看各玩法开奖结果。
      </p>

      <p v-if="syncingHint" class="collector__hint">{{ syncingHint }}</p>
      <p v-if="syncError" class="collector__error" role="alert">{{ syncError }}</p>

      <!-- 联赛同步结果 -->
      <div v-if="leagueResult" class="collector__result">
        <div class="collector__result-head">
          <span class="collector__result-badge">
            {{ leagueResult.action === 'created' ? '新建档案' : '更新档案' }}
          </span>
          <strong>{{ leagueResult.league.league_name }}</strong>
          <span class="collector__result-source">来源:{{ leagueResult.source }}</span>
        </div>
        <dl class="collector__result-fields">
          <div>
            <dt>国家/地区</dt>
            <dd>{{ leagueResult.league.country }}</dd>
          </div>
          <div>
            <dt>级别</dt>
            <dd>{{ leagueResult.league.tier === 1 ? '顶级' : '次级' }}</dd>
          </div>
          <div>
            <dt>当前赛季</dt>
            <dd>{{ leagueResult.league.season }}</dd>
          </div>
          <div>
            <dt>竞彩联赛 ID</dt>
            <dd>{{ leagueResult.uniform_league_id }}</dd>
          </div>
        </dl>
      </div>

      <!-- 球队同步结果 -->
      <div v-if="teamResult" class="collector__result">
        <div class="collector__result-head">
          <span class="collector__result-badge">球队清单已同步</span>
          <strong>{{ teamResult.league.league_name }}</strong>
          <span class="collector__result-source">来源:{{ teamResult.source }}</span>
        </div>
        <dl class="collector__result-fields">
          <div>
            <dt>球队总数</dt>
            <dd>{{ teamResult.team_count }}</dd>
          </div>
          <div>
            <dt>新建</dt>
            <dd>{{ teamResult.created_count }}</dd>
          </div>
          <div>
            <dt>更新</dt>
            <dd>{{ teamResult.updated_count }}</dd>
          </div>
        </dl>
      </div>

      <!-- 球员同步结果 -->
      <div v-if="playerResult" class="collector__result">
        <div class="collector__result-head">
          <span class="collector__result-badge">球员名单已同步</span>
          <strong>{{ playerResult.league.league_name }}</strong>
          <span class="collector__result-source">来源:{{ playerResult.source }}</span>
        </div>
        <dl class="collector__result-fields">
          <div>
            <dt>覆盖球队</dt>
            <dd>{{ playerResult.team_count }}</dd>
          </div>
          <div>
            <dt>球员总数</dt>
            <dd>{{ playerResult.player_count }}</dd>
          </div>
          <div>
            <dt>新建 / 更新</dt>
            <dd>{{ playerResult.created_count }} / {{ playerResult.updated_count }}</dd>
          </div>
          <div>
            <dt>扫描场次</dt>
            <dd>{{ playerResult.matches_scanned }}</dd>
          </div>
        </dl>
        <p v-if="playerResult.skipped_teams.length > 0" class="collector__result-note">
          ⚠ 未取得球员数据的球队(如刚升级、当前赛季尚未完赛):{{
            playerResult.skipped_teams.join('、')
          }}
        </p>
      </div>

      <!-- 赛事同步结果 -->
      <div v-if="matchResult" class="collector__result">
        <div class="collector__result-head">
          <span class="collector__result-badge">赛事已同步</span>
          <strong>{{ matchResult.date }}</strong>
          <span class="collector__result-source">来源:{{ matchResult.source }}</span>
        </div>
        <dl class="collector__result-fields">
          <div>
            <dt>在售场次</dt>
            <dd>{{ matchResult.day_match_count }}</dd>
          </div>
          <div>
            <dt>新建赛事</dt>
            <dd>{{ matchResult.created_count }}</dd>
          </div>
          <div>
            <dt>更新赛事</dt>
            <dd>{{ matchResult.updated_count }}</dd>
          </div>
        </dl>
        <p
          v-if="matchResult.skipped_leagues.length > 0"
          class="collector__result-note"
        >
          ⚠ 以下联赛未入库已跳过,请先在上方同步对应联赛:{{
            matchResult.skipped_leagues.join('、')
          }}
        </p>
        <p
          v-if="matchResult.skipped_matches.length > 0"
          class="collector__result-note"
        >
          ⚠ 以下场次因球队未入库已跳过:{{
            matchResult.skipped_matches.join(';')
          }}
        </p>
      </div>

      <!-- 赛果同步结果 -->
      <div v-if="resultSyncOutcome" class="collector__result">
        <div class="collector__result-head">
          <span class="collector__result-badge">赛果已同步</span>
          <strong>{{ resultSyncOutcome.date }}</strong>
          <span class="collector__result-source">来源:{{ resultSyncOutcome.source }}</span>
        </div>
        <dl class="collector__result-fields">
          <div>
            <dt>已开赛场次</dt>
            <dd>{{ resultSyncOutcome.day_result_count }}</dd>
          </div>
          <div>
            <dt>新建赛果</dt>
            <dd>{{ resultSyncOutcome.created_count }}</dd>
          </div>
          <div>
            <dt>更新赛果</dt>
            <dd>{{ resultSyncOutcome.updated_count }}</dd>
          </div>
          <div>
            <dt>回写比分</dt>
            <dd>{{ resultSyncOutcome.game_updated_count }}</dd>
          </div>
        </dl>
        <p
          v-if="resultSyncOutcome.skipped_matches.length > 0"
          class="collector__result-note"
        >
          ⚠ 以下场次未入库已跳过:{{
            resultSyncOutcome.skipped_matches.join(';')
          }}
        </p>
      </div>
    </div>

    <h3 class="collector__section-title">
      已同步档案
      <span class="collector__section-meta">
        联赛 {{ leagues.length }} · 球队 {{ teams.length }} · 球员 {{ players.length }}
      </span>
    </h3>
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

  &__actions {
    display: flex;
    gap: vars.$spacing-sm;
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
    padding: vars.$spacing-sm vars.$spacing-md;
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

  &__divider {
    height: 1px;
    margin: vars.$spacing-lg 0 vars.$spacing-md;
    background: vars.$color-border;
  }

  &__match-hint {
    margin: vars.$spacing-xs 0 0;
  }

  &__input--date {
    flex: none;
    width: 180px;
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

  &__result-note {
    margin: vars.$spacing-sm 0 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-warning;
  }

  &__section-title {
    margin: vars.$spacing-lg 0 vars.$spacing-sm;
  }

  &__section-meta {
    margin-left: vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    font-weight: 400;
    color: vars.$color-text-secondary;
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
