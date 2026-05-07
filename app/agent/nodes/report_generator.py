"""
最终报告生成节点

用户确认概览后，由 LLM 生成完整的 Markdown 格式分析报告。
报告包含：核心发现、市场概况、多维度分析、策略建议、风险提示。

报告内容保存为 .md 和 .pdf 文件供用户下载。
"""

import json
from datetime import datetime
from app.llm.client import get_llm_client
from app.config import settings
from app.agent.prompts import REPORT_PROMPT
from app.logger import get_logger

logger = get_logger(__name__)


async def final_report_generator_node(state: dict) -> dict:
    """生成最终分析报告

    调用高能力模型（qwen-max）生成长篇 Markdown 报告。

    Args:
        state: 当前 AgentState
            state.params: 分析参数
            state.analysis_results: 各维度分析结果
            state.raw_data: 原始数据

    Returns:
        更新后的状态子集：
        - final_report: Markdown 格式的完整报告
        - report_filename: 报告文件名（不含后缀）
        - status: completed
    """
    llm = get_llm_client()
    params = state.get("params", {})
    analysis_results = state.get("analysis_results", {})
    raw_data = state.get("raw_data", [])

    product = params.get("product", "")
    time_range = params.get("time_range", "近30天")
    platforms = params.get("platforms", ["全网"])

    logger.info("===== 最终报告生成 =====")
    logger.info("商品: %s | 时间: %s | 来源: %s",
                 product, time_range, platforms)

    prompt = REPORT_PROMPT.format(
        product=product,
        time_range=time_range,
        platforms=", ".join(platforms),
        data_count=len(raw_data),
        generated_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        analysis_results=json.dumps(analysis_results, ensure_ascii=False)[:8000],
    )

    try:
        report = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model=settings.report_model,
        )
        report = report.strip()
        logger.info("报告生成完成，长度 %d 字符", len(report))
    except Exception as e:
        logger.error("报告生成失败: %s", e)
        report = f"# {product} 市场分析报告\n\n报告生成失败: {str(e)}"

    # 生成文件名（含时间戳，避免重复）
    filename = f"{product}_市场分析报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger.info("报告文件名: %s", filename)

    return {
        "final_report": report,
        "report_filename": filename,
        "status": "completed",
    }
