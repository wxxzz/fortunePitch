# 赛事中心页面重构计划(参考 MatchCenterView.html)

## 背景与目标

参考 [MatchCenterView.html](frontend/src/views/match/MatchCenterView.html) 原型(卡片式赛事 + 玩法标签 + 赔率选项 + 底部选注栏 + 确认弹窗),以**融合式布局**重构 [MatchCenterView.vue](frontend/src/views/match/MatchCenterView.vue):保留现有筛选区与右侧焦点推荐边栏,中间列表改为卡片式玩法赔率交互。

用户决策(已确认):
1. 布局:**融合式**(保留筛选区 + 边栏,卡片式列表)
2. 赔率:**同步真实赔率**(扩展 match_sync 落库竞彩 5 种玩法赔率)
3. 提交行为:**对接模拟决策**(确认后写入 fp_strategy_user_decisions)

## 已验证的数据事实

- 竞彩"混合过关计算器"接口 `GET /gateway/jc/football/getMatchCalculatorV1.qry?poolCode=HAD,HHAD,CRS,TTG,HAFU&channel=c` 返回全部 5 种玩法赔率:
  - `had`:h/d/a(胜平负)
  - `hhad`:h/d/a + goalLine(让球胜平负)
  - `crs`:s00s00…s05s02 + s1sh/s1sd/s1sa(比分 + 胜/平/负其他,共 31 项)
  - `ttg`:s0…s7(总进球,7 为 7+)
  - `hafu`:hh/hd/ha/dh/dd/da/ah/ad/aa(半全场 9 项)
- 该接口的 `matchId` 与现有在售赛程列表(`getMatchListV1.qry`)的 `matchId` **完全一致**(15/15 对齐),可直接关联已入库的 fp_match_games
- 项目无 alembic,`init_db()` 用 create_all → 只能**新增表**,不改已有表结构(fp_strategy_user_decisions.recommend_id 非空外键必须保留 → 确认投注时先建 Recommendation 再建 UserDecision)

## 后端改动

### 1. 数据源 `app/collector/sources/sporttery.py`
新增 `fetch_match_odds() -> list[dict]`:调用计算器接口,展平 matchInfoList,返回 `[{matchId, pools: {HAD:…, HHAD:…, …}, updateTime}]` 原始结构。

### 2. 解析器 `app/collector/parsers/match.py`(或新建 `parsers/odds.py`)
新增 `build_odds_record(sub) -> dict`:把 5 种玩法原始赔率归一化为统一选项结构:

```
pools = [
  {poolCode: "HAD",  playName: "胜平负",  goalLine: null, options: [{code:"h", label:"主胜", odds:2.15}, …]},
  {poolCode: "HHAD", playName: "让球胜平负", goalLine: "-1", options: [...]},
  {poolCode: "CRS",  playName: "比分",   options: [{code:"s01s02", label:"1:2", odds:17.0}, …, {code:"s1sh", label:"胜其他"}]},
  {poolCode: "TTG",  playName: "总进球",  options: [{code:"s0", label:"0"}, …, {code:"s7", label:"7+"}]},
  {poolCode: "HAFU", playName: "半全场",  options: [{code:"hh", label:"胜胜"}, …]},
]
```

仅保留有赔率值的玩法(某玩法未开售则该 pool 缺失)。

### 3. 模型 `app/models/match.py`
新增 `MatchOdds(fp_match_odds)` 表:
- `match_id`:主键 + FK fp_match_games
- `pools`:JSON(上述归一化结构)
- `update_time`:DateTime
- relationship 挂到 MatchGame(`odds`)

### 4. 同步 `app/collector/sync/match_sync.py`
`sync_matches_by_date` 在赛程入库后追加:调用 `fetch_match_odds()`,对**已存在**于 fp_match_games 的 matchId 幂等 upsert MatchOdds(不在库的跳过,避免外键错误);MatchSyncResult 增加 `odds_count` 字段。

### 5. API
- `match/schemas.py`:新增 `MatchOddsPoolRead` / `MatchOddsRead`;`MatchGameRead` 增加 `odds: MatchOddsRead | None = None`
- `match/router.py`:`list_games` / `get_game` 改为 join/selectinload MatchOdds 一并返回
- `strategy/router.py` + schemas:新增 `POST /strategy/user-decisions/batch`:入参 `{user_id, stake_amount, selections: [{match_id, strategy_type, predicted_outcome}]}`,服务端为每条 selection 创建 Recommendation(confidence_score=0.00, logic_tags=["用户自选"])+ UserDecision,返回创建的决策列表。strategy_type 映射:HAD→WIN_DRAW_LOSS、HHAD→HANDICAP、CRS→SCORE、TTG→TOTAL_GOALS、HAFU→HALF_FULL

### 6. 后端测试
- odds 解析器:5 种玩法归一化 + 空玩法剔除
- match_sync:同步后 MatchOdds 落库、重复同步幂等、未入库场次跳过(扩展 tests/test_collector_match.py,monkeypatch fetch_match_odds)
- batch 决策接口:创建成功、非法入参 422(tests/test_crud_api.py 或新文件)

## 前端改动

### 7. API 层
- `api/match/game.ts`:MatchGame 增加 `odds` 字段类型(`MatchOdds { pools: MatchOddsPool[] }`,`MatchOddsPool { poolCode, playName, goalLine?, options: {code,label,odds}[] }`)
- `api/strategy/userDecision.ts`:新增 `createDecisionsBatch()`

### 8. 选注状态 `stores/selection.ts`(新 Pinia store)
管理 `selections: Map<key, {matchId, matchName, poolCode, playName, optionCode, optionLabel, odds}>`、模式(单关/串关/混合)、增删/清空、预计总赔率计算(单关=各自独立,串关/混合=全乘积)。

### 9. 组件(按"小组件文件"规范拆分,components/match/)
- `MatchOddsCard.vue`:单场卡片 = 渐变头部(联赛|编号|时间|状态 + 主队 VS 客队 + 深度分析按钮)+ 玩法标签页 + 选项网格(label + 赔率,选中态高亮);仅展示有赔率数据的玩法;FINISHED 场次头部显示比分
- `SelectionBar.vue`:底部悬浮选注栏(已选计数、可删除标签、单关/串关/混合模式切换、查看方案按钮),仅在有选择时显示
- `BetConfirmModal.vue`:确认弹窗(逐条明细 + 模拟注额输入 + 预计总赔率 + 确认/取消),确认后调 batch 接口

### 10. 页面 `views/match/MatchCenterView.vue`
融合式布局:
- 保留:顶部筛选区(联赛/日期/五大联赛)、右侧 FocusRecommendCard 边栏
- 中间列表:替换现有行式列表为 MatchOddsCard 流(纵向卡片列表);移除演示赔率走势展开区(赔率数据已真实化,走势图留在深度分析页)
- 无赔率数据的场次(手动建的比赛):卡片只显示头部信息 + "暂无在售赔率"提示

### 11. 前端验证
- `npm run type-check` + `npm run build` 通过(项目无单测框架)

## 视觉风格

遵循项目设计令牌(styles/variables.scss 绿茵主题),不照搬原型的紫色渐变:
- 卡片头部:主色深绿渐变(rgba 层次),白字
- 选项按钮:白底描边,选中态绿底白字;赔率数字用 $color-positive 红
- 选注栏/弹窗:白底卡片 + 主色操作按钮,交互动画参考原型(fadeIn/slideUp)

## 实施顺序

1. 后端:源函数 → 解析器 → 模型 → sync → API(+测试)
2. 前端:API 类型 → selection store → 三个组件 → 页面重组
3. 全量验证:pytest + vue-tsc + vite build

## 风险与说明

- 用户自选会在 fp_strategy_recommendations 中产生 confidence_score=0.00 的记录(logic_tags=["用户自选"]),焦点推荐按置信度排序取前 3,不受影响;深度分析页推荐列表可能出现用户自选记录(标注"用户自选"标签可区分)
- 串关/混合模式的"预计总赔率"仅为展示计算;模拟决策按"每选项一条记录"建模,串关的组合结构化建模留待后续
- 计算器接口返回全部在售日,同步某日赛程时会顺带刷新所有已入库场次的赔率(幂等 upsert,无副作用)
