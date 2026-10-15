# 联赛看板(League Dashboard)

## 功能概述

左侧导航新增「联赛看板」入口:联赛以**平铺卡片墙**展示(国家 / 名称 /
级别 / 赛季),点击卡片进入单联赛看板,聚合展示:

- **基本信息**:国家、级别、赛季、已入库球队数;
- **积分榜(总榜)**:排名 / 赛 / 胜 / 平 / 负 / 进失球 / 净胜 / 积分 / 胜率,
  前 4 名(欧战区口径)着色强调;
- **近期赛程**(未完赛,开赛时间正序)与**近期赛果**(已完赛,倒序),
  行可点击进入比赛详情。

合规:仅提供数据分析参考,不构成投注建议。

## 数据来源(零新表,全部复用现有数据)

| 区块 | 来源 |
|---|---|
| 联赛卡片墙 | `fp_base_leagues`(GET /base/leagues,limit 100) |
| 积分榜 | `fp_base_teams` 左联 `fp_base_team_fundamentals`(数据采集页"同步基本面"写入) |
| 赛程/赛果 | `fp_match_games`(按 league_id 过滤,主客队名 join fp_base_teams) |

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

## 前端

- `src/api/base/leagueDashboard.ts`:类型 + getLeagueDashboard 封装
- `src/views/league/LeagueDashboardView.vue`:卡片墙(默认,`/leagues`)
  <-> 单联赛看板(`/leagues/:leagueId?`),路由参数变化时重拉,
  赛程/赛果行点击跳转 `/match/{match_id}`
- 路由 `/leagues/:leagueId?`(name: league-dashboard,可选参数);
  侧边栏 AppSidebar 在「赛果开奖」后新增「联赛看板」

## 测试

- `tests/test_league_dashboard_api.py`(3 项):看板聚合与排序断言
  (积分榜升序/未同步排末尾/赛果倒序/赛程正序/联赛隔离)、
  limit 参数、404
- 基线:459 passed(456 + 3 新增)

## 边界与已知口径

- 积分榜只有**总榜**;主/客分榜在球队看板(TeamDashboard)与比赛详情
  的基本面对比中展示,本页不重复
- 联赛卡片墙不做分页(limit 100),联赛档案规模(个位数~数十)下足够;
  超出时可改为搜索 + 分页
- 近期赛程条数默认 10,可经查询参数调整
