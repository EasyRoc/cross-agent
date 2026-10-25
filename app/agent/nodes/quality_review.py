"""
质量审核节点

在生成概览前对分析结果进行质量审核，确保：
1. 完整性：覆盖所有请求的分析维度
2. 数据支撑：结论有据可查
3. 一致性：各维度间不矛盾
4. 深度：分析有实质内容
5. 可操作性：建议切实可行

审核不通过时返回重新采集（最多 settings.max_quality_retries 次）；
达到上限后不再回退，直接生成概览，交由用户在确认环节把关。
"""

import json
from app.llm.client import get_llm_client
from app.config import settings
from app.agent.prompts import QUALITY_REVIEW_PROMPT
from app.logger import get_logger

logger = get_logger(__name__)


async def quality_review_node(state: dict) -> dict:
    """质量审核

    调用 LLM 审核当前分析结果的质量。

    Args:
        state: 当前 AgentState
            state.params: 请求参数
            state.analysis_results: 各维度分析结果
            state.raw_data: 原始数据

    Returns:
        更新后的状态子集：
        - _quality_review: 审核结果（passed/score/issues 等）
        - status: overview_generated（通过或达重试上限时）或 pending（需要改进）
        - quality_iteration: 未通过时的累计重试计数
    """
    llm = get_llm_client()
    params = state.get("params", {})
    analysis_results = state.get("analysis_results", {})
    raw_data = state.get("raw_data", [])
    quality_iteration = state.get("quality_iteration", 0)

    logger.info("===== 质量审核 =====")
    logger.info("参数: %s | 数据分析维度: %d | 数据量: %d",
                 params.get("product"), len(analysis_results), len(raw_data))

    prompt = QUALITY_REVIEW_PROMPT.format(
        params=json.dumps(params, ensure_ascii=False),
        analysis_results=json.dumps(analysis_results, ensure_ascii=False)[:4000],
        data_count=len(raw_data),
    )

    try:
        review = await llm.chat_json(
            messages=[{"role": "user", "content": prompt}],
            model=settings.intent_model,
        )
        passed = review.get("passed", True)
        score = review.get("score", 80)
        issues = review.get("issues", [])
        suggestions = review.get("suggestions", [])

        logger.info("审核结果: %s (score=%d, issues=%d, suggestions=%d)",
                     "✅ 通过" if passed else "❌ 需改进",
                     score, len(issues), len(suggestions))

        if issues:
            for issue in issues:
                logger.info("  - [%s] %s", issue.get("severity", "info"), issue.get("description", ""))
        if suggestions:
            for sug in suggestions:
                logger.info("  - 建议: %s", sug)

    except Exception as e:
        logger.error("质量审核调用失败，默认通过: %s", e)
        review = {"passed": True, "score": 80, "issues": [], "missing_dimensions": [], "suggestions": []}

    if review.get("passed", True):
        return {
            "_quality_review": review,
            "status": "overview_generated",
        }

    quality_iteration += 1
    if quality_iteration > settings.max_quality_retries:
        # 审核一直不过时不再无限回退，带病继续生成概览，交由用户在确认环节把关
        logger.warning(
            "质量审核未通过且已达重试上限 (%d 次)，跳过重新采集，生成概览供用户确认",
            settings.max_quality_retries,
        )
        review["forced"] = True
        return {
            "_quality_review": review,
            "status": "overview_generated",
            "quality_iteration": quality_iteration,
        }

    logger.info("质量审核未通过（第 %d/%d 次），返回重新采集",
                 quality_iteration, settings.max_quality_retries)
    return {
        "_quality_review": review,
        "status": "pending",
        "quality_iteration": quality_iteration,
    }
