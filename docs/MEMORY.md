# Memory Index

- [500.com scraping techniques](500-com-scraping-techniques.md) - UA header, GBK decode, results/HT-score endpoints for jczq analysis
- [竞彩校准规则](jczq-betting-lessons.md) - H2H小样本限幅、稳胆层是生死位、让平相关性、逆向腿≤2条
- [投注方案分析功能](plan-analysis-feature.md) - 隐含概率(去水)口径、单关/串关中奖概率与期望值数学、POST /strategy/plan-analysis、弹窗分析区
- [复盘结算功能](retrospect-settlement-feature.md) - 结算引擎(HAD SP优先/串关实时计算)、POST /settlement、GET /review/stats|decisions、复盘页单页重构升级
- [赛事高阶数据功能](match-insights-feature.md) - 派生计算管线(近况/H2H视角反转/Dixon-Coles强度/泊松/Elo回放)、GET /match/games/{id}/insights、POST /analytics/team-ratings/recompute、详情页两Tab、AI上下文【高阶数据】段
- [球队档案页重构](team-profile-refactor.md) - /teams 全真实数据化(积分榜/看板/Elo三源并行加载缺失降级)、GET /analytics/team-ratings/{id}、删除演示雷达图、TeamTimeline xgDiff可选
- [球队AI维度分析](team-llm-analysis-feature.md) - 镜像llm_fundamental五段式(六维strong/average/weak)、新表fp_llm_team_analyses+dims、日志match_id="team:{id}"、POST/GET /base/teams/{id}/llm-analysis
