"""
Agent 状态定义

定义 LangGraph 中流转的 AgentState 类型，以及初始状态常量。
这是整个 Agent 系统的"脊椎"，所有节点读写此状态来协作。
"""

from typing import TypedDict, Optional


class AgentState(TypedDict):
    """Agent 状态类型定义

    LangGraph 的有向图在节点间传递此状态对象。
    每个节点读取输入状态，返回更新后的状态子集。

    状态字段分组：
    - 对话状态: messages, summary
    - 分析任务: intent, params
    - 状态流转: status, iteration, feedback
    - 数据: raw_data, analysis_results
    - 输出: overview, final_report, report_filename
    """
    # ========== 对话状态 ==========
    messages: list[dict]          # 短期记忆消息历史 [{"role": str, "content": str}, ...]
    summary: str                  # 摘要记忆（超出窗口后由 LLM 自动生成）

    # ========== 分析任务 ==========
    intent: str                   # 意图识别结果：product_analysis / normal_chat
    intent_confidence: float      # 意图识别的置信度（0.0 ~ 1.0）
    params: Optional[dict]        # 提取的分析参数（AnalysisParams 的字典形式）

    # ========== 状态流转 ==========
    status: str                   # 当前状态，见 AgentStatus 枚举
    iteration: int                # 当前迭代次数（HIL 重分析计数）
    feedback: str                 # 用户反馈（拒绝时填写）

    # ========== 数据 ==========
    raw_data: list[dict]          # 原始采集数据列表（Product 的字典形式）
    analysis_results: dict        # 各维度分析结果 {维度名: 分析文本}

    # ========== 输出 ==========
    overview: Optional[dict]      # 分析概览（展示给用户确认）
    final_report: str             # 最终 Markdown 报告文本
    report_filename: str          # 报告文件名（不含后缀）


# AgentState 的默认初始值
INITIAL_STATE: AgentState = {
    "messages": [],                # 空对话历史
    "summary": "",                 # 无摘要
    "intent": "",                  # 未识别
    "intent_confidence": 0.0,      # 零置信度
    "params": None,                # 未提取参数
    "status": "pending",           # 初始状态
    "iteration": 0,                # 未迭代
    "feedback": "",                # 无反馈
    "raw_data": [],                # 无数据
    "analysis_results": {},        # 无分析结果
    "overview": None,              # 无概览
    "final_report": "",            # 无报告
    "report_filename": "",         # 无名
}
