# 赛事深度分析页组件化重构记录(按 Tab 拆子组件 + 每数据域一 composable)

> 完成日期:2026-10-27 · 需求:拆分 1962 行的 MatchDetailView.vue

## 目标与结构

原 `frontend/src/views/match/MatchDetailView.vue` 单文件承载 8 个 Tab 的全部
模板、脚本与样式(1962 行)。本次按「每个 Tab 一个子组件 + 每个数据域一个
composable」拆分,父视图保留薄壳职责:比赛详情拉取、顶部对战卡片、
Tab 导航与子组件装配。

### composables(`frontend/src/composables/`,新建目录)

| 组合函数 | 数据域 | 归属 |
|---|---|---|
| `useMatchInsights(matchId)` | 高阶数据/历史交锋共享 payload(懒加载,load 自带已加载/加载中守卫) | 父级持有,两 Tab 经单一 `state` prop 共享;返回 reactive 捆绑对象 |
| `useMatchExtraInfo(matchId)` | 其他信息表单(加载/保存/dirty/保存提示) | 父级持有(顶部对战卡片阵型摘要与录入 Tab 共用一份表单);返回 reactive 捆绑对象 |
| `useMatchFundamentals()` | 双方球队基本面 + 总/主/客三维度行 | 基本面 Tab 自持 |
| `useOddsTrend(matchId)` | 赔率快照 + 玩法/序列/点位 | 赔率走势 Tab 自持 |
| `useLlmResource(matchId, options)` | 通用大模型资源(run 生成/loadSaved 静默拉取最近一次,错误兜底) | AI 分析/AI 基本面/AI 走势三个分析区块共用 |

### Tab 子组件(`frontend/src/components/match/detail/`,新建目录)

StrategyTab(默认 Tab,读策略 store)/ AdvancedTab / H2HTab /
OddsTrendTab / FundamentalsTab / ExtraInfoTab / AiAnalysisTab;
赛事复盘沿用既有 `MatchRetrospectPanel`。

- 共享常量与展示辅助:`detail/constants.ts`(RESULT_DOT_MODIFIER、
  PROVIDER_LABELS、EDGE_LABELS、pct、formatMatchDate)
- 共享样式:`detail-shared.scss` 三个 mixin——`panel`(面板布局 +
  section-title/hint/error/risks/form-dot/table)、`actions`(工具条/按钮)、
  `llm`(摘要卡/分玩法卡/置信度条);各组件 scoped 样式在自己的 BEM 块
  选择器下 `@include`,元素类名使用各自块前缀(如 `advanced-tab__hint`)

### 关键接线

- **KeepAlive 缓存**:7 个 Tab 组件包在 `<KeepAlive>` 内,切换不丢状态
  (与重构前单组件内 v-if 的行为等价);赛事复盘面板在 KeepAlive 外,
  保持「重进刷新」的原有语义
- **懒加载时机不变**:insights 仍由父级 watch(activeTab) 触发;赔率快照、
  基本面、已保存分析(走势/基本面/综合)改为各 Tab onMounted 触发
  (KeepAlive 下仅首次进入触发,等价于原懒加载)
- **跨 Tab 日志刷新**:AiAnalysisTab `defineExpose({ refresh })` 委托内部
  LlmLogViewer;基本面/走势 Tab 生成分析(成功或失败)结束后 emit
  `analysisSettled`,父级 `refreshLlmLogs()` 调用 `aiTab.value?.refresh()`
  (查看器未挂载时为空操作,与原防御性语义一致)

## 顺带改进

- `useMatchFundamentals.toLine` 由 `as unknown as Record<string, unknown>`
  双重断言改为按前缀的显式字段映射(类型安全)
- 移除原文件未使用的 `useMatchStore` 导入

## 验证

- `npx vue-tsc --noEmit` → 0 错误;`npm run build` → 通过
  (MatchDetailView 产物含 7 个 Tab 子组件)
- 代码审查:code-reviewer 代理,结论 WARNING(1 HIGH)——
  重构中丢失 `strategyStore.fetchAll()`,深链直入详情页时策略推荐 Tab
  无数据;已修复(StrategyTab onMounted 补回 fetchAll)。LOW 项
  `useLlmResource` 的 `as Ref<T | null>` 断言经验证为必要
  (泛型 UnwrapRef 延迟求值,去除断言 vue-tsc 报错),已加注释说明

## 边界与已知口径

- 已保存的 AI 综合分析/基本面分析由「页面挂载即拉取」变为「首次进入
  对应 Tab 时拉取」(懒加载化,可接受的行为变化)
- KeepAlive 下 LlmLogViewer 一旦挂载会常驻缓存,其他 Tab 生成分析后
  即使 AI Tab 未激活也会刷新日志(无害增强)
- `MatchRetrospectPanel` 不缓存:每次切入复盘 Tab 重新拉取
