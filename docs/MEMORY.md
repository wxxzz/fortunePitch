# Memory Index

- [500.com scraping techniques](500-com-scraping-techniques.md) - UA header, GBK decode, results/HT-score endpoints for jczq analysis
- [竞彩校准规则](jczq-betting-lessons.md) - H2H小样本限幅、稳胆层是生死位、让平相关性、逆向腿≤2条
- [投注方案分析功能](plan-analysis-feature.md) - 隐含概率(去水)口径、单关/串关中奖概率与期望值数学、POST /strategy/plan-analysis、弹窗分析区
- [复盘结算功能](retrospect-settlement-feature.md) - 结算引擎(HAD SP优先/串关实时计算)、POST /settlement、GET /review/stats|decisions、复盘页单页重构升级
- [赛事高阶数据功能](match-insights-feature.md) - 派生计算管线(近况/H2H视角反转/Dixon-Coles强度/泊松/Elo回放)、GET /match/games/{id}/insights、POST /analytics/team-ratings/recompute、详情页两Tab、AI上下文【高阶数据】段
- [球队档案页重构](team-profile-refactor.md) - /teams 全真实数据化(积分榜/看板/Elo三源并行加载缺失降级)、GET /analytics/team-ratings/{id}、删除演示雷达图、TeamTimeline xgDiff可选
- [球队AI维度分析](team-llm-analysis-feature.md) - 镜像llm_fundamental五段式(六维strong/average/weak)、新表fp_llm_team_analyses+dims、日志match_id="team:{id}"、POST/GET /base/teams/{id}/llm-analysis
- [联赛批量看板同步](league-dashboard-batch-sync.md) - /base 球队列表「批量同步看板」、本地已入库球队逐队sync_team_dashboard单队失败跳过、POST /collector/team-dashboard/sync-league、前端600s超时
- [AI策略推荐功能](ai-strategy-recommendation.md) - LLM分析→批次/单场/串关三表、逆向腿≤2、转决策桥接Recommendation、闭环结算、POST /strategy/ai-recommendations/generate
- [联赛看板页](league-dashboard.md) - /leagues 平铺卡片墙→单联赛看板(基本信息/积分榜/近期赛程赛果两选项卡)、Team左联Fundamentals NULLS LAST、GET /base/leagues/{id}/dashboard、多维度分析选项卡(已完赛场次统计:胜平负/进球/总进球/半全场/让球/热门命中,GET /base/leagues/{id}/insights)
- [比赛补充信息](match-extra-info.md) - 深度分析页"其他信息"Tab人工录入伤停/阵型(5000字上限/整体覆盖)、新表fp_match_extra_info、GET+PUT /match/games/{id}/extra-info、注入llm与llm_fundamental提示词
- [分析日志查看](llm-request-log-viewer.md) - AI分析Tab底部LlmLogViewer(fp_llm_request_logs零新表)、展开看请求参数/提示词/原始响应、GET /match/games/{id}/llm-request-logs、analysis_type派生(computed_field缺省回退analysis)
- [赛事复盘](match-llm-retrospect.md) - 赛事复盘Tab先比对AI推荐vs开奖(resolve_recommendation_hit归一化)再LLM归因出总结+经验、新表fp_match_llm_retrospects(+items快照)、GET/POST /match/games/{id}/llm-retrospect、analysis_type=retrospect、赛事中心批量AI复盘按钮(GET预检跳过未开场次)
- [AI复盘经验总结](llm-lesson-summary.md) - AI分析页手动触发生成:每场取最新复盘(≤30场)LLM归纳共性经验5~10条、新表fp_match_llm_lesson_summaries(log_id关联请求日志可查输入输出)、GET/POST /match/llm-lesson-summaries、analysis_type=lesson_summary(日志match_id="lessons:summary")、最近一次注入综合分析提示词【历史复盘经验总结】段、AI分析页两选项卡(AI分析结果/AI复盘总结)
- [深度分析页组件化重构](match-detail-refactor.md) - MatchDetailView按Tab拆7子组件(components/match/detail/)+每数据域一composable(composables/,useLlmResource通用三AI区块)、detail-shared.scss三mixin、KeepAlive缓存/复盘不缓存、analysisSettled跨Tab刷新日志
