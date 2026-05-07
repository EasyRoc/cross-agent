"""
Agent 模块

基于 LangGraph StateGraph 构建的 Supervisor 模式多 Agent 系统。

节点列表：
1. intent_recognition — 意图识别 + 参数提取
2. data_collector — 多源数据采集（RAG + MCP + LLM 兜底）
3. multi_dim_analyzer — 12 维度并行分析
4. quality_review — 质量审核
5. overview_generator — 概览生成
6. human_feedback — Human-in-the-Loop 控制
7. final_report_generator — 最终报告生成
"""
