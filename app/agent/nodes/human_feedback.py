"""
人工反馈节点

Human-in-the-Loop（HIL）控制节点。
通过 LangGraph 的 interrupt() 暂停图执行，等待用户通过 API 决策后恢复。

决策结果路由（由 decide_next_step 处理）：
- confirmed → final_report_generator（生成最终报告）
- rejected → multi_dim_analyzer（根据反馈重新分析）
- terminated → END（结束流程）

最大迭代次数由 settings.max_iterations 控制，默认 3 次。
"""

from langgraph.types import interrupt
from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


async def human_feedback_node(state: dict) -> dict:
    """人工反馈节点：暂停图执行，等待用户决策。

    调用 interrupt() 后图执行暂停，astream() 自然结束。
    通过 Command(resume={...}) 恢复后，interrupt() 返回用户决策数据。

    Args:
        state: 当前 AgentState
            state.overview: 已生成的分析概览

    Returns:
        更新后的状态子集：
        - status: confirmed / rejected / terminated
        - feedback: 用户反馈（仅 rejected）
        - iteration: 当前迭代次数
    """
    logger.info("暂停图执行，等待用户决策...")

    result = interrupt({
        "type": "human_feedback_request",
        "overview": state.get("overview"),
    })

    action = result.get("action", "terminate")
    logger.info("收到用户决策: %s", action)

    if action == "confirm":
        state["status"] = "confirmed"
    elif action == "reject":
        state["status"] = "rejected"
        state["feedback"] = result.get("feedback", "")
        state["iteration"] = state.get("iteration", 0) + 1
    else:
        state["status"] = "terminated"

    return {
        "status": state["status"],
        "feedback": state.get("feedback", ""),
        "iteration": state.get("iteration", 0),
    }


def decide_next_step(state: dict) -> str:
    """根据用户决策决定下一步路由

    Args:
        state: 当前 AgentState
            state.status: 用户决策结果
            state.iteration: 当前迭代次数

    Returns:
        路由目标：
        - "confirmed" → 生成最终报告
        - "rejected" → 重新分析
        - "terminated" → 结束
    """
    status = state.get("status", "")
    iteration = state.get("iteration", 0)

    if status == "confirmed":
        logger.info("用户已确认概览，进入报告生成")
        return "confirmed"

    elif status == "rejected":
        if iteration >= settings.max_iterations:
            logger.warning("已达到最大迭代次数 %d，终止分析", settings.max_iterations)
            return "terminated"
        logger.info("用户拒绝概览（第 %d 轮），重新分析", iteration)
        return "rejected"

    else:  # terminated
        logger.info("用户终止分析")
        return "terminated"
