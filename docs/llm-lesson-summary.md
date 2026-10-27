# AI 复盘经验总结(共性经验归纳 + 综合分析注入)

## 功能概述

AI 分析页(`/ai-analysis`)顶部拆分为两个视图选项卡,
「AI 复盘总结」选项卡承载经验归纳闭环:

1. **总结(调 LLM 一次)**:取每场比赛**最近一次**赛事复盘(重新生成过
   复盘的场次不重复计),按复盘生成时间倒序取最近 30 场,把各场
   复盘总结与经验教训交给大模型做共性归纳,输出跨场次可复用的
   分析方法经验(5~10 条);
2. **落库保存**,页面展示最近一次(总结段落 + 经验条目 + 输入统计),
   历史总结可折叠查看;
3. **查看输入输出**:每次总结经 log_id 关联请求日志,可展开查看该次
   的完整提示词(system + user)与模型原始响应;
4. **注入综合分析**:后续调用 AI 综合分析(含赛事中心批量按钮)时,
   后端自动把最近一次经验总结注入提示词【历史复盘经验总结】段,
   用于校准分析方法。

合规:经验总结仅供改进分析方法参考,不构成投注建议。

## 数据表(1 张新表)

- **fp_match_llm_lesson_summaries**(每次总结一行,保留历史):
  summary_id / provider / model / summary(归纳总结)/ lessons(JSON,
  5~10 条)/ retrospect_count(输入覆盖场次数)/ total_hit、total_decided
  (输入复盘合计命中统计)/ log_id(FK fp_llm_request_logs,日志写失败
  为 NULL)/ created_at

## 后端

- 服务 `app/services/llm_lessons.py`:
  `collect_retrospect_samples`(每场最新复盘,max(retrospect_id) 分组
  子查询 + selectinload 比赛/联赛/球队)、`build_lesson_context`
  (POST 严格校验:无复盘 → 422「尚无已生成的 AI 复盘,无法总结经验…」)、
  `build_lesson_messages`、`_parse_lesson_summary`(经验上限 10 条)、
  `analyze_lessons`(analysis_type=lesson_summary,日志 match_id 常量
  `"lessons:summary"`)、`save_lesson_summary`、`list_lesson_summaries`
- 提示词要点(system):共性 = 至少两场复盘中出现同类问题或结论;
  区分"推理正确命中"与"运气命中";不得把偶发结果总结为规律;经验
  具体可执行、指向分析方法;输出 JSON `{summary, lessons}`
- `llm.py` 改动:`_write_request_log` 改为返回 log_id(int | None);
  `MatchAnalysisContext` 新增 lessons 字段;`build_match_analysis_context`
  加载最近一次总结(查询失败只降级不阻断);`build_analysis_messages`
  注入经验段 + system 规则 5(校准参考,与当前证据冲突时以当前数据
  为准,不得机械套用);新增 `get_latest_lesson_summary`(直接查模型,
  避免与 llm_lessons 循环依赖)
- 端点:
  - `GET /api/v1/match/llm-lesson-summaries` → 历史总结列表(倒序)
  - `POST /api/v1/match/llm-lesson-summaries` → 生成并落库
  - `GET /api/v1/match/llm-lesson-summaries/{summary_id}/request-log` →
    该次总结的完整请求日志(总结/日志不存在 404)

## 前端

- `src/api/match/analysis.ts`:`LlmLessonSummary` 类型 +
  `listLlmLessonSummaries` / `runLlmLessonSummary` / `getLlmLessonSummaryLog`
- `src/components/match/LessonSummaryPanel.vue`:生成按钮 + 最近一次
  总结卡片 + 可折叠历史列表,每条可展开查看输入提示词与模型原始响应
  (日志按需拉取并缓存);置于 `AiAnalysisView.vue` 的「AI 复盘总结」
  选项卡中(页面顶部两个视图选项卡:AI 分析结果 / AI 复盘总结,
  售卖日期与置信度筛选工具栏仅存在于「AI 分析结果」选项卡)
- `LlmLogViewer` 的 ANALYSIS_TYPE_LABELS 补 `lesson_summary: 'AI 复盘经验总结'`
- 综合分析注入为后端行为,前端零改动(赛事中心批量按钮自动生效,
  注入内容可在分析日志查看器中核对)

## 测试

- `tests/test_llm_lessons_api.py`(11 项):POST 422 无复盘 / 生成落库
  与统计聚合 / 每场只取最新复盘 / 历史倒序 / 请求日志回读
  (analysis_type=lesson_summary、match_id=lessons:summary)/ 404 未知
  总结 / 404 无关联日志 / 综合分析提示词注入(有总结含经验段与
  system 规则、无总结不含)/ 解析层超上限截断与空经验拒绝
- 基线:490 passed(479 + 11 新增)

## 边界与已知口径

- 注入对象固定为**最近一次**总结;重新总结后,后续综合分析自动
  使用新经验,历史总结保留
- 经验总结日志与业务表通过总结行上的 log_id 关联;日志先行提交,
  若总结落库失败会产生一条无引用的孤儿日志(与"日志必须独立于
  业务事务留存"的设计一致,低影响)
- 每场只计最新一次复盘,避免同场重复加权;输入上限 30 场
