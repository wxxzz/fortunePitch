/** W/D/L -> 结果圆点语义修饰符(红=胜=正向 / 灰=平 / 绿=负=负向,与项目色语义一致) */
export const RESULT_DOT_MODIFIER: Record<string, string> = {
  W: 'w',
  D: 'd',
  L: 'l',
}

/** 大模型服务商标识转展示名 */
export const PROVIDER_LABELS: Record<string, string> = {
  qwen: '阿里云千问',
  ark: '火山方舟',
}

/** 基本面维度优劣倾向 -> 展示名 */
export const EDGE_LABELS: Record<string, string> = {
  home: '主队占优',
  away: '客队占优',
  even: '势均力敌',
}

/** 概率(0~1)转百分比文本 */
export const pct = (value: number): string => `${(value * 100).toFixed(0)}%`

/** 时间串转 YYYY-MM-DD(非法串原样返回) */
export function formatMatchDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
