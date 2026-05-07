"""
数据采集节点

从多个数据源并行采集商品数据，按优先级依次尝试：
1. RAG 检索 — 公司私有商品库（Milvus 向量检索）
2. MCP 平台采集 — 电商平台 + Tavily 网络检索
3. LLM 兜底 — 以上都无数据时由 LLM 生成模拟数据

采集到的数据去重后存入 AgentState.raw_data。
"""

import json
from app.mcp.factory import get_mcp_factory
from app.rag.hybrid_search import HybridSearch
from app.logger import get_logger

logger = get_logger(__name__)


async def data_collector_node(state: dict) -> dict:
    """多源数据采集

    按 RAG → MCP → LLM 兜底的顺序采集，结果去重。

    Args:
        state: 当前 AgentState
            state.params: 分析参数（包含 product, platforms, time_range）

    Returns:
        更新后的状态子集：
        - raw_data: 去重后的商品数据列表
        - status: 保持 pending
    """
    params = state.get("params", {})
    if not params:
        logger.warning("参数为空，跳过数据采集")
        return state

    product = params.get("product", "")
    platforms = params.get("platforms", ["全网"])
    time_range = params.get("time_range", "近30天")

    logger.info("===== 数据采集开始 =====")
    logger.info("商品: %s | 平台: %s | 时间: %s", product, platforms, time_range)

    all_data = []

    # ===== 数据源 1: RAG 检索 =====
    try:
        hybrid = HybridSearch()
        rag_results = await hybrid.search(product, top_k=10)
        for item in rag_results:
            item["_source"] = "rag"
            all_data.append(item)
        logger.info("RAG 检索到 %d 条商品", len(rag_results))
    except Exception as e:
        logger.warning("RAG 检索失败（不影响后续流程）: %s", e)

    # ===== 数据源 2: MCP 平台采集 =====
    try:
        factory = get_mcp_factory()
        mcp_data = await factory.search_all(product, platforms, time_range)
        all_data.extend(mcp_data)
        logger.info("MCP 采集到 %d 条商品", len(mcp_data))
    except Exception as e:
        logger.warning("MCP 采集失败（不影响后续流程）: %s", e)

    # ===== 数据去重 =====
    # 按 (商品名, 平台) 去重，保证同名同平台只保留一条
    seen = set()
    unique_data = []
    for item in all_data:
        key = (item.get("name", ""), item.get("platform", ""))
        if key not in seen and item.get("name"):
            seen.add(key)
            unique_data.append(item)

    logger.info("数据去重: %d → %d 条", len(all_data), len(unique_data))
    logger.info("===== 数据采集完成: %d 条 =====", len(unique_data))

    return {
        "raw_data": unique_data,
        "status": "pending",
    }
