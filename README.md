# FortunePitch 财富绿茵

基于大数据与 AI 的智能足彩数据分析系统(内部代号:致富之道 / The Path to Wealth)。

> 系统定位为"数据分析与辅助决策工具",仅提供基于公开数据的量化分析,
> 不构成任何投注建议,严禁用于非法博彩活动。

## 项目结构

```
fortunePitch/
├── backend/              # Python FastAPI 后端
│   ├── app/core/         # 配置、数据库连接、安全认证、异常处理
│   ├── app/models/       # SQLAlchemy ORM 模型(按 4 模块分文件)
│   ├── app/services/     # 核心算法(Elo、xG、Dixon-Coles 泊松)+ 通用 CRUD
│   ├── app/api/v1/
│   │   ├── base/         # 基础档案:联赛/球队/球员
│   │   ├── match/        # 比赛与赛果:比赛/事件
│   │   ├── analytics/    # 高阶数据分析:指标/表现/泊松预测
│   │   └── strategy/     # 策略与赔率:赔率/推荐/决策/凯利
│   └── tests/            # Pytest 单元与集成测试
├── frontend/             # Vue3 + TypeScript 前端
│   ├── src/views/
│   │   ├── base/         # 基础档案页
│   │   ├── match/        # 赛事中心页
│   │   ├── analytics/    # 数据分析页
│   │   └── strategy/     # 策略与赔率页
│   ├── src/components/   # 按模块分组的业务组件(ECharts 封装等)
│   ├── src/api/          # Axios 请求封装(按模块分组)
│   └── src/stores/       # Pinia 状态管理(按模块拆分)
└── docs/                 # 需求、数据库设计、算法说明文档
```

## 快速启动

### 后端

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

接口文档:http://localhost:8000/docs

### 前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173(已配置 `/api` 代理转发至后端 8000 端口)。

## 运行测试

```bash
cd backend && pytest
```

## 开发规范

详见 [.cursorrules](.cursorrules) 与 [docs/](docs/)。
