/**
 * 串关组合计算(与后端 app/services/parlay.py 同口径)。
 *
 * 竞彩串关规则:N串1 从不同场次中任取 N 场组合;每场仅一种玩法
 * (同玩法多选项为复式)。注数 = 各 N 场组合的选项数乘积之和;
 * 单注最高赔率 = 组合内各场最高赔率乘积的最大值。
 * 此处仅用于确认弹窗预览,服务端保存时会重新计算。
 */
import type { OddsSelection } from '@/stores/selection'

/** 串关场次范围:2串1 ~ 8串1 */
export const MIN_PARLAY_SIZE = 2
export const MAX_PARLAY_SIZE = 8

/** 串关组合计算结果 */
export interface ParlayCalc {
  /** 总注数 */
  betCount: number
  /** 总投入 = 每注注额 x 总注数(此处不含注额,由调用方相乘) */
  /** 单注最高赔率 */
  maxOdds: number
  /** 已勾选的不同场次数 */
  matchCount: number
  /** 校验错误(同场多玩法等),为空表示可提交 */
  error: string
}

/** 按比赛分组选注,并校验每场仅一种玩法 */
function groupByMatch(selections: OddsSelection[]): Map<string, OddsSelection[]> {
  const groups = new Map<string, OddsSelection[]>()
  for (const item of selections) {
    const list = groups.get(item.matchId)
    if (list) {
      list.push(item)
    } else {
      groups.set(item.matchId, [item])
    }
  }
  return groups
}

/** 计算串关组合(注数/单注最高赔率),不满足串关规则时返回 error */
export function computeParlay(
  selections: OddsSelection[],
  parlaySize: number,
): ParlayCalc {
  const groups = groupByMatch(selections)
  const matchCount = groups.size

  for (const [matchId, list] of groups) {
    const poolCount = new Set(list.map((i) => i.poolCode)).size
    if (poolCount > 1) {
      return {
        betCount: 0,
        maxOdds: 0,
        matchCount,
        error: `同一场比赛仅允许勾选一种玩法:${list[0]?.matchName ?? matchId}`,
      }
    }
  }
  if (parlaySize > matchCount) {
    return {
      betCount: 0,
      maxOdds: 0,
      matchCount,
      error: `${parlaySize}串1 需要 ${parlaySize} 个不同场次,当前仅勾选了 ${matchCount} 场`,
    }
  }

  // 遍历 C(matchCount, parlaySize) 个组合:注数累加选项数乘积,赔率取各场最大
  let betCount = 0
  let maxOdds = 0
  const matchLists = Array.from(groups.values())
  const combo: OddsSelection[][] = []
  const walk = (start: number, depth: number): void => {
    if (depth === parlaySize) {
      betCount += combo.reduce((product, list) => product * list.length, 1)
      const odds = combo.reduce((product, list) => {
        return product * Math.max(...list.map((i) => i.odds))
      }, 1)
      maxOdds = Math.max(maxOdds, odds)
      return
    }
    for (let i = start; i <= matchLists.length - (parlaySize - depth); i++) {
      combo.push(matchLists[i]!)
      walk(i + 1, depth + 1)
      combo.pop()
    }
  }
  walk(0, 0)

  return { betCount, maxOdds, matchCount, error: '' }
}
