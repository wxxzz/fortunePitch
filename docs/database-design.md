# FortunePitch 数据库设计文档

> ORM 定义位置:`backend/app/models/match.py`(SQLAlchemy 2.0 风格)

## 1. ER 关系概览

```
Team (1) ────< Match >──── (1) Team
                 │
                 └────< OddsRecord
```

## 2. 表结构

### 2.1 teams(球队)

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, 自增 | 主键 |
| name | VARCHAR(128) | UNIQUE, INDEX | 球队名 |
| elo_rating | FLOAT | 默认 1500.0 | Elo 评分,由 elo 服务维护 |
| league | VARCHAR(64) | 可空 | 所属联赛 |

### 2.2 matches(比赛)

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, 自增 | 主键 |
| external_id | VARCHAR(64) | UNIQUE, INDEX | 外部数据源编号,幂等导入 |
| league | VARCHAR(64) | INDEX | 联赛 |
| kickoff_at | DATETIME | 非空 | 开赛时间(带时区) |
| home_team_id | INTEGER | FK -> teams.id | 主队 |
| away_team_id | INTEGER | FK -> teams.id | 客队 |
| home_goals | INTEGER | 默认 -1 | 主队进球,-1 表示未开赛 |
| away_goals | INTEGER | 默认 -1 | 客队进球,-1 表示未开赛 |

### 2.3 odds_records(赔率快照)

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, 自增 | 主键 |
| match_id | INTEGER | FK -> matches.id, INDEX | 所属比赛 |
| captured_at | DATETIME | 非空 | 采集时间 |
| home_win_odds | FLOAT | 非空 | 主胜欧赔 |
| draw_odds | FLOAT | 非空 | 平局欧赔 |
| away_win_odds | FLOAT | 非空 | 客胜欧赔 |

## 3. 设计说明

- 一场比赛可对应多条赔率快照,用于还原市场预期的时间轨迹。
- `home_goals/away_goals` 用 `-1` 而非 `NULL` 区分"未开赛",简化类型约束。
- 默认使用 SQLite 开发库,生产环境通过 `DATABASE_URL` 环境变量切换。
