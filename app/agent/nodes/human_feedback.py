"""
人工反馈节点

Human-in-the-Loop（HIL）控制节点。
用户在 WebSocket 中决策，此节点根据决策结果路由到不同的下游节点：

- confirmed → final_report_generator（生成最终报告）
- rejected → multi_dim_analyzer（根据反馈重新分析）
- terminated → END（结束流程）

最大迭代次数由 settings.max_iterations 控制，默认 3 次。
"""

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


async def human_feedback_node(state: dict) -> dict:
    """人工反馈节点

    注：实际用户交互在 WebSocket handler 中处理，
    此节点仅传递状态，不做业务逻辑。

    Args:
        state: 当前 AgentState

    Returns:
        原样返回 state
    """
    # 状态已在 WebSocket handler 中更新
    return state


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
