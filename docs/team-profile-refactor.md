# 球队全景档案页重构记录(/teams)

> 完成日期:2026-09-29 · 需求:优化重构球队档案页面(/teams)

## 需求与现状

原 `TeamProfileView.vue` 大量为演示数据:六维雷达图硬编码(进攻78/防守66/…)、
时间轴无数据时回退到"对手A-D"假赛程、真实行的 `xgDiff` 硬编码 0、
概览指标全是"待接入/统计中/演示"占位;且数据源错误地取自赛事中心的
matchStore(受单日售卖日筛选限制,只能看到当天比赛的球队)。

## 重构口径

**全部替换为真实数据源,缺失时降级提示,不再使用任何演示数据**:

| 数据 | 来源 | 缺失表现 |
|---|---|---|
| 球队身份(阵型/主场/主教练/队徽) | `GET /base/teams`(baseStore)+ 看板 `profile.logo_url` | 徽标回退首字圆形 |
| 赛季战绩(排名/积分/胜率/总/主/客) | `GET /base/teams/{id}/fundamentals`(积分榜) | 面板提示"未同步" |
| 近期赛果(W/D/L 串 + 时间轴) | `GET /base/teams/{id}/dashboard`(看板赛果) | 面板提示"未同步" |
| Elo 评分 | `GET /analytics/team-ratings/{id}`(**新端点**) | 指标显示 `--` |

- 六维雷达图(`TeamRadarChart.vue`)依赖 xG/控球/定位球等无采集管线的数据,
  **直接删除组件与引用**;原位置改为赛季战绩表(总/主/客 × 赛胜平负进失净胜积分胜率)
- `TeamTimeline` 的 `xgDiff` 改为可选(看板数据无 xG,缺失时隐藏该行,不再显示假的 0)
- 球队选择器改为按联赛 optgroup 分组(baseStore 全量球队,无需级联加载)
- 三路并行加载 `Promise.allSettled`:看板失败 = 页面错误;基本面 / Elo 404 = 仅降级为缺失,
  并在顶部"数据缺口"提示区引导去数据采集页补数据
- 近期状态条:W红/D灰/L绿圆点串 + X胜X平X负 + 连胜/连平/连败标签
  (结果直接取看板行 `team_result`,与详情页高阶数据同一口径)

## 涉及文件

| 层 | 文件 | 内容 |
|---|---|---|
| 后端 API | `backend/app/api/v1/analytics/router.py` | 新增 `GET /analytics/team-ratings/{team_id}` → `TeamRatingRead`(复用既有 schema,`crud.get_entity` 404 语义;与 POST `.../recompute` 无路由冲突) |
| 后端测试 | `backend/tests/test_team_rating.py` | +2:重算前 404 / 重算后返回评分(主>1500、客<1500) |
| 前端 API | `frontend/src/api/analytics/teamRatings.ts` | `TeamRating` 接口 + `getTeamRating` |
| 前端组件 | `frontend/src/components/team/TeamTimeline.vue` | `xgDiff` 可选化,条件渲染 |
| 前端 UI | `frontend/src/views/team/TeamProfileView.vue` | 整页重写(见上表口径) |
| 删除 | `frontend/src/components/team/TeamRadarChart.vue` | 演示数据专用组件,重写后无引用 |

## 手动验证路径

1. 数据采集页同步目标球队看板(积分榜+看板赛果入库)→ 重算 Elo 评分
2. 打开 /teams → 按联赛选择球队 → 概览指标、赛季战绩表、近期赛果均为真实数据
3. 选一支未同步球队 → 顶部数据缺口提示逐项引导,页面不报错不显示假数据

## 验证结果

- 后端:`python -m pytest -q` → **395 passed**(基线 393 + 新增 2)
- 前端:`npx tsc --noEmit` 无错误;`npm run build` 通过
- 代码审查:1 HIGH 已修复(快速切换球队时过期响应竞态 → 加载序号守卫,
  过期响应直接丢弃);1 MEDIUM 已修复(看板请求失败时错误信息与内容面板同时
  渲染 → 错误态优先);1 LOW 已修复(看板未同步提示文案改为"可能缺失",
  不再断言与 profile 无关的赛果一定缺失)
- 审查确认非问题:recompute 与 {team_id} 路由无冲突(方法不同);
  match_results 后端确认时间倒序;xgDiff=0 时 `!= null` 判断正确
