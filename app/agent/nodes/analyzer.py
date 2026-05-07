"""
多维分析节点

对采集到的商品数据，从多个维度并行分析。
每个维度调用一次 LLM，通过 asyncio.gather 实现并行执行。

分析维度（12 个）：爆款、配色、价格带、品类、材质、风格、
人群、购买动机、痛点、使用场景、购买路径、生命周期

支持 HIL 反馈重新分析（iteration > 0 时使用 REANALYSIS_PROMPT）。
"""

import asyncio
import json
from app.llm.client import get_llm_client
from app.config import settings
from app.agent.prompts import ANALYSIS_PROMPT, REANALYSIS_PROMPT
from app.models.enums import ALL_DIMENSIONS
from app.logger import get_logger

logger = get_logger(__name__)


async def analyze_all_dimensions(state: dict) -> dict:
    """并行分析所有维度

    内部使用 asyncio.gather 同时调用 LLM 分析每个维度，
    显著减少总体等待时间。

    Args:
        state: 当前 AgentState
            state.params.dimensions: 需要分析的维度列表
            state.raw_data: 采集到的商品数据
            state.iteration: 当前迭代次数（0 为首次）
            state.feedback: 用户反馈（重新分析时使用）

    Returns:
        更新后的状态子集：
        - analysis_results: {维度名: 分析文本} 字典
        - status: 保持 pending
    """
    llm = get_llm_client()
    params = state.get("params", {})
    raw_data = state.get("raw_data", [])
    feedback = state.get("feedback", "")
    iteration = state.get("iteration", 0)

    product = params.get("product", "")
    time_range = params.get("time_range", "近30天")
    dimensions = params.get("dimensions", ALL_DIMENSIONS)

    logger.info("===== 维度分析开始 =====")
    logger.info("商品: %s | 维度: %d 个 | 迭代: 第 %d 轮",
                 product, len(dimensions), iteration + 1)

    # 序列化商品数据供 LLM 使用（截取前 20 条、前 6000 字符）
    data_json = json.dumps(raw_data[:20], ensure_ascii=False, indent=2)[:6000]

    async def analyze_one(dim: str) -> tuple[str, str]:
        """分析单个维度

        Args:
            dim: 维度名称

        Returns:
            (维度名, 分析文本) 元组
        """
        if feedback and iteration > 0:
            # 重新分析：参考用户反馈
            prompt = REANALYSIS_PROMPT.format(
                feedback=feedback,
                dimension=dim,
                raw_data=data_json,
            )
        else:
            # 首次分析
            prompt = ANALYSIS_PROMPT.format(
                product=product,
                time_range=time_range,
                dimension=dim,
                raw_data=data_json,
            )

        try:
            result = await llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=settings.analysis_model,
            )
            logger.debug("维度 '%s' 分析完成（%d 字符）", dim, len(result.strip()))
            return dim, result.strip()
        except Exception as e:
            logger.error("维度 '%s' 分析失败: %s", dim, e)
            return dim, f"分析失败: {str(e)}"

    # 并行执行所有维度分析
    tasks = [analyze_one(dim) for dim in dimensions]
    results = await asyncio.gather(*tasks)

    # 汇总结果
    analysis_results = {}
    for dim, result in results:
        analysis_results[dim] = result

    logger.info("===== 维度分析完成: %d/ %d 个 =====",
                 len(results), len(dimensions))

    return {
        "analysis_results": analysis_results,
        "status": "pending",
    }
