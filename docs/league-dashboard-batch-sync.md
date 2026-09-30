# 按联赛批量同步球队看板记录(基础档案管理)

> 完成日期:2026-09-30 · 需求:基础档案管理增加按钮,选联赛后按该联赛的
> 球队名单批量同步球队看板数据

## 设计口径

- **取数范围(已与用户确认)**:仅本地已入库球队(`fp_base_teams` 中该联赛下的
  球队,即页面正在展示的名单),不重新拉取竞彩网球队清单;未同步过竞彩网档案
  (无 uniform_team_id 映射)的球队跳过并在结果中给出原因
- **单队失败不阻断整批**:逐队复用既有 `sync_team_dashboard`,捕获
  `DataValidationError / ResourceNotFoundError / ExternalSourceError` 计入
  `skipped_teams`("队名(原因)")后继续 —— 跳过语义与 `fundamental_sync` 一致
- **顺序循环不并发**:避免冲击竞彩网接口;每队约 4 次外部请求,20 队典型
  1-3 分钟,前端设 600s 专用超时 + "请勿关闭页面"提示
- **幂等**:重复同步仅更新并修剪失效未开赛行(由单队同步保证)

## 涉及文件

| 层 | 文件 | 内容 |
|---|---|---|
| 后端服务 | `backend/app/collector/sync/team_dashboard_sync.py` | 新增 `TeamDashboardLeagueSyncResult` NamedTuple + `sync_league_team_dashboards(session, *, league_id, term_limits=20)`:联赛 404 校验 → 按 league_id 枚举球队(team_id 升序)→ 逐队同步聚合计数;无球队返回 0 计数不抛 |
| 后端 API | `backend/app/api/v1/collector/schemas.py` | `TeamDashboardLeagueSyncRequest`(league_id 必填 + term_limits 1-100)/ `TeamDashboardLeagueSyncResultRead` |
| 后端 API | `backend/app/api/v1/collector/router.py` | `POST /collector/team-dashboard/sync-league`(单队端点之后) |
| 后端测试 | `backend/tests/test_collector_team_dashboard.py` | +9:`_restub_multi_team_sources`(按 uniform_team_id 键控多队打桩)+ `la_liga` fixture + `TestLeagueDashboardSync`(聚合计数 / 幂等二跑 / 无档案跳过 / 外部错误跳过 / 联赛 404 / 空联赛)+ `TestLeagueSyncApi`(200 聚合 + 幂等 / 404 / 401) |
| 前端 API | `frontend/src/api/collector/teamDashboard.ts` | `TeamDashboardLeagueSyncResult` 接口 + `syncLeagueTeamDashboards`(`LEAGUE_SYNC_TIMEOUT_MS = 600_000` 专用超时) |
| 前端 UI | `frontend/src/views/base/BaseDataView.vue` | 球队视图标题区「批量同步看板」按钮(currentTeams 非空时显示):`isSyncingDashboards` 互斥 + "批量同步中…"文案;结果消息(球队 X/Y + 各计数)+ ⚠ 跳过列表(role="status");错误走 error 展示 |

## 验证

- 代码审查(code-reviewer):WARNING → 修复后复审通过。1 HIGH 已修:每队用
  `session.begin_nested()` SAVEPOINT 包裹,失败球队回滚半途写入(否则"跳过"的
  球队其已 upsert 的档案/未来赛事行会随请求提交);测试断言被跳过球队落库行
  为空,并临时移除 SAVEPOINT 验证过断言有效性。2 MEDIUM 已修:前端同步状态绑定
  所属联赛(`syncTargetLeagueId`,切联赛不串显);测试失败点移到赛果拉取阶段
  (半途写入已发生之后)。LOW:测试变量更名 `team_ids_by_name`;"同步后不刷新
  球队列表"确认为可接受(看板同步不改变 fp_base_teams 行)
- 后端:`python -m pytest backend/tests -q` → **423 passed**(基线 414 + 新增 9)
- 前端:`npx tsc --noEmit` 通过;`npm run build` 通过
- 手动:/base 选联赛 → 球队列表点「批量同步看板」→ 结果消息含各计数;
  无档案映射的球队出现在 ⚠ 列表;`fp_base_team_matches` 各队看板行更新

## 风险与注意

- 长耗时单请求,不做流式进度(项目无 SSE/轮询基础设施,与既有批量端点行为一致)
- 长跑期间会话无整体 commit,每队 SAVEPOINT 成功释放后改动保留、失败即回滚;
  全部改动在请求成功后由会话依赖一次性提交,未捕获的 DB 异常整体失败回滚
  (SAVEPOINT 在 MySQL 生产与 SQLite 测试后端均验证可用)

## 上线后修复:批量同步 500(StaleDataError)

现象:league_id=22(亚运会男足)批量同步返回 500,traceback 为
`StaleDataError: UPDATE on fp_base_team_matches expected 1 row; 0 matched`。

根因(单队同步的潜伏 bug,批量首次引爆):生产会话 `autoflush=False`,
而修剪 DELETE 下推 DB 时,本轮赛果 upsert 只把比分标在 ORM 对象上、尚未落盘,
`full_home_score IS NULL` 读到旧值 → 刚完赛的原未来赛事行被误删 →
最终 flush 的 UPDATE 匹配 0 行抛 StaleDataError(不在领域异常捕获内)。
测试会话此前未显式关 autoflush(默认 True,自动落盘掩盖了时序),
故 423 项测试全绿仍在生产翻车。

修复(`team_dashboard_sync.py` + 测试):
- `_upsert_match` 新建行后立即 `flush` —— 兼防同一场比赛先后出现在
  未来赛事与赛果列表时,`session.get` 查不到 pending 行导致重复插入(UNIQUE 冲突)
- `sync_team_dashboard` 修剪 DELETE 前显式 `flush`,比分先落盘再修剪
- 测试 `session_factory` 对齐生产:`async_sessionmaker(..., autoflush=False)`,
  `test_future_row_updated_by_result` 即为回归用例(修复前该用例稳定复现两种失败)
- 端到端验证:直连生产库对联赛 22 逐队真实同步,24/25 队成功提交,
  1 队因赛果缺 `awayAbbCnName` 按设计跳过
