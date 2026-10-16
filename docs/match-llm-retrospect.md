# 赛事复盘(大模型复盘总结)

## 功能概述

深度分析页新增「赛事复盘」Tab(排在「AI 分析」之后),对已完赛比赛做事后复盘:

1. **比对(系统计算,不调 LLM)**:最近一次 AI 综合分析的分玩法推荐
   vs 官方开奖结果,逐玩法命中比对(命中口径复用
   `llm_query.resolve_recommendation_hit`,归一化"让球"前缀/"球"后缀,
   与 AI 分析结果查询页一致);
2. **AI 复盘(调 LLM 一次)**:把开奖结果、赛前 AI 推荐与理由、比对
   结论,连同基本面/走势分析结论与人工录入补充信息(如有)作为归因
   上下文,要求模型输出复盘总结、逐玩法归因与经验教训;
3. **落库保存**,Tab 内展示(生成后切换为快照明细 + 归因)。

前置条件(不满足时按钮禁用并提示原因):赛果已同步且有开奖数据、
已生成过 AI 综合分析、存在已开奖玩法可比对。

合规:复盘仅供改进分析方法参考,不构成投注建议。

## 数据表(2 张新表)

- **fp_match_llm_retrospects**(主表,每次生成一行,保留历史):
  retrospect_id / match_id / analysis_id(被复盘的综合分析,溯源)/
  provider / model / summary(复盘总结)/ lessons(JSON,经验 1~5 条)/
  hit_count / total_count(命中统计,未开奖玩法不计入)/ created_at
- **fp_match_llm_retrospect_items**(比对明细,每玩法一行,快照式;
  (retrospect_id, play_code) 唯一):推荐/置信度/次选/理由为分析当时值
  快照,开奖结果为生成复盘时官方赛果快照,is_hit 命中标记,
  review 为大模型事后归因 —— 即使后续重新生成分析,历史复盘仍自洽。

## 后端

- 服务 `app/services/llm_retrospect.py`:
  `build_comparison`(逐玩法比对)、`load_retrospect_view`(GET 宽松口径)、
  `build_retrospect_context`(POST 严格校验:无赛果/无分析/无已开奖玩法
  → 422)、`build_retrospect_messages`、`analyze_retrospect`
  (复用 llm 模块的调用与日志基础设施,analysis_type=retrospect)、
  `save_retrospect`(主表 + 明细快照)、`get_latest_retrospect`
- 端点:
  - `GET /api/v1/match/games/{match_id}/llm-retrospect` →
    `LlmRetrospectViewRead`(result_available / analysis_available /
    comparison 实时比对预览 / retrospect 最近一次复盘或 null)
  - `POST /api/v1/match/games/{match_id}/llm-retrospect` →
    `LlmRetrospectRead`(生成并落库)
- 提示词要点(system):归因须区分"推理正确"与"运气命中";经验教训
  必须具体可执行、指向分析方法,禁止"下次注意"式空话,不得把偶然
  结果总结为规律;未开奖玩法跳过。输出 JSON:
  `{summary, playReviews:[{playCode, review}], lessons:[...]}`

## 前端

- `src/api/match/analysis.ts`:`LlmRetrospect*` 类型 +
  `getLlmRetrospectView` / `runLlmRetrospect`
- `src/components/match/MatchRetrospectPanel.vue`:比对表
  (玩法/AI 推荐(置信度)/开奖/命中✓✗/当时理由/事后归因)、
  命中统计、复盘总结卡、经验教训列表;`defineExpose({ refresh })`
- `MatchDetailView.vue` TABS 追加「赛事复盘」;`LlmLogViewer` 的
  ANALYSIS_TYPE_LABELS 补 `retrospect: 'AI 赛事复盘'`
- 赛事中心首页(MatchCenterView)批量工具栏追加「批量AI复盘」按钮
  (批量基本面/走势/综合分析之后):逐场 GET 复盘视图做前置校验
  (已开奖 + 已有综合分析 + 有可比对玩法),未满足自动跳过不计失败
  (预检接口异常则计失败),满足场次串行 POST 生成复盘;汇总文案含
  成功/总场次、跳过数、失败场次

## 测试

- `tests/test_llm_retrospect_api.py`(9 项):GET 404 / 缺失标记 /
  实时比对(含"3球"vs"3"归一化命中);POST 422 三种前置缺失 /
  生成落库快照与命中统计(非法玩法编码过滤、未覆盖玩法 review 为
  null)/ 生成后 GET 回读 / 请求日志 analysis_type=retrospect
- 基线:479 passed(470 + 9 新增;另修复 test_llm_team 一处固定日期
  随时间过期的断言,改为相对日期)

## 边界与已知口径

- 复盘对象固定为**最近一次**综合分析(以 analysis_id 溯源);重新生成
  分析后再次复盘将基于新分析,历史复盘快照不受影响
- 全部开奖字段为空的取消场次:实时预览照常返回,但生成按钮禁用
  (视为未开奖)
- 模型 playReviews 未覆盖的玩法 review 落 null,非法玩法编码过滤丢弃
