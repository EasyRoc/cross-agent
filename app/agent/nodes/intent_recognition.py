"""
意图识别节点

作为 LangGraph 的入口节点，负责：
1. 判断用户输入是"商品分析请求"还是"普通对话"
2. 如果是分析请求，提取商品、平台、维度、时间等参数
3. 将结果写回 AgentState，供后续节点使用

路由逻辑：
- product_analysis + confidence >= 0.7 → 进入数据采集流程
- normal_chat 或 confidence < 0.7 → 直接 LLM 回复，流程结束
"""

import json
from app.llm.client import get_llm_client
from app.config import settings
from app.agent.prompts import INTENT_PROMPT, PARAMS_EXTRACT_PROMPT
from app.models.enums import Platform, Dimension, ALL_DIMENSIONS
from app.logger import get_logger

logger = get_logger(__name__)


async def intent_recognition_node(state: dict) -> dict:
    """意图识别 + 参数提取

    从用户最新消息中识别意图，提取分析参数。

    Args:
        state: 当前 AgentState
            state.messages[-1].content 是用户最新输入

    Returns:
        更新后的状态子集：
        - intent: 识别结果（product_analysis / normal_chat）
        - intent_confidence: 置信度
        - params: 分析参数（仅 product_analysis 时有值）
        - status: 保持 pending
    """
    # 获取用户最新输入
    user_input = state["messages"][-1]["content"] if state["messages"] else ""
    logger.info("意图识别: %s...", user_input[:60])

    # ===== Step 1: 意图识别 =====
    llm = get_llm_client()
    prompt = INTENT_PROMPT.format(user_input=user_input)

    try:
        result = await llm.chat_json(
            messages=[{"role": "user", "content": prompt}],
            model=settings.intent_model,
        )
        intent = result.get("intent", "normal_chat")
        confidence = float(result.get("confidence", 0.0))
        logger.info("意图识别结果: %s (confidence=%.2f)", intent, confidence)
    except Exception as e:
        logger.error("意图识别调用失败: %s，默认 normal_chat", e)
        intent = "normal_chat"
        confidence = 0.0

    # 非分析请求或置信度不足，直接返回
    if intent != "product_analysis" or confidence < 0.7:
        return {
            "intent": intent,
            "intent_confidence": confidence,
            "params": None,
            "status": "pending",
        }

    # ===== Step 2: 提取分析参数 =====
    platforms_str = ", ".join([p.value for p in Platform])
    dimensions_str = ", ".join(ALL_DIMENSIONS)
    params_prompt = PARAMS_EXTRACT_PROMPT.format(
        user_input=user_input,
        platforms=platforms_str,
        dimensions=dimensions_str,
    )

    try:
        params = await llm.chat_json(
            messages=[{"role": "user", "content": params_prompt}],
            model=settings.intent_model,
        )
        logger.info("参数提取完成: product=%s, platforms=%s, dimensions=%s, time=%s",
                     params.get("product"),
                     params.get("platforms"),
                     params.get("dimensions"),
                     params.get("time_range"))
    except Exception as e:
        logger.error("参数提取失败: %s，使用默认参数", e)
        params = {
            "product": user_input,
            "platforms": [Platform.ALL.value],
            "dimensions": ALL_DIMENSIONS,
            "time_range": "近30天",
        }

    return {
        "intent": intent,
        "intent_confidence": confidence,
        "params": params,
        "status": "pending",
    }
