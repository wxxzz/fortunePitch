# 赛事中心高阶数据实现记录(派生计算管线 + 详情页两 Tab + AI 上下文联动)

> 完成日期:2026-09-28 · 需求:赛事中心高阶数据采集与实现

## 需求与口径决策(用户确认)

- **数据来源 = 派生计算管线**:不新增外部数据源(500.com 明确禁用、understat 网络不可达),
  全部基于已采集 sporttery 数据实时派生:积分榜 `fp_base_team_fundamentals` + 看板赛果
  `fp_base_team_matches` → 近况 / H2H / Elo / 攻防强度 / 泊松概率
- **存储 = 混合**:仅 Elo 落库(新表每队一行当前值);近况/H2H/强度/泊松读时计算
- **联动 = 详情页两个 Tab + AI 综合分析上下文**;不改投注策略链路(证据权重 50/30/20 不变)

## 涉及文件

| 层 | 文件 | 内容 |
|---|---|---|
| 后端模型 | `backend/app/models/analytics.py` | `TeamRating`(fp_analytics_team_ratings,每队一行,FK fp_base_teams,不保留历史) |
| 后端服务 | `backend/app/services/team_rating.py` | Elo 回放管线:看板行按 uniform_match_id 分组→profile 解析主客→时间序回放→delete+insert 幂等全量重建(新建) |
| 后端服务 | `backend/app/services/insights.py` | 派生计算核心:近况/H2H(交叉过滤+去重+视角映射)/Dixon-Coles 强度/泊松预测/Elo 快照/`format_insights_summary`(新建) |
| 后端 API | `backend/app/api/v1/match/router.py` + `schemas.py` | `GET /match/games/{id}/insights?form_limit=6&h2h_limit=10` → `MatchInsightsRead.from_insights` |
| 后端 API | `backend/app/api/v1/analytics/router.py` + `schemas.py` | `POST /analytics/team-ratings/recompute` → 重算摘要 |
| 后端服务 | `backend/app/services/llm.py` | 上下文加 `insights_text`;聚合 try/except 只降级;提示词插入【高阶数据(系统模型派生,非外部数据)】段 |
| 后端测试 | `backend/tests/test_team_rating.py` | 7 用例:手算数值/零和/幂等/单侧看板/无 profile 跳过/组内比分不一致跳过/端点(新建) |
| 后端测试 | `backend/tests/test_insights.py` | 16 用例:近况手算/H2H 视角反转与去重/队名变体精确视角/强度手算 LGH=2.0/LGA=1.0→λ=3.0/泊松守恒/404/数据缺口/近况<3 场退化/端点(新建) |
| 后端测试 | `backend/tests/test_llm_analysis.py` | +2 用例:上下文含摘要与【高阶数据】段;insights 抛错时降级不阻断 |
| 前端 API | `frontend/src/api/match/insights.ts` | 类型镜像 schema + `getMatchInsights`(新建) |
| 前端 API | `frontend/src/api/analytics/teamRatings.ts` | `recomputeTeamRatings` + 摘要类型(新建) |
| 前端 UI | `frontend/src/views/match/MatchDetailView.vue` | 高阶数据 Tab 重构(Elo 卡/近况对比/强度表/泊松概率条)、历史交锋 Tab 从空占位落地;insights 懒加载(两 Tab 共享 payload);移除 teamStats 消费 |
| 前端 UI | `frontend/src/views/collector/CollectorView.vue` | 新增「派生数据 · 重算 Elo 评分」按钮与结果卡片 |

## 核心口径(重要,复核时看这里)

### 攻防强度(Dixon-Coles 强度比参数化)
```
LGH = Σ home_goals_for / Σ home_played   # 联赛主队场均(本联赛优先,全库兜底)
LGA = Σ away_goals_for / Σ away_played
rate = 0.70 × 赛季主客拆分值 + 0.30 × 近 N 场场均   # 近 N<3 退化为纯赛季值
A_h = home_scored/LGH  D_h = home_conceded/LGA  A_a/D_a 同理
λ = LGH × A_h × D_a    μ = LGA × A_a × D_h       夹逼 [0.2, 4.0]
```
- Numeric 字段读出为 Decimal,计算前一律 `float()`
- **数据缺口分级退化**:某队积分榜缺 → 该速率退化近况值 → 再缺退化联赛均值(强度 1.0);
  **全库无任何积分榜 → strength/poisson 整体 None**(不用全局常数编造预测,前端展示"数据不足")

### H2H 视角反转(易错点)
`TeamMatch` 同场比赛两队看板各存一行(共享 uniform_match_id)。H2H = 双向"对手=对方
uniform id"过滤 + `uniform_match_id` 去重。往绩行主客可能与本场相反,但**视角判定
不依赖队名字符串匹配**(队名可能存在简称/译名变体):由"行所属看板 team_id + 行内
`is_home`"精确推导——行来自本场主队看板且 is_home(或来自客队看板且非主队)时,
行主队即本场主队;否则 W/L 翻转、D 不变。明细 entry 带队名,前端按队名归属渲染。

### Elo 回放
- K=20 / HFA=100 / DEFAULT_ELO=1500,复用 `services/elo.py`
- 主客由看板行 `is_home` 确定,对手本地 ID 经 `TeamProfile.uniform_team_id` 解析;
  解析失败、主客同队、或**组内多行比分不一致**(脏数据)→ 跳过并计入 matches_skipped
- 幂等全量重建(delete + 批量 insert),仅手动端点触发,查询路径无写操作

### AI 联动容错
`build_match_analysis_context` 中 insights 聚合 try/except 全包裹:失败仅
`insights_text=None` + warning 日志,提示词输出"高阶数据暂不可用",不阻断 AI 主链路。

## 手动验证路径

1. 数据采集页:同步双方球队看板(积分榜+看板赛果入库)
2. 数据采集页「重算 Elo 评分」(或 `POST /api/v1/analytics/team-ratings/recompute`)
3. 赛事详情页「历史交锋」/「高阶数据」Tab 首次切入懒加载
4. 生成一次 AI 综合分析,`fp_llm_request_logs.request_messages` 含【高阶数据】段

## 验证结果

- 后端:`python -m pytest -q` → **393 passed**(基线 368 + 新增 25)
- 前端:`npx tsc --noEmit` 无错误;`npm run build` 通过
- 代码审查:2 个 HIGH 已修复(H2H 视角改精确判定、Elo 组内比分一致性校验)+
  watch 加 immediate;其余 MEDIUM/LOW 项评估后保持现状(全库兜底为既定口径、
  clearResults 命名与既有模式一致)
