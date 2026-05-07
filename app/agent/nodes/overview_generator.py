"""
概览生成节点

将多维度分析结果汇总为一份简洁的概览，展示给用户确认。
概览包含：标题、摘要、核心发现、各维度结论。

概览数据将流式返回给用户，用户确认后才进入最终报告生成。
用户拒绝时可输入反馈重新分析。
"""

import json
from datetime import datetime
from app.llm.client import get_llm_client
from app.config import settings
from app.agent.prompts import OVERVIEW_PROMPT
from app.logger import get_logger

logger = get_logger(__name__)


async def overview_generator_node(state: dict) -> dict:
    """生成分析概览

    调用 LLM 将所有维度的分析结果整合为一份结构化概览。

    Args:
        state: 当前 AgentState
            state.params: 分析参数
            state.analysis_results: 各维度分析结果
            state.raw_data: 原始数据

    Returns:
        更新后的状态子集：
        - overview: 概览数据（title, summary, key_findings, dimension_summaries）
        - status: overview_generated
    """
    llm = get_llm_client()
    params = state.get("params", {})
    analysis_results = state.get("analysis_results", {})
    raw_data = state.get("raw_data", [])

    product = params.get("product", "")
    time_range = params.get("time_range", "近30天")
    platforms = params.get("platforms", ["全网"])
    dimensions = params.get("dimensions", [])

    logger.info("===== 概览生成 =====")
    logger.info("商品: %s | 维度: %d 个 | 数据: %d 条",
                 product, len(analysis_results), len(raw_data))

    prompt = OVERVIEW_PROMPT.format(
        product=product,
        time_range=time_range,
        platforms=", ".join(platforms),
        data_count=len(raw_data),
        dimensions=", ".join(dimensions),
        analysis_results=json.dumps(analysis_results, ensure_ascii=False)[:5000],
    )

    try:
        overview = await llm.chat_json(
            messages=[{"role": "user", "content": prompt}],
            model=settings.report_model,
        )
        logger.info("概览生成完成: %s", overview.get("title", ""))
        logger.info("核心发现: %d 条", len(overview.get("key_findings", [])))
        logger.info("维度摘要: %d 个", len(overview.get("dimension_summaries", {})))
    except Exception as e:
        logger.error("概览生成失败，使用默认概览: %s", e)
        overview = {
            "title": f"{product} 市场分析报告",
            "summary": f"对 {product} 在 {time_range} 内的市场情况进行分析",
            "key_findings": ["数据加载中..."],
            "dimension_summaries": {},
        }

    # 补充元信息
    overview["product"] = product
    overview["time_range"] = time_range
    overview["platforms"] = platforms
    overview["data_count"] = len(raw_data)

    return {
        "overview": overview,
        "status": "overview_generated",
    }
