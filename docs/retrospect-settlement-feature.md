# 复盘结算功能实现记录(结算引擎 + 复盘中心真实数据)

> 完成日期:2026-09-24 · 需求:重新设计复盘功能,补齐结算引擎,接入真实数据

## 需求与口径决策

- **结算赔率来源(用户确认)**:不改表,结算时解析:
  - 单关决策:`UserDecision` 无下注赔率快照,HAD 优先用赛果 SP
    (`MatchResult.sp_h/d/a`),其余玩法用当前在售赔率(`fp_match_odds.pools`);
  - 串关方案:`BetSchemeItem` 已存赔率快照,总回报实时计算不落库
- **触发时机(用户确认)**:复盘页打开时自动结算 + 手动「立即结算」按钮
- **页面改版(用户确认)**:单页重构升级(真实 KPI + 盈亏曲线 + 维度分析 + 富明细表)

## 涉及文件

| 层 | 文件 | 内容 |
|---|---|---|
| 后端服务 | `backend/app/services/settlement.py` | 结算引擎:选项编码映射/命中判定/SP 优先赔率解析/单关&串关结算/实时盈亏计算(新建) |
| 后端服务 | `backend/app/services/review.py` | 复盘统计聚合:KPI/盈亏曲线/维度分析/富明细查询(新建) |
| 后端 API | `backend/app/api/v1/strategy/schemas.py` | `SettlementRequest`/`SettlementResultRead`/`ReviewKpiRead`/`ProfitPointRead`/`DimensionStatRead`/`ReviewStatsRead`/`ReviewDecisionRead`;扩 `BetSchemeItemRead`(result_label/is_hit)、`BetSchemeRead`(profit_loss) |
| 后端 API | `backend/app/api/v1/strategy/router.py` | `POST /settlement`、`GET /review/stats`、`GET /review/decisions`;`GET /bet-schemes` 增加读时结算注记 |
| 后端测试 | `backend/tests/test_settlement.py` | 59 个用例(新建):选项映射/命中判定/SP 优先级/单关赢输边界/串关全中部分/复式枚举/接口端点 |
| 前端 API | `frontend/src/api/strategy/review.ts` | `settleAll`/`getReviewStats`/`listReviewDecisions` + 类型(新建) |
| 前端 API | `frontend/src/api/strategy/betScheme.ts` | `BetSchemeItem` 增 `result_label/is_hit`,`BetScheme` 增 `profit_loss` |
| 前端 UI | `frontend/src/views/retrospect/UserDashboardView.vue` | 全面重写:结算触发/KPI 卡片/盈亏曲线/维度分析/决策明细/串关方案逐腿命中 |

## 核心口径(重要,复核时看这里)

### 命中判定(选项编码 -> 赛果标签)
`UserDecision.user_bet_type` 存 `"HAD:h"` 格式。
**静态映射**(镜像 `parsers/odds.py` 构造表,不依赖库中赔率):
- HAD/HHAD:`h→主胜 / d→平 / a→客胜`
- TTG:`s0..s6→"0".."6"`,`s7→"7+"`(边界:赛果总进球 ≥7 均命中 "7+")
- CRS:`s(\d{2})s(\d{2})→"H:A"`;`s1sh→胜其他 / s1sd→平其他 / s1sa→负其他`
- HAFU:`hh→胜胜 / hd→胜平 / ... / aa→负负`

判定复用 `llm_query._normalize_play_label`(剥"让球"前缀/"球"后缀)。

### 单关结算盈亏
- 命中:`profit = stake × (odds − 1)`;未中:`profit = −stake`(2dp)
- **odds 解析顺序**:HAD → 赛果 SP;否则 → 当前 `fp_match_odds.pools` 中该选项赔率;
  两者皆无 → 跳过(保持 PUSH,等下次结算)

### 串关方案结算与盈亏(实时计算,不落库)
- 明细已有赔率快照 + option_label → 逐腿命中判定(需全部腿赛果齐备)
- **赢的语义**(N串1 复式):存在任一 C(M,N) 场次组合,其中每场所选选项至少
  一个命中 → 该注中奖。方案 WIN = 存在中奖注
- **总回报 = stake × Σ_{中奖注} Π odds** = `stake × Π_{各场}(Σ_{命中选项} odds)`,
  分解到每场避免枚举单注(上限 1 万注规则仍有效,但计算复杂度为 O(M))
- `status` 落库 WIN/LOSS;`profit_loss` 读时实时计算

### 统计聚合
- **KPI**:总注数 = 单关决策数 + 串关方案数;命中率/盈亏只统计已结算记录;
  ROI = 累计盈亏 / 累计投入(全量)
- **盈亏曲线**:统一事件流 = 已结算单关 + 已结算串关方案,按比赛时间排序累计;
  串关方案事件时间 = max(明细 legs 的 match_time)
- **维度分析**:按玩法 / 按赔率区间(低<1.80 / 中1.80-2.50 / 高≥2.50)/ 按联赛,
  数据源 = 已结算单关决策 + 已结算串关明细逐腿;
  输出各维度 注数/命中数/命中率(不含盈亏,盈亏集中在 KPI 与曲线)

## 关键实现细节

### `compute_scheme_payout` 分解算法
```python
for combo in combinations(match_ids, parlay_size):
    payout += stake × Π(match_hit_sums[m] for m in combo)
```
其中 `match_hit_sums[m]` = 该场命中选项的赔率之和(未命中 = 0)。
正确性:复式对选项求和可分解到每场,与 `plan_analysis` 期望回报分解同构。

### 串关盈亏读时计算的三处复用
- `settlement.py:compute_scheme_payout`(结算引擎判定 WIN/LOSS)
- `settlement.py:scheme_profit`(结算服务算 profit)
- `settlement.py:load_scheme_annotations`(GET /bet-schemes 逐腿赛果/命中 + 方案盈亏)
- `review.py:_build_stats`(复盘统计聚合串关事件)

### 前端复盘中心交互
- `onMounted` 触发 `refresh()`:先 `settleAll()` → 并行加载 stats + decisions + schemes
- 结算失败不阻塞复盘数据展示(提示文案变更)
- 单关决策表支持状态筛选(全部/已赢/已输/待结算)客户端过滤
- 串关方案明细展开显示逐腿命中徽标(命中/未中/待赛果)

## 验证结果

- 后端:`cd backend && python -m pytest -q` → **368 passed**(基线 309 + 新增 59)
- 前端:`npx tsc --noEmit` 无错误;`npm run build` 成功
- 手动验证路径:
  1. 重启后端 → 赛事中心勾选若干选项(单关+串关)→ 同步赛果
  2. 打开 /retrospect → 自动结算 → KPI/曲线/维度/明细均为真实数据
  3. 「立即结算」可重复触发幂等;未开赛投注显示待结算
  4. 决策表状态筛选生效;串关方案明细展开显示逐腿命中徽标

## 已知限制

- **赔率口径为近似**(用户已确认):单关盈亏用结算时赔率,若下注后赔率变动
  会与真实回报有偏差;维度分析中单关决策赔率读时解析(同结算口径近似),
  串关明细用勾选时快照
- 串关 `profit_loss` 每次查询实时计算,列表/统计/结算共用 `compute_scheme_payout`
  保证三处一致
- `UserDecision` 无 `created_at`,排序统一用比赛 `match_time`(join MatchGame)
- IDE 中可能显示 "Cannot find module '@/api/strategy/review'" 等警告 —
  这是已知 TS 服务器缓存问题,tsc 实际无错误,可忽略
