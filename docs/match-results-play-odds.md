# 赛果开奖页:售卖日单选 + 玩法中奖赔率

> 完成日期:2026-10-28 · 需求:售卖日筛选改单日单选;
> 各玩法开奖结果后附中奖选项赔率(如比分 5:2@100)

## 需求

1. **售卖日筛选改单选**:原"售卖日起 + 售卖日止"范围筛选(最长 31 天)
   改为单个售卖日下拉选择,查询/统计/同步均按单日口径。
2. **玩法中奖赔率**:胜平负/让球/比分/总进球/半全场五列的开奖结果后
   追加该玩法中奖选项的赔率,如比分列显示 `5:2@100`。

## 实现口径

### 赔率来源(后端)

`fp_match_results` 只存开奖标签与胜平负 SP(sp_h/sp_d/sp_a),其余玩法的
中奖赔率需由 `fp_match_odds.pools`(每场一行的在售赔率池 JSON)推导:

- `app/services/settlement.py` 新增两个纯函数:
  - `_winning_option_code(play_code, result_label, pool)`:在赔率池中找
    中奖选项编码——逐选项将展示名(经 `resolve_option_label`)与开奖
    标签比对(复用 `resolve_option_hit` 的归一化与 TTG "7+" 特例);
    比分玩法超出常规选项的高比分(如 6:2)命中"胜/平/负其他"
    (s1sh/s1sd/s1sa)
  - `resolve_result_play_odds(result, pools) -> {had_sp, hhad_sp, crs_sp,
    ttg_sp, hafu_sp}`:逐玩法解析中奖选项赔率,直接以 `**` 展开进
    `MatchResultRead` 构造
- **胜平负优先取赛果 SP**(sp_h/sp_d/sp_a,与结算引擎
  `resolve_payout_odds` 同口径),中奖选项由开奖标签直接反查
  (`_WDL_LABEL_TO_CODE`),无/缺 HAD 赔率池时仍可解析;
  其余玩法依赖在售赔率池的中奖选项赔率
- `GET /match/results`(match/router.py)批量 `IN` 加载当页场次的
  `MatchOdds` 后逐场解析,一次额外查询,无 N+1

边界:非胜平负玩法未同步赔率池、取消/未开奖玩法、未开售玩法均返回
None,前端仅显示标签不带 `@`。

### 前端(MatchResultsView.vue)

- 单个 `startDate`(售卖日)下拉;删除 endDate/MAX_RANGE_DAYS/
  dateRange/isoOf,新增 `validateSaleDate` 校验;`listMatchResults/
  listMatchResultStats` 以同一起止(=单日)调用,后端接口本身仍是
  范围签名,无需改
- 同步按钮按售卖日口径同步单日(会拉取当日+次日赛果),行为不变
- 玩法单元格经 `formatPlay(label, sp)` 渲染 `标签@赔率`;
  `formatSp` 去掉尾随多余的 0(100.00 → 100,2.10 → 2.1)
- 多维度分析 meta 由起止区间改为单日文案

## 验证

- 后端:`python -m pytest backend/tests -q` → 507 passed
  (新增 `TestResolveResultPlayOdds` 8 项:逐玩法解析/TTG 7+/高比分
  "胜其他"/无赔率池/HAD 无池取 SP/HAD 缺池取 SP/取消场次/玩法缺失;
  接口层新增 `test_list_results_with_play_odds` 预置 MatchOdds 全链路断言)
- 前端:`npx vue-tsc --noEmit` → 0 错误;`npm run build` → 通过
- 代码审查:code-reviewer 代理,结论 APPROVE(0 CRITICAL/HIGH);
  2 项 MEDIUM 已修复——① HAD 中奖选项改为由开奖标签直接反查,
  赔率池缺失时仍取赛果 SP;② `pools_by_match` 类型注解去掉多余的
  `| None`。1 项 LOW(空日期校验顺序)顺手修正;其余 LOW 为
  有意的设计选择(`formatSp` 去尾零与 SP 列两位小数并存、
  `**` 展开 + 测试兜底)不改

## 边界与已知口径

- 非胜平负玩法的"赛果赔率"取自 fp_match_odds 在售赔率池的当前值
  (即时赔率),并非体彩官方开奖 SP——官方接口仅在赛果响应中提供
  胜平负三项 SP;如后续需要精确开奖 SP,可扩展赛果采集存储
- 比分 "胜/平/负其他" 的命中规则为本地推导(常规比分选项之外的
  高比分),与体彩口径一致
