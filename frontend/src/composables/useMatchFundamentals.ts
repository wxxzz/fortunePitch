import { computed, ref } from 'vue'
import { getTeamFundamentals, type TeamFundamentals } from '@/api/base/team'

/** 单维度战绩行(总/主/客同构) */
export interface FundamentalsLine {
  ranking: number | null
  played: number | null
  wins: number | null
  draws: number | null
  losses: number | null
  goals_for: number | null
  goals_against: number | null
  goal_diff: number | null
  points: number | null
  win_rate: number | null
}

/** 单支球队基本面(404=未同步,按无数据处理) */
async function fetchFundamentals(
  teamId: number,
): Promise<TeamFundamentals | null> {
  try {
    return await getTeamFundamentals(teamId)
  } catch {
    return null
  }
}

/** 总/主/客三维度字段同构,按前缀取对应字段 */
function toLine(
  f: TeamFundamentals,
  prefix: '' | 'home_' | 'away_',
): FundamentalsLine {
  const scoped = (
    total: number | null,
    home: number | null,
    away: number | null,
  ): number | null => (prefix === '' ? total : prefix === 'home_' ? home : away)
  return {
    ranking: scoped(f.ranking, f.home_ranking, f.away_ranking),
    played: scoped(f.played, f.home_played, f.away_played),
    wins: scoped(f.wins, f.home_wins, f.away_wins),
    draws: scoped(f.draws, f.home_draws, f.away_draws),
    losses: scoped(f.losses, f.home_losses, f.away_losses),
    goals_for: scoped(f.goals_for, f.home_goals_for, f.away_goals_for),
    goals_against: scoped(
      f.goals_against,
      f.home_goals_against,
      f.away_goals_against,
    ),
    goal_diff: scoped(f.goal_diff, f.home_goal_diff, f.away_goal_diff),
    points: scoped(f.points, f.home_points, f.away_points),
    win_rate: scoped(f.win_rate, f.home_win_rate, f.away_win_rate),
  }
}

/**
 * 双方球队基本面数据(联赛积分榜口径)。
 *
 * 由基本面 Tab 独占持有:比赛详情就绪后以双方 teamId 调用 load;
 * 未同步过基本面的球队按无数据处理。
 */
export function useMatchFundamentals() {
  const home = ref<TeamFundamentals | null>(null)
  const away = ref<TeamFundamentals | null>(null)
  const isLoading = ref(false)

  async function load(homeTeamId: number, awayTeamId: number): Promise<void> {
    isLoading.value = true
    try {
      ;[home.value, away.value] = await Promise.all([
        fetchFundamentals(homeTeamId),
        fetchFundamentals(awayTeamId),
      ])
    } finally {
      isLoading.value = false
    }
  }

  const season = computed(
    () => home.value?.season ?? away.value?.season ?? '',
  )

  /** 主队取主场维度,客队取客场维度(与本场对阵环境一致) */
  const homeHomeLine = computed(() =>
    home.value === null ? null : toLine(home.value, 'home_'),
  )
  const awayAwayLine = computed(() =>
    away.value === null ? null : toLine(away.value, 'away_'),
  )
  const homeTotalLine = computed(() =>
    home.value === null ? null : toLine(home.value, ''),
  )
  const awayTotalLine = computed(() =>
    away.value === null ? null : toLine(away.value, ''),
  )

  const has = computed(() => home.value !== null || away.value !== null)

  return {
    home,
    away,
    isLoading,
    load,
    season,
    homeHomeLine,
    awayAwayLine,
    homeTotalLine,
    awayTotalLine,
    has,
  }
}
