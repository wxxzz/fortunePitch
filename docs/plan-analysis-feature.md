# 投注方案分析功能实现记录(中奖概率 + 期望值)

> 完成日期:2026-09-24 · 需求:赛事中心投注方案功能增加分析,计算方案的中奖概率和期望值

## 需求与口径决策

- **概率口径(用户确认)**:赔率隐含概率(去水)——对某玩法全部在售选项
  `p_i = (1/odds_i) / Σ(1/odds_j)`,归一化消除返还率折扣。
  否决的备选:Poisson 模型概率(需手动 xG,无法全自动)、隐含概率+手动调整(复杂度过高)。
- 分析为**纯展示**,不改变提交流程;注额为模拟数据,不构成投注建议。

## 涉及文件

| 层 | 文件 | 内容 |
|---|---|---|
| 后端服务 | `backend/app/services/plan_analysis.py` | 核心概率/期望值数学(新建) |
| 后端 API | `backend/app/api/v1/strategy/schemas.py` | PlanSelectionItem / PlanAnalysisRequest / SelectionAnalysisRead / PlanAnalysisRead |
| 后端 API | `backend/app/api/v1/strategy/router.py` | `POST /api/v1/strategy/plan-analysis`(纯计算不落库,挂在 /bet-schemes 之后) |
| 后端测试 | `backend/tests/test_plan_analysis.py` | 21 个用例(新建) |
| 前端 API | `frontend/src/api/strategy/planAnalysis.ts` | `analyzeBetPlan()` + 类型(新建) |
| 前端 UI | `frontend/src/components/match/BetConfirmModal.vue` | 弹窗内嵌「方案分析」区 |

## 核心数学(重要,复核时看这里)

### 输入解析
- 赔率优先取 `fp_match_odds.pools` 当前值(按 match_id 批量查);库中无该玩法时
  回退勾选时点赔率、`p = 1/odds` **不归一**(注意:单选项归一会得 p=1,是 bug,勿改回)。
- 库中在售时,选项集合 = 库中选项 ∪ 勾选项(勾选项不在售时并入分母参与归一)。

### 单关(mode=single)
- `期望回报 = 注额 × Σ(p_i × odds_i)`;`EV = 期望回报 − 总投入`
- `中奖概率 = 1 − Π(1 − q_g)`,g 按 (场次,玩法) 分组、`q_g = 组内 Σ p_i`
  (同组互斥;同场不同玩法实际相关,跨组按独立近似——docstring 已注明)。

### 串关 N串1(mode=parlay/mixed,复式多选项)
- 注数/总投入/单注最高赔率:直接复用 `calculate_parlay`(含全部规则校验)。
- 每场定义:`q_m = Σ p_i`(该场被覆盖概率)、`S_m = Σ odds_i·p_i`。
- `期望回报 = 注额 × Σ_{C(M,N)组合} Π S_m` —— 精确(每注期望贡献 = 各场 odds·p 之积,
  复式对选项求和可分解到每场)。
- `中奖概率 = P(至少 N 场被覆盖) = Poisson-binomial 尾概率`(DP:`dp[k]`=恰好 k 场
  覆盖概率,倒序更新,`win_prob = Σ_{k≥N} dp[k]`)。
  **正确性**:复式枚举全部选项组合,任取 N 个已覆盖场次的实际赢家组合必为其中一注
  → 精确无近似。
- 兜底口径(不归一)下组内概率和可能 >1,汇总时截断到 1。

### 每选项输出
`implied_prob`(4dp)、`fair_odds = 1/p`、`ev_per_unit = p×odds − 1`、
`kelly_fraction`(复用 `poisson.kelly_fraction`,负期望为 0)。
汇总计算用**原始精度**概率,仅展示层四舍五入(先舍入再乘会累积误差)。

## 前端交互

- BetConfirmModal 打开后自动分析;watch [selectionList, mode, parlaySize, stakeAmount]
  **400ms 防抖**重新请求;`onBeforeUnmount` 清理定时器。
- 跳过条件:选注为空、串关规则不满足(invalidReason)、注额非法。
- 分析失败只显示轻提示,**不阻塞提交**。
- EV 着色遵循项目语义色:**红=正向**(`$color-positive`)、绿=负向(`$color-negative`),
  与 `$color-danger`(#c0392b)近似同色,勿用错。

## 关键数值特征(校验参考)

- 去水后单关 EV ≈ **−9.5%**(竞彩返还率约 90% 的折扣如实呈现);负 EV 时凯利=0。
- 串关 EV 随 N 按「返还率^N」递减,弹窗切换 2串1→3串1 可直观看到。
- 测试固定赔率:HAD 2.15/3.20/3.05(返还率 ≈ 90.5%)。

## 验证结果

- 后端:`python -m pytest -q` → **309 passed**(基线 288 + 新增 21)。
- 前端:`npx tsc --noEmit` 无错误;`npm run build` 成功。
- 手动路径:重启后端 → 赛事中心勾选(含复式)→ 查看方案 → 弹窗「方案分析」区,
  改注额/过关方式后指标自动刷新。
