<script setup lang="ts">
/**
 * 基础档案管理视图:联赛 -> 球队 -> 球员 的层级导航与钻取。
 *
 * 布局依据《基础档案管理页面布局优化方案.md》:
 * - 面包屑实时展示当前层级路径,点击可回退
 * - 左侧可折叠树(联赛/球队/球员三级,懒加载)
 * - 主内容区按当前层级展示关联表格,支持"查看球队/查看球员"向下钻取
 * - 层级状态记录在 URL 查询参数(?league=&team=),刷新后保持
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { listTeams, type Team } from '@/api/base/team'
import { listPlayers, type Player } from '@/api/base/player'
import { useBaseStore } from '@/stores/base'

const route = useRoute()
const router = useRouter()
const baseStore = useBaseStore()
const { leagues, isLoading, error } = storeToRefs(baseStore)

// ---------- 层级状态(URL 查询参数驱动) ----------

function parseId(value: unknown): number | null {
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : null
}

const leagueId = computed(() => parseId(route.query.league))
const teamId = computed(() => parseId(route.query.team))

/** 当前层级:联赛列表 / 某联赛的球队列表 / 某球队的球员列表 */
const viewLevel = computed<'leagues' | 'teams' | 'players'>(() => {
  if (teamId.value !== null) return 'players'
  if (leagueId.value !== null) return 'teams'
  return 'leagues'
})

const currentLeague = computed(
  () => leagues.value.find((l) => l.league_id === leagueId.value) ?? null,
)

const currentTeam = computed(
  () => teamsByLeague.value.get(leagueId.value ?? -1)?.find((t) => t.team_id === teamId.value) ?? null,
)

function navigateTo(nextLeague: number | null, nextTeam: number | null): void {
  const query: Record<string, string> = {}
  if (nextLeague !== null) query.league = String(nextLeague)
  if (nextTeam !== null) query.team = String(nextTeam)
  void router.replace({ query })
}

// ---------- 懒加载数据缓存 ----------

const teamsByLeague = ref(new Map<number, Team[]>())
const playersByTeam = ref(new Map<number, Player[]>())
const isLoadingChildren = ref(false)

const currentTeams = computed(() => teamsByLeague.value.get(leagueId.value ?? -1) ?? [])
const currentPlayers = computed(() => playersByTeam.value.get(teamId.value ?? -1) ?? [])

async function loadTeams(targetLeagueId: number): Promise<void> {
  if (teamsByLeague.value.has(targetLeagueId)) return
  isLoadingChildren.value = true
  try {
    const teams = await listTeams({ league_id: targetLeagueId, limit: 100 })
    teamsByLeague.value = new Map(teamsByLeague.value).set(targetLeagueId, teams)
  } finally {
    isLoadingChildren.value = false
  }
}

async function loadPlayers(targetTeamId: number): Promise<void> {
  if (playersByTeam.value.has(targetTeamId)) return
  isLoadingChildren.value = true
  try {
    const players = await listPlayers({ team_id: targetTeamId, limit: 100 })
    playersByTeam.value = new Map(playersByTeam.value).set(targetTeamId, players)
  } finally {
    isLoadingChildren.value = false
  }
}

// ---------- 左侧树 ----------

const expandedLeagues = ref(new Set<number>())
const expandedTeams = ref(new Set<number>())

function toggleLeague(id: number): void {
  const next = new Set(expandedLeagues.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
    void loadTeams(id)
  }
  expandedLeagues.value = next
}

function toggleTeam(id: number): void {
  const next = new Set(expandedTeams.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
    void loadPlayers(id)
  }
  expandedTeams.value = next
}

/** 点击联赛节点:钻取到该联赛的球队列表 */
function openLeague(id: number): void {
  void loadTeams(id)
  expandedLeagues.value = new Set(expandedLeagues.value).add(id)
  navigateTo(id, null)
}

/** 点击球队节点:钻取到该球队的球员列表 */
function openTeam(league: number, team: number): void {
  void loadPlayers(team)
  expandedLeagues.value = new Set(expandedLeagues.value).add(league)
  expandedTeams.value = new Set(expandedTeams.value).add(team)
  navigateTo(league, team)
}

function openTeamDashboard(team: number): void {
  void router.push(`/base/team-dashboard/${team}`)
}

// ---------- 生命周期与联动 ----------

void baseStore.fetchAll()

/** URL 变化(刷新/回退/钻取)时,补齐当前层级的懒加载数据 */
watch(
  [leagueId, teamId],
  ([nextLeagueId, nextTeamId]) => {
    if (nextLeagueId !== null) {
      expandedLeagues.value = new Set(expandedLeagues.value).add(nextLeagueId)
      void loadTeams(nextLeagueId)
    }
    if (nextTeamId !== null) {
      expandedTeams.value = new Set(expandedTeams.value).add(nextTeamId)
      void loadPlayers(nextTeamId)
    }
  },
  { immediate: true },
)

function handleDeleteLeague(id: number): void {
  void baseStore.removeLeague(id).then(() => {
    if (leagueId.value === id) navigateTo(null, null)
  })
}
</script>

<template>
  <section class="base-data">
    <h2 class="base-data__title">基础档案管理</h2>

    <p v-if="error" class="base-data__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="base-data__hint">加载中…</p>

    <!-- 面包屑 -->
    <nav class="base-data__breadcrumb" aria-label="层级路径">
      <button class="base-data__crumb" type="button" @click="navigateTo(null, null)">
        基础档案管理
      </button>
      <template v-if="currentLeague">
        <span class="base-data__crumb-sep">›</span>
        <button class="base-data__crumb" type="button" @click="navigateTo(null, null)">
          联赛
        </button>
        <span class="base-data__crumb-sep">›</span>
        <button
          v-if="viewLevel === 'players'"
          class="base-data__crumb base-data__crumb--league"
          type="button"
          @click="navigateTo(leagueId, null)"
        >
          {{ currentLeague.league_name }}
        </button>
        <span v-else class="base-data__crumb base-data__crumb--current">
          {{ currentLeague.league_name }}
        </span>
      </template>
      <template v-if="currentTeam">
        <span class="base-data__crumb-sep">›</span>
        <button class="base-data__crumb" type="button" @click="navigateTo(leagueId, null)">
          球队
        </button>
        <span class="base-data__crumb-sep">›</span>
        <span class="base-data__crumb base-data__crumb--current">
          {{ currentTeam.team_name }}
        </span>
      </template>
    </nav>

    <div class="base-data__layout">
      <!-- 左侧层级树 -->
      <aside class="base-data__tree" aria-label="档案层级树">
        <div v-for="league in leagues" :key="league.league_id" class="base-data__tree-group">
          <div class="base-data__tree-row">
            <button
              class="base-data__tree-toggle"
              type="button"
              :aria-expanded="expandedLeagues.has(league.league_id)"
              @click.stop="toggleLeague(league.league_id)"
            >
              {{ expandedLeagues.has(league.league_id) ? '▾' : '▸' }}
            </button>
            <button
              class="base-data__tree-label base-data__tree-label--league"
              :class="{
                'base-data__tree-label--active': viewLevel !== 'leagues' && leagueId === league.league_id,
              }"
              type="button"
              :title="`${league.league_name}(${league.country} · ${league.season})`"
              @click="openLeague(league.league_id)"
            >
              <span class="base-data__tree-icon">🏆</span>
              {{ league.league_name }}
            </button>
          </div>

          <!-- 二级:球队(懒加载,展开联赛时显示) -->
          <div
            v-if="expandedLeagues.has(league.league_id)"
            class="base-data__tree-children"
          >
            <p v-if="isLoadingChildren" class="base-data__tree-empty">加载中…</p>
            <template v-else>
              <div
                v-for="team in teamsByLeague.get(league.league_id) ?? []"
                :key="team.team_id"
                class="base-data__tree-row"
              >
                <button
                  class="base-data__tree-toggle"
                  type="button"
                  :aria-expanded="expandedTeams.has(team.team_id)"
                  @click.stop="toggleTeam(team.team_id)"
                >
                  {{ expandedTeams.has(team.team_id) ? '▾' : '▸' }}
                </button>
                <button
                  class="base-data__tree-label base-data__tree-label--team"
                  :class="{
                    'base-data__tree-label--active': viewLevel === 'players' && teamId === team.team_id,
                  }"
                  type="button"
                  @click="openTeam(team.league_id, team.team_id)"
                >
                  <span class="base-data__tree-icon">🛡</span>
                  {{ team.team_name }}
                </button>
              </div>
              <p
                v-if="(teamsByLeague.get(league.league_id) ?? []).length === 0"
                class="base-data__tree-empty"
              >
                暂无球队
              </p>
            </template>

            <!-- 三级:球员(懒加载,展开球队时显示) -->
            <template
              v-for="team in teamsByLeague.get(league.league_id) ?? []"
              :key="`p-${team.team_id}`"
            >
              <div
                v-if="expandedTeams.has(team.team_id)"
                class="base-data__tree-children base-data__tree-children--deep"
              >
                <button
                  v-for="player in playersByTeam.get(team.team_id) ?? []"
                  :key="player.player_id"
                  class="base-data__tree-label base-data__tree-label--player"
                  type="button"
                  :title="`${player.player_name}${player.position ? ' · ' + player.position : ''}`"
                  @click="openTeam(team.league_id, team.team_id)"
                >
                  <span class="base-data__tree-icon">👤</span>
                  {{ player.player_name }}
                </button>
              </div>
            </template>
          </div>
        </div>
        <p v-if="leagues.length === 0" class="base-data__tree-empty">
          暂无联赛,请先在“数据采集”页同步
        </p>
      </aside>

      <!-- 主内容区 -->
      <div class="base-data__main">
        <!-- 联赛视图(默认) -->
        <template v-if="viewLevel === 'leagues'">
          <h3 class="base-data__section-title">联赛列表</h3>
          <table class="base-data__table">
            <thead>
              <tr>
                <th>ID</th><th>名称</th><th>国家</th><th>级别</th><th>赛季</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="league in leagues" :key="league.league_id">
                <td>{{ league.league_id }}</td>
                <td>{{ league.league_name }}</td>
                <td>{{ league.country }}</td>
                <td>{{ league.tier === 1 ? '顶级' : '次级' }}</td>
                <td>{{ league.season }}</td>
                <td>
                  <div class="base-data__row-actions">
                    <button
                      class="base-data__btn base-data__btn--league"
                      type="button"
                      @click="openLeague(league.league_id)"
                    >
                      查看球队
                    </button>
                    <button
                      class="base-data__btn base-data__btn--danger"
                      type="button"
                      @click="handleDeleteLeague(league.league_id)"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="leagues.length === 0">
                <td colspan="6" class="base-data__empty">暂无数据,可在“数据采集”页同步</td>
              </tr>
            </tbody>
          </table>
        </template>

        <!-- 球队视图 -->
        <template v-else-if="viewLevel === 'teams'">
          <h3 class="base-data__section-title">
            {{ currentLeague?.league_name }} · 球队
          </h3>
          <p v-if="isLoadingChildren" class="base-data__hint">正在加载球队…</p>
          <table v-else class="base-data__table">
            <thead>
              <tr>
                <th>ID</th><th>名称</th><th>主场</th><th>主教练</th><th>阵型</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="team in currentTeams" :key="team.team_id">
                <td>{{ team.team_id }}</td>
                <td>{{ team.team_name }}</td>
                <td>{{ team.stadium ?? '-' }}</td>
                <td>{{ team.manager ?? '-' }}</td>
                <td>{{ team.formation ?? '-' }}</td>
                <td>
                  <div class="base-data__row-actions">
                    <button
                      class="base-data__btn base-data__btn--team"
                      type="button"
                      @click="openTeam(team.league_id, team.team_id)"
                    >
                      查看球员
                    </button>
                    <button
                      class="base-data__btn base-data__btn--team"
                      type="button"
                      @click="openTeamDashboard(team.team_id)"
                    >
                      看板
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="currentTeams.length === 0">
                <td colspan="6" class="base-data__empty">
                  该联赛下暂无球队,可在“数据采集”页同步
                </td>
              </tr>
            </tbody>
          </table>
        </template>

        <!-- 球员视图 -->
        <template v-else>
          <h3 class="base-data__section-title">
            {{ currentTeam?.team_name }} · 球员
          </h3>
          <p v-if="isLoadingChildren" class="base-data__hint">正在加载球员…</p>
          <table v-else class="base-data__table">
            <thead>
              <tr>
                <th>ID</th><th>姓名</th><th>位置</th><th>出生日期</th><th>身价(€)</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="player in currentPlayers" :key="player.player_id">
                <td>{{ player.player_id }}</td>
                <td>
                  <span class="base-data__tree-icon base-data__tree-icon--player">👤</span>
                  {{ player.player_name }}
                </td>
                <td>{{ player.position ?? '-' }}</td>
                <td>{{ player.birth_date ?? '-' }}</td>
                <td>{{ player.market_value?.toLocaleString() ?? '-' }}</td>
              </tr>
              <tr v-if="currentPlayers.length === 0">
                <td colspan="5" class="base-data__empty">
                  该球队下暂无球员,可在“数据采集”页同步
                </td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>
    </div>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.base-data {
  max-width: 1280px;
  margin: 0 auto;

  &__title {
    margin: 0 0 vars.$spacing-md;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__hint {
    color: vars.$color-text-secondary;
  }

  // ---------- 面包屑 ----------

  &__breadcrumb {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: vars.$spacing-md;
    font-size: vars.$font-size-md;
  }

  &__crumb {
    border: none;
    background: transparent;
    padding: 2px vars.$spacing-xs;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-md;
    cursor: pointer;
    border-radius: 4px;

    &:hover {
      background: vars.$color-surface-hover;
      color: vars.$color-text-primary;
    }

    &--league {
      color: vars.$color-info;
    }

    &--current {
      color: vars.$color-text-primary;
      font-weight: 600;
      cursor: default;

      &:hover {
        background: transparent;
        color: vars.$color-text-primary;
      }
    }
  }

  &__crumb-sep {
    color: vars.$color-neutral;
  }

  // ---------- 左侧树 + 主内容 双栏 ----------

  &__layout {
    display: flex;
    gap: vars.$spacing-md;
    align-items: flex-start;
  }

  &__tree {
    width: 240px;
    flex-shrink: 0;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    padding: vars.$spacing-sm;
    max-height: 70vh;
    overflow: auto;
  }

  &__tree-group {
    margin: 0;
    display: flex;
    flex-direction: column;
  }

  &__tree-row {
    display: flex;
    align-items: flex-start;
  }

  &__tree-children {
    display: flex;
    flex-direction: column;
    padding-left: vars.$spacing-md;

    &--deep {
      padding-left: vars.$spacing-lg;
    }
  }

  &__tree-toggle {
    flex-shrink: 0;
    width: 20px;
    border: none;
    background: transparent;
    color: vars.$color-text-secondary;
    cursor: pointer;
    padding: 2px 0;
  }

  &__tree-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: none;
    background: transparent;
    padding: 2px vars.$spacing-xs;
    border-radius: 4px;
    color: vars.$color-text-primary;
    font-size: vars.$font-size-md;
    cursor: pointer;
    text-align: left;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 200px;

    &:hover {
      background: vars.$color-surface-hover;
    }

    &--league {
      color: vars.$color-info;
      font-weight: 600;
    }

    &--active {
      background: vars.$color-primary-light;
    }

    &--team {
      color: vars.$color-primary;
    }

    &--player {
      color: vars.$color-warning;
      font-size: vars.$font-size-sm;
    }
  }

  &__tree-icon {
    flex-shrink: 0;
  }

  &__tree-empty {
    margin: 0;
    padding: vars.$spacing-sm;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
  }

  // ---------- 主内容区 ----------

  &__main {
    flex: 1;
    min-width: 0;
  }

  &__section-title {
    margin: 0 0 vars.$spacing-sm;
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
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

  &__row-actions {
    display: flex;
    gap: vars.$spacing-xs;
  }

  &__btn {
    padding: vars.$spacing-xs vars.$spacing-sm;
    border-radius: vars.$border-radius;
    background: transparent;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &--league {
      border: 1px solid vars.$color-info;
      color: vars.$color-info;
    }

    &--team {
      border: 1px solid vars.$color-primary;
      color: vars.$color-primary;
    }

    &--danger {
      border: 1px solid vars.$color-danger;
      color: vars.$color-danger;
    }
  }

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
  }

  // ---------- 响应式:窄屏隐藏树,靠面包屑导航 ----------

  @media (max-width: 900px) {
    &__layout {
      flex-direction: column;
    }

    &__tree {
      display: none;
    }
  }
}
</style>
