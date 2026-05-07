"""
商品分析 Agent

基于 LangGraph Supervisor 模式的多 Agent 商品分析系统。
支持从小红书、抖音、淘宝、亚马逊、得物等多平台采集数据，
进行 12 维度分析，生成 Markdown/PDF 报告。

核心模块：
- agent: LangGraph Agent 节点和图编排
- llm:   阿里百炼 LLM 客户端
- mcp:   多平台数据采集（含 Tavily 网络检索）
- rag:   Milvus 向量检索
- memory: 短期/摘要记忆
- models: 数据模型和枚举
- report: 报告生成（Markdown/PDF）
- api:    FastAPI WebSocket 端点
"""
