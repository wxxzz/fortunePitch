<script setup lang="ts">
/**
 * 页面C:球队全景档案(Team Profile)。
 * 顶部概览仪表盘 + 左侧六维雷达图 + 右侧近 10 场时间轴。
 */
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useBaseStore } from '@/stores/base'
import { useMatchStore } from '@/stores/match'
import TeamRadarChart, {
  type TeamDimension,
} from '@/components/team/TeamRadarChart.vue'
import TeamTimeline, {
  type TeamTimelineItem,
} from '@/components/team/TeamTimeline.vue'

const baseStore = useBaseStore()
const { teams } = storeToRefs(baseStore)

const matchStore = useMatchStore()
const { games } = storeToRefs(matchStore)

onMounted(() => {
  void baseStore.fetchAll()
  void matchStore.fetchGames()
})

const selectedTeamId = ref<number | null>(null)

const selectedTeam = computed(() =>
  teams.value.find((t) => t.team_id === selectedTeamId.value) ?? null,
)

const teamName = (teamId: number): string =>
  teams.value.find((t) => t.team_id === teamId)?.team_name ?? `#${teamId}`

/** 该队参与的比赛(含比分) */
const teamGames = computed(() =>
  games.value.filter(
    (g) =>
      (g.home_team_id === selectedTeamId.value ||
        g.away_team_id === selectedTeamId.value) &&
      g.home_score !== null,
  ),
)

/** 近 10 场时间轴(真实比赛 + 演示数据补充) */
const timelineItems = computed<TeamTimelineItem[]>(() => {
  const realItems: TeamTimelineItem[] = teamGames.value.slice(0, 10).map((g) => {
    const isHome = g.home_team_id === selectedTeamId.value
    return {
      opponent: teamName(isHome ? g.away_team_id : g.home_team_id),
      isHome,
      goalsFor: isHome ? (g.home_score ?? 0) : (g.away_score ?? 0),
      goalsAgainst: isHome ? (g.away_score ?? 0) : (g.home_score ?? 0),
      xgDiff: 0,
      date: new Date(g.match_time).toLocaleDateString(),
    }
  })
  if (realItems.length > 0) return realItems
  // 暂无完赛数据时的演示时间轴
  return [
    { opponent: '对手A', isHome: true, goalsFor: 2, goalsAgainst: 0, xgDiff: 1.4, date: '演示' },
    { opponent: '对手B', isHome: false, goalsFor: 1, goalsAgainst: 1, xgDiff: 0.2, date: '演示' },
    { opponent: '对手C', isHome: true, goalsFor: 3, goalsAgainst: 1, xgDiff: 1.1, date: '演示' },
    { opponent: '对手D', isHome: false, goalsFor: 0, goalsAgainst: 2, xgDiff: -0.8, date: '演示' },
  ]
})

/** 六维能力(演示数据,由高阶指标聚合后下发) */
const radarDimensions = ref<TeamDimension[]>([
  { name: '进攻', value: 78 },
  { name: '防守', value: 66 },
  { name: '控球', value: 82 },
  { name: '定位球', value: 61 },
  { name: '防守压迫', value: 70 },
  { name: '状态', value: 74 },
])

/** 概览指标 */
const overview = computed(() => [
  { label: '联赛排名', value: '待接入' },
  { label: '场均 xG', value: teamGames.value.length ? '统计中' : '1.82(演示)' },
  { label: '场均控球率', value: teamGames.value.length ? '统计中' : '58.4%(演示)' },
  { label: '近 10 场战绩', value: `${timelineItems.value.length} 场` },
])
</script>

<template>
  <section class="team-profile">
    <div class="team-profile__header">
      <h2 class="team-profile__title">球队全景档案</h2>
      <label class="team-profile__selector">
        <span>选择球队</span>
        <select v-model.number="selectedTeamId">
          <option :value="null">请选择</option>
          <option v-for="team in teams" :key="team.team_id" :value="team.team_id">
            {{ team.team_name }}
          </option>
        </select>
      </label>
    </div>

    <p v-if="!selectedTeam" class="team-profile__hint">请先选择一支球队查看全景档案。</p>

    <template v-else>
      <!-- 顶部概览 -->
      <header class="team-profile__overview">
        <div class="team-profile__identity">
          <span class="team-profile__badge">{{ selectedTeam.team_name.slice(0, 2) }}</span>
          <div>
            <strong class="team-profile__name">{{ selectedTeam.team_name }}</strong>
            <span class="team-profile__meta">
              {{ selectedTeam.formation ?? '阵型未知' }} ·
              主场 {{ selectedTeam.stadium ?? '未知' }} ·
              主教练 {{ selectedTeam.manager ?? '未知' }}
            </span>
          </div>
        </div>
        <div class="team-profile__metrics">
          <div v-for="metric in overview" :key="metric.label" class="team-profile__metric">
            <span class="team-profile__metric-label">{{ metric.label }}</span>
            <strong class="team-profile__metric-value">{{ metric.value }}</strong>
          </div>
        </div>
      </header>

      <div class="team-profile__body">
        <!-- 左侧雷达图 -->
        <div class="team-profile__panel">
          <h3 class="team-profile__section-title">六维能力</h3>
          <TeamRadarChart :dimensions="radarDimensions" />
          <p class="team-profile__hint">演示数据 · 高阶指标聚合接入后实时计算</p>
        </div>

        <!-- 右侧时间轴 -->
        <div class="team-profile__panel">
          <h3 class="team-profile__section-title">近 10 场赛果与 xG 差值</h3>
          <TeamTimeline :items="timelineItems" />
        </div>
      </div>
    </template>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.team-profile {
  max-width: 1080px;
  margin: 0 auto;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: vars.$spacing-md;
  }

  &__title {
    margin: 0;
  }

  &__selector {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;

    select {
      padding: vars.$spacing-xs vars.$spacing-sm;
      border: 1px solid vars.$color-border;
      border-radius: vars.$border-radius;
      background: #fff;
    }
  }

  &__hint {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__overview {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-lg;
    padding: vars.$spacing-lg;
    margin-bottom: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    flex-wrap: wrap;
  }

  &__identity {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
  }

  &__badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-lg;
    font-weight: 700;
  }

  &__name {
    display: block;
    font-size: vars.$font-size-lg;
  }

  &__meta {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__metrics {
    display: flex;
    gap: vars.$spacing-lg;
  }

  &__metric {
    display: flex;
    flex-direction: column;
    align-items: center;

    &-label {
      font-size: vars.$font-size-sm;
      color: vars.$color-text-secondary;
    }

    &-value {
      font-size: vars.$font-size-md;
    }
  }

  &__body {
    display: flex;
    gap: vars.$spacing-lg;
    align-items: flex-start;
  }

  &__panel {
    flex: 1;
    min-width: 0;
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__section-title {
    margin: 0 0 vars.$spacing-sm;
    font-size: vars.$font-size-md;
  }
}
</style>
