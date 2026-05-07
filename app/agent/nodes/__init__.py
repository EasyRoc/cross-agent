"""
Agent 节点模块

实现 LangGraph 图中的所有节点函数，每个节点处理 AgentState 的一部分。

节点列表：
- intent_recognition: 意图识别 + 参数提取
- data_collector: 多源数据采集
- analyze_all_dimensions: 12 维度并行分析
- quality_review: 质量审核
- overview_generator: 概览生成
- final_report_generator: 最终报告生成
- human_feedback / decide_next_step: HIL 控制
"""

from app.agent.nodes.intent_recognition import intent_recognition_node
from app.agent.nodes.data_collector import data_collector_node
from app.agent.nodes.analyzer import analyze_all_dimensions
from app.agent.nodes.quality_review import quality_review_node
from app.agent.nodes.overview_generator import overview_generator_node
from app.agent.nodes.report_generator import final_report_generator_node
from app.agent.nodes.human_feedback import human_feedback_node, decide_next_step

__all__ = [
    "intent_recognition_node",
    "data_collector_node",
    "analyze_all_dimensions",
    "quality_review_node",
    "overview_generator_node",
    "final_report_generator_node",
    "human_feedback_node",
    "decide_next_step",
]
