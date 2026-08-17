# FortunePitch (财富绿茵) Backend

基于 FastAPI 的智能足彩数据分析服务。

## 快速启动

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 MySQL 连接串与 API Key
python -c "import asyncio; from app.core.database import init_db; asyncio.run(init_db())"  # 首次建表
uvicorn app.main:app --reload --port 8000
```

## 运行测试

```bash
pytest
```

## 目录说明

- `app/core` - 核心配置、数据库连接、安全认证
- `app/models` - SQLAlchemy ORM 模型定义
- `app/services` - 核心业务逻辑、AI 模型推理(Elo、xG、泊松分布)
- `app/api/v1` - RESTful 路由与接口定义
- `tests` - Pytest 单元测试

## 合规声明

本系统定位为"数据分析与辅助决策工具",仅提供基于公开数据的量化分析能力,
不构成任何投注建议,严禁用于非法博彩活动。
