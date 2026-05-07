"""
LangGraph Supervisor 图定义

使用 LangGraph 的 StateGraph 构建 Supervisor 模式的分析工作流。

节点拓扑：
    [用户输入]
        │
    intent_recognition ──normal_chat──→ [END]
        │ product_analysis
    data_collector
        │
    multi_dim_analyzer (内部并行 12 维度)
        │
    quality_review ──need_recollect──→ data_collector
        │ pass
    overview_generator
        │
    human_feedback ──rejected──→ multi_dim_analyzer
        │ confirmed              │ terminated
    final_report_generator    [END]
        │
    [END]

Supervisor 模式说明：
- Supervisor（意图识别节点）在入口处路由请求
- 各子 Agent 通过 StateGraph 协作，共享 AgentState
- Human-in-the-Loop 通过 human_feedback 节点实现
- 质量审核不通过时自动回退重试
"""

from langgraph.graph import StateGraph, END
from app.models.state import AgentState
from app.agent.nodes import (
    intent_recognition_node,
    data_collector_node,
    analyze_all_dimensions,
    quality_review_node,
    overview_generator_node,
    final_report_generator_node,
    human_feedback_node,
    decide_next_step,
)
from app.logger import get_logger

logger = get_logger(__name__)


def create_graph() -> StateGraph:
    """构建 Supervisor 模式 LangGraph 工作流

    定义所有节点和有向边，返回可编译的 StateGraph。

    Returns:
        未编译的 StateGraph 实例
    """
    logger.info("构建 LangGraph 分析工作流")

    workflow = StateGraph(AgentState)

    # ===== 注册节点 =====
    # 每个节点是一个异步函数，接收当前 state 返回更新后的 state 子集
    workflow.add_node("intent_recognition", intent_recognition_node)
    workflow.add_node("data_collector", data_collector_node)
    workflow.add_node("multi_dim_analyzer", analyze_all_dimensions)
    workflow.add_node("quality_review", quality_review_node)
    workflow.add_node("overview_generator", overview_generator_node)
    workflow.add_node("human_feedback", human_feedback_node)
    workflow.add_node("final_report_generator", final_report_generator_node)

    # ===== 有向边定义 =====

    # 入口条件边：根据意图识别结果路由
    # - product_analysis → 进入数据采集
    # - normal_chat → 直接结束（由 WebSocket 处理回复）
    workflow.set_conditional_entry_point(
        "intent_recognition",
        lambda s: "product_analysis" if s.get("intent") == "product_analysis" else "normal_chat",
        {
            "product_analysis": "data_collector",
            "normal_chat": END,
        },
    )

    # 主流程：采集 → 分析 → 审核 → 概览
    workflow.add_edge("data_collector", "multi_dim_analyzer")
    workflow.add_edge("multi_dim_analyzer", "quality_review")

    # 质量审核条件分支
    # - 通过 → 生成概览
    # - 不通过 → 重新采集
    workflow.add_conditional_edges(
        "quality_review",
        lambda s: "overview_generator" if s.get("status") == "overview_generated" else "data_collector",
        {
            "overview_generator": "overview_generator",
            "data_collector": "data_collector",
        },
    )

    # 概览 → 等待用户确认
    workflow.add_edge("overview_generator", "human_feedback")

    # Human-in-the-Loop 条件分支
    workflow.add_conditional_edges(
        "human_feedback",
        decide_next_step,
        {
            "confirmed": "final_report_generator",
            "rejected": "multi_dim_analyzer",
            "terminated": END,
        },
    )

    # 报告生成 → 结束
    workflow.add_edge("final_report_generator", END)

    logger.info("LangGraph 工作流定义完成，节点数: 7, 边数: 8")
    return workflow


# ==================== 全局单例 ====================

_analysis_graph = None


def get_analysis_graph():
    """获取编译后的 LangGraph 实例（单例）

    首次调用时创建并编译图，后续复用。
    """
    global _analysis_graph
    if _analysis_graph is None:
        logger.info("首次编译 LangGraph 工作流")
        graph = create_graph()
        _analysis_graph = graph.compile()
        logger.info("LangGraph 工作流编译完成")
    return _analysis_graph
