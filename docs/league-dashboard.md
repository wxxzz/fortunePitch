# 联赛看板(League Dashboard)

## 功能概述

左侧导航新增「联赛看板」入口:联赛以**平铺卡片墙**展示(国家 / 名称 /
级别 / 赛季),点击卡片进入单联赛看板,聚合展示:

- **基本信息**:国家、级别、赛季、已入库球队数;
- **积分榜(总榜)**:排名 / 赛 / 胜 / 平 / 负 / 进失球 / 净胜 / 积分 / 胜率,
  前 4 名(欧战区口径)着色强调;
- **近期赛程**(未完赛,开赛时间正序)与**近期赛果**(已完赛,倒序),
  行可点击进入比赛详情;
- **多维度分析**:对联赛内全部已完赛且有比分的场次做多维度统计
  (见下文「多维度分析」一节)。

单联赛看板以**选项卡**组织:「积分榜」(上述积分榜 + 赛程赛果)与
「多维度分析」;切换联赛时回到积分榜选项卡。

合规:仅提供数据分析参考,不构成投注建议。

## 数据来源(零新表,全部复用现有数据)

| 区块 | 来源 |
|---|---|
| 联赛卡片墙 | `fp_base_leagues`(GET /base/leagues,limit 100) |
| 积分榜 | `fp_base_teams` 左联 `fp_base_team_fundamentals`(数据采集页"同步基本面"写入) |
| 赛程/赛果 | `fp_match_games`(按 league_id 过滤,主客队名 join fp_base_teams) |
| 多维度分析 | `fp_match_games`(完赛比分)左联 `fp_match_results`(玩法标签与 SP) |

未同步基本面的球队排积分榜末尾、战绩字段为空(不隐藏,提示同步入口)。

## 后端

- 服务 `app/services/league_dashboard.py`:`get_league_dashboard(session,
  league_id, *, result_limit=10, fixture_limit=10)` 聚合返回
  LeagueDashboardData(NamedTuple:league / team_count / standings /
  recent_results / upcoming_fixtures)
- 排序口径:积分榜 `ORDER BY (ranking IS NULL), ranking, team_id`
  (MySQL/SQLite 通用 NULLS LAST 实现);赛果 `match_time DESC`;
  赛程 `match_time ASC`
- 端点 `GET /api/v1/base/leagues/{league_id}/dashboard`
  (result_limit / fixture_limit,1~50),响应模型 LeagueDashboardRead
  (schemas.py 新增 LeagueStandingRowRead / LeagueMatchRowRead)

## 多维度分析(insights)

对联赛内全部**已完赛且有比分**的场次(不限赛季)统计以下维度,
全部在服务层 Python 聚合(联赛场次规模小,无需 SQL 聚合):

| 维度 | 内容 |
|---|---|
| 胜平负分布 | 主胜/平/客胜计数与占比 |
| 进球 | 场均总进球及主/客拆分、3 球及以上占比(竞彩大小球 3 球线)、双方进球占比 |
| 总进球分布 | 0/1/2/3/4/5+ 六档,固定顺序 |
| 半全场分布 | 开奖标签计数,按次数降序、同频按标签排序 |
| 让球胜平负分布 | 固定顺序(让球主胜/让球平/让球客胜),仅非零项 |
| 热门命中 | 三项胜平负 SP 齐全的场次,取 SP 最低项为热门,统计其开奖命中率与热门项平均 SP |

- 服务 `app/services/league_insights.py`:`get_league_insights(session,
  league_id)` 返回 LeagueInsightsData(NamedTuple,占比在服务层计算,
  无场次时为 None)
- 端点 `GET /api/v1/base/leagues/{league_id}/insights`,响应模型
  LeagueInsightsRead(schemas.py 新增 LabelCountRead / LeagueFavoriteStatsRead);
  联赛不存在返回 404
- 前端 `src/api/base/leagueInsights.ts` + 
  `src/components/league/LeagueInsightsPanel.vue`:概览统计瓦片 +
  各维度条形分布 + 热门命中卡片,支持手动刷新;空数据/加载/错误态齐全
- 统计口径:仅 `match_status=FINISHED` 且比分非空的场次;半全场/让球/
  热门命中依赖赛果快照(`fp_match_results`),无快照的场次只参与
  比分维度统计

## 前端

- `src/api/base/leagueDashboard.ts`:类型 + getLeagueDashboard 封装
- `src/views/league/LeagueDashboardView.vue`:卡片墙(默认,`/leagues`)
  <-> 单联赛看板(`/leagues/:leagueId?`),路由参数变化时重拉,
  赛程/赛果行点击跳转 `/match/{match_id}`
- 单联赛看板页头「同步基本面」按钮:复用采集页
  `POST /collector/fundamentals/sync`(按联赛名称同步积分榜,
  120s 超时),完成后展示统计与跳过球队并自动刷新看板;
  传参为库内联赛全称(如"亚洲冠军精英联赛"),后端
  `find_league_item` 匹配链含"全称词元压缩推导简称"层
  (国家/地区与性质词按映射取短写,其余片段原样保留,
  结尾"联赛/大联盟"再生成删除与取首字变体,如
  "德国乙级联赛"->"德乙"、"亚洲冠军精英联赛"->"亚冠精英"、
  "欧洲国家联赛"->"欧国联"),解决全称与竞彩网列表简称
  既不相等也不互为子串导致 422 的问题;
  候选简称唯一精确命中才生效,歧义/未命中回退包含匹配,
  维持原有报错口径
- 页头「批量同步看板」按钮:与基础档案管理页同款,复用
  `POST /collector/team-dashboard/sync-league`(本地已入库球队逐队同步,
  600s 超时),结果消息按所属联赛守卫(切联赛不串显)并自动刷新看板
- 路由 `/leagues/:leagueId?`(name: league-dashboard,可选参数);
  侧边栏 AppSidebar 在「赛果开奖」后新增「联赛看板」;
  赛事中心赛事卡片的联赛名可点击进入对应联赛看板
  (MatchOddsCard 新增 leagueId 属性,无联赛档案时保持纯文本)

## 测试

- `tests/test_league_dashboard_api.py`(3 项):看板聚合与排序断言
  (积分榜升序/未同步排末尾/赛果倒序/赛程正序/联赛隔离)、
  limit 参数、404
- `tests/test_league_insights_api.py`(3 项):多维度统计断言
  (胜平负/进球/总进球/半全场/让球/热门命中、联赛隔离与未完赛排除)、
  空联赛零计数、404
- 基线:496 passed(493 + 3 新增)

## 边界与已知口径

- 积分榜只有**总榜**;主/客分榜在球队看板(TeamDashboard)与比赛详情
  的基本面对比中展示,本页不重复
- 联赛卡片墙不做分页(limit 100),联赛档案规模(个位数~数十)下足够;
  超出时可改为搜索 + 分页
- 近期赛程条数默认 10,可经查询参数调整
