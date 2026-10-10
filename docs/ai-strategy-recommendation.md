# AI 策略推荐功能(AI 分析结果 → 单场推荐 + 自动串关 + 结算复盘闭环)

## 功能概述

打通"深度分析页 AI 分析"与"策略页推荐"两套平行体系:按售卖日汇总各场
**最近一次** AI 分析的分玩法推荐(`fp_match_llm_play_recs`),解析选项编码与
生成时点赔率,计算去水隐含概率 / EV / 凯利 / 逆向标记,落库为
**单场推荐清单** + **自动串关候选(2-4 串)**;用户可一键将推荐转为
模拟决策/模拟串关方案,直接进入现有结算/复盘闭环。

- 生成方式:策略页「生成推荐」按钮**手动触发**,可反复重算
  (同售卖日旧批次自动置 SUPERSEDED,历史保留,查询只看最新 ACTIVE 批次)
- 合规:全程"模拟投注"口径,分析结果仅供参考,不构成投注建议

## 数据模型(新建 3 表,零改动现有表)

| 表 | 说明 |
|---|---|
| `fp_strategy_ai_pick_batches` | 批次:business_date / min_confidence / pick_count / skipped_count / plan_count / status(ACTIVE/SUPERSEDED) |
| `fp_strategy_ai_picks` | 单场推荐:批次 FK / match_id / analysis_id(溯源)/ play_code / recommendation(LLM 原始文案)/ option_code+label+odds(生成时点快照)/ confidence / implied_prob / ev(=conf×odds−1)/ kelly / is_contrarian(=conf<implied)/ reasoning / decision_id(转决策后回填,幂等指针) |
| `fp_strategy_ai_parlay_plans` | 串关候选:批次 FK / parlay_size(2-4)/ plan_name+desc / **legs JSON 快照** / combined_odds(Πodds)/ combined_confidence(Πconf,独立近似)/ ev / kelly / contrarian_count / scheme_id(保存后回填) |

> 项目无 Alembic,`create_all` 只能加表;`fp_strategy_recommendations`
> 保留为转决策的桥接表(`UserDecision.recommend_id` 非空 FK 要求)。

## 核心口径

- **选项解析** `llm_query.resolve_recommendation_option(pools, play_code, recommendation)`:
  归一化精确(让球前缀/总进球"球"后缀)→ 原始 label 精确 → 最长子串回退
  → odds 可转 float 且 >0;现有 `resolve_recommendation_odds` 重构为薄包装
- **只落可行动推荐**:非 PENDING / 解析失败 / odds≤1 / 结算引擎无法静态映射
  编码(`settlement.resolve_option_label` 为 None)一律跳过,计入 skipped_count
- **串关构建** `_build_parlay_plans`:每场仅取 EV 最高代表腿(EV 并列取置信度,
  天然满足每场一玩法)→ chalk(顺向)/ value(逆向)分层 → 至多 4 档:
  稳胆 2串1 / 稳胆 3串1 / 稳胆 4串1(3 顺向+1 逆向)/ 价值混合 2串1;
  **硬约束逆向腿 ≤ 2**(jczq-betting-lessons 校准规则);腿不足的档位不硬凑
- **凯利钳制**:confidence 进 `poisson.kelly_fraction` 前钳制到 (0.001, 0.999)

## API(前缀 /api/v1/strategy)

| 端点 | 说明 |
|---|---|
| `POST /ai-recommendations/generate` | 生成/重算,body:{business_date?, min_confidence?=0.55},返回批次摘要(含 superseded_batch_ids) |
| `GET /ai-picks` | 单场推荐清单(默认最新 ACTIVE 批次,EV 倒序,分页,含场次/联赛/主客队富字段) |
| `GET /ai-parlay-plans` | 串关候选方案(最新 ACTIVE 批次) |
| `POST /ai-picks/{pick_id}/convert` | 转模拟决策(幂等,响应含 created 标记) |
| `POST /ai-parlay-plans/{plan_id}/convert` | 转模拟串关方案(幂等) |

## 转换契约(结算/复盘闭环零改动)

- **单场 → 决策**:动态建桥接 `Recommendation(strategy_type=POOL_TO_STRATEGY[play_code],
  predicted_outcome=option_label, logic_tags=["AI推荐", play_name])` +
  `UserDecision(user_bet_type="{play_code}:{option_code}")`,回填 decision_id;
  复盘侧通过 logic_tags 区分 AI 来源与用户自选
- **串关候选 → 方案**:legs JSON → `parlay.ParlayPick` 列表 →
  `parlay.save_bet_scheme`(每场一玩法/注数上限校验全复用),BetSchemeItem
  持有保存时点赔率快照
- 转换时二次校验:批次 ACTIVE + 比赛 PENDING(防"生成后开赛"窗口);
  HAD 结算优先赛果 SP 赔率,其余玩法用在售赔率

## 并发与删除口径(代码评审后加固)

- **转换/保存幂等指针用行锁**:两个 convert 服务入口以
  `SELECT ... FOR UPDATE` 锁定 AiPick / AiParlayPlan 行后再检查
  decision_id / scheme_id,并发的重复请求阻塞等待、提交后直接返回既有
  记录(MySQL InnoDB 生效;SQLite 测试方言忽略 FOR UPDATE)
- **批次失效移到插入之后**:generate_batch 先 INSERT 新批次再 UPDATE
  同日其他 ACTIVE 批次为 SUPERSEDED(排除自身),并发生成时
  "最后提交者"完成清理,收窄多 ACTIVE 批次窗口
- **幂等指针 FK 带 ondelete="SET NULL"**:删除用户决策/串关方案时
  自动置空 AiPick.decision_id / AiParlayPlan.scheme_id,
  恢复推荐的可转换状态(新表首建时生效,DELETE /user-decisions 不再被外键阻塞)

## 前端

- `src/api/strategy/aiPick.ts`:5 个 API 封装 + 类型
- `src/stores/strategy.ts`:aiPicks / aiPlans / aiBatch / isGenerating 状态,
  generateAi / fetchAiRecommendations 并入 fetchAll
- `src/components/strategy/AiPickTable.vue`:工具条(**售卖日筛选** + 置信度阈值下拉 +
  生成按钮 + 批次摘要)+ 推荐表(含 EV 着色/逆向标记/行内注额转决策,已转行置灰);
  售卖日与串关候选区共享筛选状态(缺省当天,切换即按该日生效批次重拉,
  清空取最近生效批次)
- `src/components/strategy/AiParlayPlanCard.vue`:候选方案卡片(逐腿 +
  组合指标 + 保存为模拟方案),含独立性近似与合规脚注
- `StrategyView.vue`:AI 推荐区替换为上述两子组件,其余三区不动
- `FocusRecommendCard.vue`:数据源优先 aiPicks(置信度前 3,含赔率快照),
  空时回退现有 recommendations;strategyLabel 补 TOTAL_GOALS/HALF_FULL

## 测试

- `tests/test_recommendation_engine.py`(17 项):resolve 匹配层、generate_batch
  (最新分析生效/阈值过滤/skipped 计数/EV 数值/重算 SUPERSEDED 幂等)、
  串关构建(每场一腿/腿不足跳档/组合乘积)、convert 幂等与 422/404
- `tests/test_ai_picks_api.py`(12 项):generate 200/422/默认日期、GET 清单、
  convert 幂等/404、**闭环集成**(生成→转换→结算→复盘统计,
  断言 SP 优先结算盈亏与 KPI 纳入 AI 来源记录)
- 基线:452 passed(423 存量 + 29 新增)

## 边界与已知近似

- 组合置信度按腿间独立近似(浅盘日让平存在相关性),候选 desc 与 UI 显式声明,
  不做概率修正(校准教训口径)
- 生成与转换之间开赛的窗口:转换时二次校验 PENDING 拦截
- **单次转换语义**:AiPick/AiParlayPlan 为全局批次数据,每条推荐只能被
  转换一次(user_id 维度不区分);当前为单用户场景,多用户需改为按用户
  分记录的关联表
- CRS 高赔腿:combined_odds Numeric(12,2) 覆盖;单选腿 bet_count=1 不触上限
