# 赛果采集与开奖页面实现计划

参考 https://www.sporttery.cn/jc/zqsgkj/(足球赛果开奖),实现:
1. 数据采集页新增"同步赛果"(输入日期)
2. 新增"赛果开奖"页面展示各玩法开奖结果

## 数据源(已探测验证)

接口:`GET https://webapi.sporttery.cn/gateway/uniform/football/getUniformMatchResultV1.qry`
参数:`matchBeginDate={date}&matchEndDate={date}&leagueId=&pageSize=30&pageNo=1&isFix=0&matchPage=1&pcOrWap=1`
(需浏览器 UA + Referer;total/pages 字段支持翻页)

单场关键字段:
- `matchId`(与 fp_match_games.match_id 一一对应,已验证 2041050 对上)、`matchNumStr`(周二002)、`leagueName`
- `homeTeam/allHomeTeam`、`awayTeam/allAwayTeam`
- `sectionsNo1` 半场比分("0:1")、`sectionsNo999` 全场比分("1:2");取消场次为"无效场次"/"取消"
- `winFlag`(H/D/A 胜平负结果)、`goalLine`(让球盘口)
- `h`/`d`/`a` 胜平负开奖 SP 值
- `poolStatus`(Payout=已开奖)

总进球/半全场/让球胜平负结果由比分 + 盘口自行推导(源站前端也是这么算的)。

## 后端

### 1. 源适配 `app/collector/sources/sporttery.py`
- 新增 `_MATCH_RESULT_PATH = "/gateway/uniform/football/getUniformMatchResultV1.qry"`
- `fetch_match_results(date: str) -> list[dict]`:拉取单日赛果,按 `total`/`pages` 翻页聚合,返回原始条目列表;网络/解析失败抛 `ExternalSourceError`

### 2. 解析器 `app/collector/parsers/result.py`(新文件)
- `_WDL_LABEL = {"H": "主胜", "D": "平", "A": "客胜"}`
- `derive_play_results(full_home, full_away, half_home, half_away, goal_line) -> dict`:
  纯函数,返回 `{had, hhad, crs, ttg, hafu}` 中文标签(如 "客胜"/"让球客胜"/"1:2"/"3"/"负负");
  hhad = 全场比分 + 让球盘口后判定;hafu = 半场结果 + 全场结果组合
- `build_result_fields(item) -> dict | None`:
  解析半/全场比分(取消/无效场次返回 None 比分但保留状态)、SP、winFlag 等;
  返回 `{match_id, match_num_str, league_name, home_team_name, away_team_name, half_home_score, half_away_score, full_home_score, full_away_score, had, hhad, crs, ttg, hafu, goal_line, sp_h, sp_d, sp_a, pool_status}`;
  `matchId` 缺失抛 `DataValidationError`

### 3. 模型 `app/models/match.py`
新表 `fp_match_results`(MatchResult),一场一行:
- `match_id` PK FK fp_match_games.match_id
- `match_num_str`、`goal_line`(String nullable)
- `half_home_score/half_away_score/full_home_score/full_away_score`(Integer nullable,取消场次为 NULL)
- `had/hhad/crs/ttg/hafu`(String nullable,中文标签)
- `sp_h/sp_d/sp_a`(Float nullable,胜平负开奖 SP)
- `pool_status`(String,如 Payout)
- `update_time`(DateTime)
- `game` relationship;MatchGame 增加 `result` 反向关系
- `app/models/__init__.py` 导出
- **对远程 MySQL 需手动跑一次 `init_db()` 建表**(无 alembic,create_all 只新增)

### 4. 同步 `app/collector/sync/result_sync.py`(新文件)
`sync_results_by_date(session, date) -> ResultSyncResult`:
- 拉取赛果 -> 逐条 build_result_fields
- 场次未入库(按 match_id 查不到 MatchGame)记入 `skipped_matches`
- 已入库:upsert MatchResult(get 更新 / add 新建),同时刷新 `MatchGame.home_score/away_score/match_status=FINISHED`(仅当比分有效)
- `ResultSyncResult(date, day_result_count, created_count, updated_count, game_updated_count, skipped_matches)`

### 5. API
- `app/api/v1/collector/schemas.py`:`ResultSyncRequest {date}`、`ResultSyncResultRead {date, day_result_count, created_count, updated_count, game_updated_count, skipped_matches, source}`
- `app/api/v1/collector/router.py`:`POST /collector/results/sync`(200)
- `app/api/v1/match/schemas.py`:`MatchResultRead {match_id, match_num_str, league_name, home_team_name, away_team_name, match_time, goal_line, half_score, full_score, had, hhad, crs, ttg, hafu, sp_h, sp_d, sp_a, pool_status}`
- `app/api/v1/match/router.py`:`GET /match/results?date=YYYY-MM-DD` -> list[MatchResultRead]
  (join MatchGame/League/Team 取名称,selectinload 避免懒加载;按 match_num_str 排序,无数据返回 [])

### 6. 测试 `tests/test_collector_result.py`(新文件,沿用 test_collector_match 的 fixture 模式)
- SAMPLE_RESULTS:正常场次 + 取消场次 + 未入库场次 + SP 缺失场次
- fetch_match_results monkeypatch
- 解析器单测:比分推导(含让球盘口、平局、取消场次)
- 同步:入库/upsert 幂等/game 比分与状态刷新/未入库跳过/取消场次不覆盖比分
- API:GET /match/results 返回列表;POST /collector/results/sync 返回计数

## 前端

### 7. API 层
- `src/api/collector/match.ts` 增加 `syncResults(date)` + `ResultSyncResult` 类型
- `src/api/match/result.ts`(新):`MatchResultItem` 接口 + `listMatchResults(date)`

### 8. 采集页 `src/views/collector/CollectorView.vue`
- 赛事同步卡片下新增"赛果同步"块:日期输入(默认当天)+ "同步赛果"按钮 + 结果展示(同步 N 场、更新比分 M 场、跳过说明)

### 9. 赛果开奖页面 `src/views/match/MatchResultsView.vue`(新)
- 顶部:日期选择(默认当天)+ 查询按钮 + "同步赛果"快捷按钮(调同一接口后刷新)
- 主体表格(参考 sporttery 开奖页布局):编号 | 联赛 | 主队(让球盘口) vs 客队 | 半场 | 全场 | 胜平负 | 让球 | 比分 | 总进球 | 半全场 | 胜平负SP(h/d/a)
- 开奖结果列高亮显示(橙色,与 sporttery 一致);取消场次灰色显示状态
- 空态:"该日期暂无赛果,请先同步"

### 10. 路由与导航
- `src/router/index.ts`:`/results` -> MatchResultsView
- `src/components/layout/AppSidebar.vue`:赛事中心后加 `{ label: '赛果开奖', route: '/results', icon: '🏆' }`

## 验证
- 后端:`pytest`(新增测试文件,保持全绿)
- 前端:`npm run type-check` + `npm run build`
- 远程 MySQL:跑一次 `init_db()` 建 fp_match_results 表
- 端到端:同步 2026-08-25 赛果(当天 13 场已开奖),验证 /match/results 与页面
