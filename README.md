# 🧠 商品分析 Agent

> **多 Agent 商品分析系统** — 基于 LangGraph Supervisor 模式，从小红书、抖音、淘宝、亚马逊、得物等多平台采集数据，进行 12 维度分析，生成结构化报告（Markdown/PDF）。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| **意图识别** | LLM 自动区分"商品分析请求"与"普通对话" |
| **多源数据采集** | RAG（Milvus 混合检索）+ Tavily 网络检索 + LLM 兜底生成 |
| **12 维分析** | 爆款/配色/价格带/品类/材质/风格/人群/购买动机/痛点/使用场景/购买路径/生命周期 |
| **并行分析** | 12 个维度通过 `asyncio.gather` 并行调用 LLM，秒级完成 |
| **报告生成** | 固定模板的 Markdown 报告，支持 PDF 导出 |
| **Human-in-the-Loop** | 生成概览 → 用户确认/反馈 → 迭代改进 → 输出终稿 |
| **流式输出** | LLM 推理结果逐 token 推送到前端，实时展示 |
| **记忆管理** | 短期记忆（滑动窗口）+ 摘要记忆（LLM 自动总结） |
| **暗色模式** | 前端支持主题切换 |

---

## 架构设计

### 系统架构

```
┌────────────────────────────────────────────────────────────┐
│                        用户界面 (Web)                       │
├────────────────────────────────────────────────────────────┤
│                     FastAPI / WebSocket                    │
├────────────────────────────────────────────────────────────┤
│                     Supervisor Agent                       │
│              (意图识别 + 任务编排 + HIL 控制)                │
├───────────┬───────────┬───────────┬────────────────────────┤
│ Data      │ MultiDim  │ Quality   │ Report                 │
│ Collector │ Analyzer  │ Review    │ Generator              │
│ Agent     │ Agent     │ Agent     │ Agent                  │
├───────────┴───────────┴───────────┴────────────────────────┤
│                      记忆层 (Memory)                        │
├───────────┬───────────┬───────────┬────────────────────────┤
│ RAG       │ MCP       │ MCP       │ LLM                    │
│ (Milvus)  │ (Tavily)  │ (电商平台) │ (兜底)                 │
├───────────┴───────────┴───────────┴────────────────────────┤
│                    基础设施层                                │
│       阿里百炼 LLM · Milvus (Docker) · 阿里云 OSS(可选)     │
└────────────────────────────────────────────────────────────┘
```

### Agent 工作流

```
[用户输入]
    │
intent_recognition ──normal_chat──→ [LLM 直接回复]
    │ product_analysis
data_collector (RAG → MCP → LLM 兜底)
    │
multi_dim_analyzer (12 维度并行 asyncio.gather)
    │
quality_review (完整性/准确性/一致性审核)
    │
overview_generator (生成分析概览)
    │
human_feedback ←── 用户确认/拒绝/终止
    │ confirmed          │ rejected
final_report_generator    multi_dim_analyzer (迭代)
    │
[END]
```

---

## 快速开始

### 环境要求

- Python >= 3.11
- Milvus（可选，Docker 部署）
- 阿里百炼 API Key（必填）
- Tavily API Key（可选，推荐）

### 安装

```bash
# 1. 克隆项目
git clone <repo-url> && cd cross-agent

# 2. 创建虚拟环境
python -m venv .venv && source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
# 或：pip install fastapi uvicorn openai langgraph pymilvus markdown weasyprint tavily python-dotenv pydantic-settings jinja2 aiofiles

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY
```

### 启动

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问 **http://localhost:8000**

---

## 配置说明

### 环境变量（`.env`）

```bash
# === 阿里百炼（必填）===
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxx
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# === Tavily 网络搜索（推荐）===
TAVILY_API_KEY=tvly-xxxxxxxxxxxx

# === Milvus 向量数据库（可选）===
MILVUS_HOST=localhost
MILVUS_PORT=19530

# === 服务配置 ===
APP_HOST=0.0.0.0
APP_PORT=8000
```

### LLM 模型配置（`app/config.py`）

| 用途 | 默认模型 | 说明 |
|------|----------|------|
| 意图识别 | `qwen-plus` | 快速、低成本 |
| 数据分析 | `qwen-max` | 推理能力强 |
| 报告生成 | `qwen-max` | 长文本生成 |
| 文本向量化 | `text-embedding-v3` | Embedding |
| 摘要记忆 | `qwen-plus` | 中等推理任务 |

---

## 使用指南

### 分析商品

在输入框输入分析请求，例如：

```
男性衬衫爆款分析
运动鞋2025年流行趋势与配色
夏季女装价格带与风格
母婴用品购买动机分析
```

### 分析流程

1. **输入请求** → 输入商品分析需求
2. **意图识别** → 系统自动判断是否为分析请求
3. **数据采集** → 从 RAG、Tavily、LLM 多渠道采集
4. **并行分析** → 12 维度同时分析（侧边栏实时显示进度）
5. **概览确认** → 侧边栏展示分析概览
6. **确认/反馈** → 确认则生成报告，拒绝可输入改进建议
7. **下载报告** → Markdown / PDF 格式下载

### WebSocket 协议

```json
// 客户端 → 服务端
{"type": "user_message", "content": "男式衬衫爆款分析"}
{"type": "decision", "action": "confirm|reject|terminate", "feedback": "..."}

// 服务端 → 客户端
{"type": "token", "content": "正在..."}           // 流式 token
{"type": "done", "intent": "product_analysis"}   // 流式结束
{"type": "status", "content": "正在采集..."}      // 状态提示
{"type": "overview", "data": {...}}              // 分析概览
{"type": "report_ready", "markdown_url": "...", "pdf_url": "..."}  // 报告就绪
{"type": "error", "content": "..."}              // 错误
{"type": "terminated", "content": "..."}         // 终止
```

---

## 项目结构

```
cross-agent/
├── app/
│   ├── main.py              # FastAPI 入口 + 静态文件服务
│   ├── config.py            # 全局配置（环境变量加载）
│   ├── logger.py            # 统一日志配置
│   │
│   ├── models/              # 数据模型
│   │   ├── enums.py         # 平台/维度/时间/状态 枚举
│   │   ├── schemas.py       # Pydantic 模型（Product, AnalysisParams 等）
│   │   └── state.py         # AgentState TypedDict
│   │
│   ├── llm/                 # LLM 客户端
│   │   └── client.py        # 阿里百炼封装（chat/stream/embed）
│   │
│   ├── memory/              # 记忆系统
│   │   ├── short_term.py    # 短期记忆（滑动窗口）
│   │   └── summary_memory.py# 摘要记忆（LLM 自动总结）
│   │
│   ├── mcp/                 # 数据采集层
│   │   ├── base.py          # MCP 基类 + ProductResult 数据模型
│   │   ├── tavily.py        # Tavily 网络检索 + LLM 兜底
│   │   └── factory.py       # 工厂模式，并行采集
│   │
│   ├── rag/                 # RAG 检索
│   │   ├── milvus_client.py # Milvus 连接/建集合/检索
│   │   ├── embedding.py     # 文本向量化
│   │   └── hybrid_search.py # Query Rewrite → 向量检索
│   │
│   ├── agent/               # Agent 核心
│   │   ├── prompts.py       # 所有 LLM Prompt 模板
│   │   ├── graph.py         # LangGraph 图编排
│   │   └── nodes/           # 7 个 Agent 节点
│   │       ├── intent_recognition.py
│   │       ├── data_collector.py
│   │       ├── analyzer.py       # 12 维并行分析
│   │       ├── quality_review.py
│   │       ├── overview_generator.py
│   │       ├── report_generator.py
│   │       └── human_feedback.py
│   │
│   ├── api/                 # API 端点
│   │   └── websocket.py     # WebSocket + REST
│   │
│   └── report/              # 报告生成
│       └── generator.py     # Markdown/PDF 生成
│
├── static/                  # 前端静态文件
│   ├── index.html           # 主页面
│   ├── style.css            # 样式（毛玻璃 + 暗色模式）
│   └── app.js               # WebSocket 客户端
│
├── docs/
│   ├── 技术方案文档.md       # 完整技术设计
│   └── 需求优化计划.md       # 后续优化路线图
│
├── reports/                 # 报告输出目录（自动生成）
├── .env.example             # 环境变量模板
├── pyproject.toml           # 依赖管理
└── README.md
```

---

## 依赖清单

| 包 | 版本 | 用途 |
|----|------|------|
| fastapi | >=0.111.0 | Web 框架 |
| uvicorn | >=0.29.0 | ASGI 服务器 |
| websockets | >=12.0 | WebSocket 支持 |
| openai | >=1.30.0 | 阿里百炼 LLM 客户端 |
| langgraph | >=0.2.0 | Agent 图编排 |
| langchain | >=0.3.0 | LangChain 生态 |
| pymilvus | >=2.4.0 | Milvus 向量数据库 |
| tavily | >=0.3.0 | 网络搜索 |
| sentence-transformers | >=3.0.0 | 文本向量化（可选） |
| markdown | >=3.6 | Markdown → HTML 转换 |
| weasyprint | >=62.0 | HTML → PDF 转换 |
| pydantic-settings | >=2.2.0 | 环境变量加载 |
| python-dotenv | >=1.0.0 | .env 文件加载 |

---

## 开发计划

| 阶段 | 任务 | 状态 |
|------|------|------|
| **P0** | 项目骨架 + 配置管理 | ✅ |
| **P0** | 数据模型定义 | ✅ |
| **P0** | LLM 客户端（流式） | ✅ |
| **P0** | LangGraph 图 + Supervisor 编排 | ✅ |
| **P0** | 数据采集（RAG + MCP + LLM） | ✅ |
| **P0** | 12 维度并行分析 | ✅ |
| **P0** | 质量审核 | ✅ |
| **P0** | 概览生成 + HIL 流程 | ✅ |
| **P0** | 最终报告生成 | ✅ |
| **P0** | WebSocket 实时通信 | ✅ |
| **P0** | 前端 UI（毛玻璃 + 暗色模式） | ✅ |
| **P1** | 记忆系统（短期 + 摘要） | ✅ |
| **P1** | Markdown/PDF 报告导出 | ✅ |
| **P2** | Milvus 初始化 + 数据导入 | ⬜ |
| **P2** | 各电商平台 MCP 对接 | ⬜ |
| **P2** | 报告嵌入图片（图表 + 商品图） | ⬜ |
| **P2** | OSS 文件上传 | ⬜ |
| **P3** | 长期记忆（SQLite 持久化） | ⬜ |
| **P3** | 测试覆盖 | ⬜ |

---

## 相关文档

- [技术方案文档](docs/技术方案文档.md) — 完整的技术架构设计
- [需求优化计划](docs/需求优化计划.md) — 后续功能优化路线图

---

## License

MIT
