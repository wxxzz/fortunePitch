# 分析日志查看(大模型调用日志)

## 功能概述

深度分析页「AI 分析」Tab 底部新增**分析日志**区:按调用时间倒序展示本场的
大模型调用记录,点击条目展开可查看**请求参数、完整提示词(system + user)
与响应结果(模型原始输出)**,供排障与效果核对。

- 成功与失败调用均留痕(失败条目红边框 + 错误摘要/详情);
- 每条头部展示:状态徽章 / 调用类型 / 服务商与模型 / 调用时间 /
  耗时 / token 用量(共 N tokens,提示 X / 输出 Y);
- 生成 AI 分析后自动刷新(成功与失败都会写日志),也可手动"刷新"。

合规:日志仅供排障参考,不构成投注建议。

## 数据来源(零新表)

`fp_llm_request_logs`(models/llm.py `LlmRequestLog`):由
`llm._write_request_log` 在每次 LLM 调用后用**独立会话**写入并提交,
业务请求回滚也不影响日志留存。字段含 request_messages(完整提示词
JSON 数组)/ request_params / response_content(解析前原始输出)/
status / http_status / token 计量 / duration_ms / error_message /
error_detail / created_at。

注:match_id 列对球队维度分析存 `team:{team_id}` 标识;本功能按比赛
ID 精确匹配,球队维度日志不会串入。

## 后端

- 服务 `llm.list_request_logs(session, match_id, *, limit=20)`:按
  log_id 倒序
- 端点 `GET /api/v1/match/games/{match_id}/llm-request-logs`
  (limit 1~100,默认 20),响应模型 `LlmRequestLogRead`
- `analysis_type` 为响应上的 `computed_field`,从
  `request_params.analysis_type` 派生:analysis=综合分析 /
  fundamental=基本面 / odds_trend=赔率走势;早期综合分析日志未写该键,
  缺省回退为 `analysis`
- 顺带补齐:`llm.py`(综合分析)的 request_params 增加
  `"analysis_type": "analysis"`(fundamental 与 odds_trend 原本就有)

## 前端

- `src/api/match/analysis.ts`:`LlmRequestLog` 类型 +
  `listLlmRequestLogs(matchId, limit=20)`
- `src/components/match/LlmLogViewer.vue`:日志列表 + 点击展开明细
  (请求参数键值块 / 分角色提示词 `<pre>` / 原始输出 `<pre>`,
  长内容限高滚动);`defineExpose({ refresh })` 供父组件刷新
- `MatchDetailView.vue` AI 分析 Tab 底部挂载 `<LlmLogViewer>`;
  `handleRunAnalysis` 结束(含失败)后调用 `llmLogViewer.refresh()`

## 测试

- `tests/test_llm_request_logs_api.py`(4 项):倒序返回与完整载荷断言
  (提示词/参数/响应/token/耗时/错误信息;analysis_type 派生与缺省回退;
  球队维度日志不串入)、limit 参数、未知比赛 404、无日志空列表
- 基线:470 passed(466 + 4 新增)

## 边界与已知口径

- 日志只读不删,单次最多拉 100 条;历史综合分析日志(无
  analysis_type 键)统一显示为"AI 综合分析"
- response_content 是解析前的原始输出(含 JSON 围栏等),与页面上
  解析后的推荐展示互补
