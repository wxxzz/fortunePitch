# 比赛补充信息(伤停/阵型等人工录入)

## 功能概述

深度分析页(比赛详情)新增「其他信息」Tab:以**大文本输入**的方式人工录入
场外情报,保存到数据库,并作为**支撑证据注入 AI 分析模块**。

三个自由文本字段(单字段上限 5000 字):

| 字段 | 内容 |
|---|---|
| 伤停信息 | 双方伤停/停赛球员与影响评估 |
| 阵型信息 | 预计首发阵型/战术打法 |
| 其他补充 | 天气/裁判/战意等未归类情报 |

合规:仅提供数据分析参考,不构成投注建议。

## 后端

### 数据模型(新表 fp_match_extra_info,每场一行)

`MatchExtraInfo`(models/match.py):match_id PK/FK → fp_match_games /
injuries / formations / other_notes(Text,均可空)/ updated_at
(default now + onupdate now)。整体覆盖语义:重复保存为更新,空文本归一为
NULL(与"清空"一致)。无 Alembic,`create_all` 增表即可,存量表零改动。

### 服务(app/services/match_extra_info.py)

- `load_extra_info(session, match_id)`:未录入返回 None;
- `upsert_extra_info(session, *, match_id, ...)`:比赛不存在抛 404,
  空白文本归一 None;经 `session.merge` 按 PK 转为 INSERT 或 UPDATE,
  避免"先查后插"在并发保存(双开页/连点)时撞重复主键,updated_at
  显式赋值保证 UPDATE 路径时间戳刷新;flush 后返回(提交由请求级会话依赖完成);
- `format_extra_info_text(row)`:渲染为 `- 伤停信息:… / - 阵型信息:… /
  - 其他补充:…` 文本块;全空返回 None(不注入)。

### 端点(api/v1/match/router.py)

| 端点 | 说明 |
|---|---|
| `GET /api/v1/match/games/{match_id}/extra-info` | 未录入返回空记录(updated_at 为 null),比赛不存在 404 |
| `PUT /api/v1/match/games/{match_id}/extra-info` | 保存(整体覆盖),比赛不存在 404,单字段 >5000 字 422 |

### AI 分析注入(llm.py / llm_fundamental.py)

`MatchAnalysisContext` 与 `FundamentalAnalysisContext` 新增
`extra_info_text: str | None` 字段;上下文聚合时读取补充信息并渲染
(读取失败只降级记 warning,不阻断主分析)。非空时在 user 提示词
【比赛信息】之后注入:

```
【人工录入补充信息(伤停/阵型等,可能含主观判断,须与系统数据交叉校验)】
```

两个服务的 system 提示词均补一条职责边界:人工录入信息一并作为推理依据,
但须与积分榜/赔率等系统数据交叉校验,矛盾时以系统数据为准并在理由中说明。
注入范围:**AI 综合分析**(llm)与 **AI 基本面分析**(llm_fundamental);
赔率走势分析(市场资金视角)不注入。

## 前端

- `src/api/match/extraInfo.ts`:getMatchExtraInfo / saveMatchExtraInfo 封装
- `MatchDetailView.vue`:TABS 在「AI 分析」前插入「其他信息」;
  三个 textarea(带 placeholder 与 maxlength)+ 保存按钮 + 最近保存时间
  提示;表单与已保存快照不一致时提示"有未保存的更改";
  加载失败可点"重新加载"重试
- 顶部对战卡片的阵型行由静态演示文案改为动态:已录入阵型时显示其首行
  (`阵型:…`),未录入时提示录入入口
- 录入后需**重新生成** AI 分析,最新内容才会体现在分析结论中

## 测试

- `tests/test_match_extra_info_api.py`(7 项):GET 未录入空记录 /
  未知比赛 404 / PUT 保存与整体覆盖(重复保存仍单行,空文本清空)/
  PUT 404 / 超 5000 字 422 / 注入 llm 上下文与提示词(含未录入不注入)/
  注入 llm_fundamental 上下文与提示词
- 基线:466 passed(459 + 7 新增)

## 边界与已知口径

- 每场一条记录,不做历史版本(每次保存覆盖);AI 分析结论自身按次留痕
- 人工录入可能含主观判断,提示词显式标注数据来源并要求交叉校验,
  由模型自行取舍
- 单字段 5000 字上限同时约束前后端(服务常量 MAX_FIELD_LENGTH 被 schema
  `Field(max_length=...)` 引用 + textarea maxlength,单一事实来源)
