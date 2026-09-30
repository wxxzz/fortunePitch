# 球队全景档案 AI 维度分析记录(/teams)

> 完成日期:2026-09-29 · 需求:球队全景档案增加 AI 分析(进攻/防守/主场/客场等维度),
> 结果保存数据库新建表,AI 调用日志保存到 fp_llm_request_logs

## 设计口径

**模式镜像开发**:粒度从"比赛"改为"单支球队",整体镜像 `llm_fundamental.py` 五段式
(build_context → build_messages → analyze(三分支日志) → parse → save/get/list),
复用 `llm.py` 的服务商解析、网络调用与日志基础设施,不改动后者。

**固定六维度**(编码→展示名),每维评级 `strong/average/weak`(强/中/弱):
`ATTACK 进攻能力` / `DEFENSE 防守能力` / `HOME_FORM 主场表现` /
`AWAY_FORM 客场表现` / `RECENT_FORM 近期状态` / `OTHER 其他因素`;
另有整体 `summary` + `risks[]`。输出固定顺序,缺失维度补位"模型未给出该维度结论"。

**结果新表**(每次生成保留历史,建表走 create_all):
- `fp_llm_team_analyses`(`TeamLlmAnalysis`):analysis_id PK / team_id FK /
  provider / model / summary / risks(JSON) / created_at;dims relationship
  `cascade="all, delete-orphan", passive_deletes=True`
- `fp_llm_team_analysis_dims`(`TeamLlmAnalysisDim`):dim_id PK / analysis_id FK /
  dim_code / dim_title / rating / content;UniqueConstraint(analysis_id, dim_code)

**日志表复用 `fp_llm_request_logs`,不改表结构**(项目无 Alembic,现有 MySQL 表
不能加列):`match_id` 为 String(64) NOT NULL,球队分析写入 `team:{team_id}` 标识,
`request_params.analysis_type="team"` 与比赛类分析区分。

**上下文数据源**(均为已采集数据,缺失在提示词明示,要求模型声明数据不足且评级
average,不得臆造):Team + League + TeamProfile + TeamFundamentals(总/主/客三维,
渲染复用 `llm._format_fundamentals` 处理 Decimal)+ 近 10 场已赛 + 后 3 场未赛
(复用 `llm_fundamental._load_team_matches`)+ TeamRating(Elo,可缺)。

**端点放 base 模块**(资源归属球队):
- `POST /base/teams/{team_id}/llm-analysis` 生成并保存(404/503/502)
- `GET /base/teams/{team_id}/llm-analysis` 最近一次(未生成 404)
- `GET /base/teams/{team_id}/llm-analyses` 历史列表(倒序,最近 20 条)

证据权重/AI 综合分析链路不联动(球队分析是独立档案视角,不进比赛推荐权重)。

## 涉及文件

| 层 | 文件 | 内容 |
|---|---|---|
| 后端模型 | `backend/app/models/llm.py` | 新增 `TeamLlmAnalysis` + `TeamLlmAnalysisDim` 两表;`LlmRequestLog` docstring 说明 match_id 双语义 |
| 后端服务 | `backend/app/services/llm_team.py` | **新建**:上下文聚合 / 提示词构造 / 三分支日志调用 / 输出解析 / 落库与查询 |
| 后端 API | `backend/app/api/v1/base/schemas.py` | `TeamLlmAnalysisDimRead` / `TeamLlmAnalysisRead` |
| 后端 API | `backend/app/api/v1/base/router.py` | 三个端点(POST/GET latest/GET history)+ 修复遗漏的 `ResourceNotFoundError` 导入 |
| 后端测试 | `backend/tests/test_llm_team.py` | **新建** 19 个:提示词 / 解析鲁棒 / 上下文聚合 / 端点(落库、日志 match_id=`team:{id}`、404/503/502、历史倒序、解析失败保留原文) |
| 前端 API | `frontend/src/api/base/teamAnalysis.ts` | **新建**:类型 + `runTeamAnalysis` / `getLatestTeamAnalysis` / `listTeamAnalyses` |
| 前端 UI | `frontend/src/views/team/TeamProfileView.vue` | 「AI 维度分析」全宽面板:第四路并行加载(404 降级)、「生成 AI 分析」按钮(纳入 loadSequence 竞态守卫)、summary + 六维卡片(评级徽章:红=强/灰=中/绿=弱)+ 风险提示 + 模型/生成时间 |

## 关键实现细节

- `_parse_team` 鲁棒性:非法编码过滤、非法 rating 归一 average、缺失维度补位
  (rating=average)、全无效维度抛 `LlmServiceError`;日志走 `_write_request_log`
  独立会话(`_log_session_factory`),测试必须打桩到测试库
- 前端生成按钮:进行中禁用 + "分析生成中…"文案;切换球队时 `loadTeamProfile`
  重置 `analysis` / `isGenerating` / `analysisError`,过期响应按序号丢弃
- 数据缺口(积分榜/看板未同步)时按钮下方提示"分析仍可生成,但结论会声明数据不足"

## 验证

- 代码审查(code-reviewer):APPROVE,0 CRITICAL/HIGH;3 个 LOW 已全部修复
  (维度内容超长截断对齐 dim_content 列宽、补 `LlmNotConfiguredError` 导出、
  dimensions relationship 显式 order_by)。注:`llm_fundamental.py` 存在同样的
  超长未截断问题(既有问题,本次未动)
- 后端:`python -m pytest backend/tests -q` → **414 passed**(基线 395 + 新增 19)
- 前端:`npx tsc --noEmit` 通过;`npm run build` 通过
- 手动:/teams 选队 → 生成 AI 分析 → 六维卡片带评级;`fp_llm_team_analyses` 及 dims
  落库;`fp_llm_request_logs` 新增 `match_id=team:{id}` 的 SUCCESS(analysis_type=team)
