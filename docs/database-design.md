# FortunePitch 数据库设计文档

> 权威来源:《智能足彩数据分析系统 (FortunePitch) 数据库设计文档.docx》(存放于 `docs/`)
> ORM 定义位置:`backend/app/models/`(SQLAlchemy 2.0 风格,模块对应文件)

## 0. 命名规范

所有表使用统一前缀,保证物理层面的模块化与高内聚:

| 前缀 | 模块 | ORM 文件 |
|------|------|----------|
| `fp_base_` | 基础档案模块 Base Module | `models/base.py` |
| `fp_match_` | 比赛与赛果模块 Match Module | `models/match.py` |
| `fp_analytics_` | 高阶数据分析模块 Analytics Module | `models/analytics.py` |
| `fp_strategy_` | 策略与赔率模块 Strategy Module | `models/strategy.py` |

## 1. ER 关系概览

```
fp_base_leagues ──< fp_base_teams ──< fp_base_players
        │                │      │
        │                └──┬───┘ (home/away)
        └────< fp_match_games ────< fp_match_events
                    │
                    ├──< fp_analytics_team_stats ──> fp_base_teams
                    ├──< fp_analytics_player_stats ──> fp_base_players
                    ├──< fp_strategy_odds_history
                    └──< fp_strategy_recommendations ──< fp_strategy_user_decisions
```

## 2. 基础档案模块(fp_base_)

### 2.1 fp_base_leagues 联赛信息表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| league_id | BIGINT | PK, 自增 | 联赛唯一标识 |
| league_name | VARCHAR(128) | 非空 | 联赛名称 |
| country | VARCHAR(64) | 非空 | 所属国家 |
| tier | INT | 默认 1 | 联赛级别(1=顶级, 2=次级) |
| season | VARCHAR(16) | 默认 "2025-2026" | 当前赛季标识 |

### 2.2 fp_base_teams 球队信息表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| team_id | BIGINT | PK, 自增 | 球队唯一标识 |
| team_name | VARCHAR(128) | 非空 | 球队名称 |
| league_id | BIGINT | FK -> fp_base_leagues, INDEX | 所属联赛 |
| stadium | VARCHAR(128) | 可空 | 主场馆名称 |
| manager | VARCHAR(64) | 可空 | 现任主教练 |
| formation | VARCHAR(8) | 可空 | 常规首发阵型(如 4-3-3) |

### 2.3 fp_base_players 球员信息表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| player_id | BIGINT | PK, 自增 | 球员唯一标识 |
| player_name | VARCHAR(128) | 非空 | 球员姓名 |
| team_id | BIGINT | FK -> fp_base_teams, INDEX | 效力球队 |
| position | VARCHAR(8) | 可空 | 场上位置(CB / CAM / ST) |
| birth_date | DATE | 可空 | 出生日期 |
| market_value | DECIMAL(15,2) | 可空 | 当前市场身价 |

## 3. 比赛与赛果模块(fp_match_)

### 3.1 fp_match_games 比赛基础信息表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| match_id | VARCHAR(64) | PK | 比赛全局唯一标识(外部数据源) |
| league_id | BIGINT | FK, INDEX | 所属联赛 |
| home_team_id | BIGINT | FK -> fp_base_teams | 主队 |
| away_team_id | BIGINT | FK -> fp_base_teams | 客队 |
| referee_id | BIGINT | 可空 | 主裁判 ID(暂存外部编号) |
| match_time | DATETIME | 非空 | 开赛时间 |
| match_status | ENUM | PENDING / LIVE / FINISHED | 比赛状态 |
| home_score | INT | 可空 | 主队全场比分(未完赛为 NULL) |
| away_score | INT | 可空 | 客队全场比分(未完赛为 NULL) |

### 3.2 fp_match_events 比赛事件表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| event_id | BIGINT | PK, 自增 | 事件唯一标识 |
| match_id | VARCHAR(64) | FK, INDEX | 关联比赛 |
| event_type | VARCHAR(32) | 非空 | GOAL / RED_CARD / YELLOW_CARD / SUBSTITUTION |
| event_minute | INT | 非空 | 发生时间(分钟) |
| player_id | BIGINT | FK -> fp_base_players, 可空 | 关联球员 |
| is_home_team | BOOLEAN | 默认 TRUE | 是否为主队事件 |

## 4. 高阶数据分析模块(fp_analytics_)

### 4.1 fp_analytics_team_stats 球队高阶指标表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| stat_id | BIGINT | PK, 自增 | 记录 ID |
| match_id | VARCHAR(64) | FK, INDEX | 关联比赛 |
| team_id | BIGINT | FK, INDEX | 球队 ID |
| xg | DECIMAL(5,2) | 可空 | 预期进球 xG |
| xga | DECIMAL(5,2) | 可空 | 预期失球 xGA |
| possession | DECIMAL(5,2) | 可空 | 控球率(0-100) |
| shot_accuracy | DECIMAL(5,2) | 可空 | 射门转化率 |
| ppda | DECIMAL(5,2) | 可空 | 防守压迫指数 |

### 4.2 fp_analytics_player_stats 球员单场表现表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| performance_id | BIGINT | PK, 自增 | 表现记录 ID |
| match_id | VARCHAR(64) | FK, INDEX | 关联比赛 |
| player_id | BIGINT | FK, INDEX | 球员 ID |
| minutes_played | INT | 可空 | 出场时间 |
| goals | INT | 默认 0 | 进球数 |
| assists | INT | 默认 0 | 助攻数 |
| key_passes | INT | 默认 0 | 关键传球 |
| rating | DECIMAL(4,2) | 可空 | 赛后综合评分 |

## 5. 策略与赔率模块(fp_strategy_)

### 5.1 fp_strategy_odds_history 赔率与盘口表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| odds_id | BIGINT | PK, 自增 | 记录 ID |
| match_id | VARCHAR(64) | FK, INDEX | 关联比赛 |
| bookmaker | VARCHAR(64) | 非空 | 机构名称 |
| market_type | VARCHAR(32) | 非空 | ASIAN_HANDICAP / EURO_ODDS / OVER_UNDER |
| initial_value | DECIMAL(8,3) | 非空 | 初盘水位/赔率 |
| current_value | DECIMAL(8,3) | 非空 | 即时水位/赔率 |
| update_time | DATETIME | 非空 | 更新时间 |

### 5.2 fp_strategy_recommendations 策略推荐记录表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| recommend_id | BIGINT | PK, 自增 | 推荐 ID |
| match_id | VARCHAR(64) | FK, INDEX | 关联比赛 |
| strategy_type | VARCHAR(32) | 非空 | WIN_DRAW_LOSS / HANDICAP / SCORE |
| predicted_outcome | VARCHAR(64) | 非空 | 推荐结果 |
| confidence_score | DECIMAL(4,2) | 非空 | 模型置信度(0.00-1.00) |
| logic_tags | JSON | 可空 | 推导逻辑标签(如 ["核心缺阵","盘口浅开"]) |
| created_at | DATETIME | 非空 | 策略生成时间 |

### 5.3 fp_strategy_user_decisions 用户决策记录表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| decision_id | BIGINT | PK, 自增 | 决策 ID |
| user_id | BIGINT | INDEX | 用户 ID(文档未定义用户表,暂存外部编号) |
| recommend_id | BIGINT | FK -> fp_strategy_recommendations | 关联系统推荐 |
| user_bet_type | VARCHAR(32) | 非空 | 用户选择的玩法 |
| stake_amount | DECIMAL(10,2) | 非空 | **模拟**注额(仅复盘统计用) |
| result_status | ENUM | WIN / LOSS / PUSH | 结算状态 |
| profit_loss | DECIMAL(10,2) | 可空 | 盈亏金额(系统结算,模拟数据) |

## 6. 设计说明

- **文档勘误**:原文档若干字段名存在排版丢字(首字母 s 丢失),
  实现已规范化:`eason -> season`、`tadium -> stadium`、`tat_id -> stat_id`、
  `trategy_type -> strategy_type`、`hot_accuracy -> shot_accuracy`、`take_amount -> stake_amount`。
- **比分 NULL 语义**:`home_score/away_score` 未完赛时为 NULL,
  由 `match_status` 区分状态(替代旧版用 -1 的方案)。
- **match_id 用 VARCHAR**:比赛标识来自外部数据源,非自增。
- **referee_id / user_id**:文档未定义裁判表与用户表,暂存外部编号,不做外键约束。
- 首次建表:`python -c "import asyncio; from app.core.database import init_db; asyncio.run(init_db())"`
