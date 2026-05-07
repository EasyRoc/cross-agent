"""
后台任务执行器

在后台线程中执行完整分析流程，更新任务状态和进度。
供 FastAPI BackgroundTasks 调用。

流程：
  1. 更新任务状态为 running
  2. 依次调用各分析节点
  3. 完成或失败时更新任务状态
  4. 保存报告文件到 user_id/task_id/ 子目录
"""

import asyncio
from pathlib import Path
from datetime import datetime

from app.config import settings
from app.task.manager import TaskManager
from app.report.generator import get_report_generator
from app.logger import get_logger

logger = get_logger(__name__)


def run_analysis_task(task_id: str, user_id: str, params: dict):
    """在后台线程中执行完整的商品分析流程

    Args:
        task_id: 任务 ID
        user_id: 用户 ID
        params: 分析参数字典（含 product, platforms, dimensions 等）
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    manager = TaskManager()

    try:
        logger.info("任务 %s 开始执行: %s", task_id, params.get("product", ""))
        manager.update_task(task_id, status="running", progress='{"step": "starting"}')

        # 延迟导入，避免循环依赖
        from app.models.state import INITIAL_STATE
        from app.agent.nodes.intent_recognition import intent_recognition_node
        from app.agent.nodes.data_collector import data_collector_node
        from app.agent.nodes.analyzer import analyze_all_dimensions
        from app.agent.nodes.quality_review import quality_review_node
        from app.agent.nodes.overview_generator import overview_generator_node
        from app.agent.nodes.report_generator import final_report_generator_node

        state = dict(INITIAL_STATE)
        state["params"] = params
        state["session_id"] = f"task_{task_id}"

        # Step 1: 数据采集
        manager.update_task(task_id, progress='{"step": "data_collect"}')
        state.update(loop.run_until_complete(intent_recognition_node(state)))
        state.update(loop.run_until_complete(data_collector_node(state)))
        data_count = len(state.get("raw_data", []))
        logger.info("任务 %s 采集到 %d 条数据", task_id, data_count)

        # Step 2: 多维分析
        manager.update_task(task_id, progress='{"step": "analyzing"}')
        state.update(loop.run_until_complete(analyze_all_dimensions(state)))
        dim_count = len(state.get("analysis_results", {}))
        logger.info("任务 %s 完成 %d 个维度分析", task_id, dim_count)

        # Step 3: 质量审核
        manager.update_task(task_id, progress='{"step": "quality_review"}')
        state.update(loop.run_until_complete(quality_review_node(state)))

        # Step 4: 生成概览（跳过 HIL，后台任务直接走到报告）
        manager.update_task(task_id, progress='{"step": "generating_report"}')
        state["status"] = "confirmed"
        state.update(loop.run_until_complete(final_report_generator_node(state)))

        report_content = state.get("final_report", "")
        filename = state.get("report_filename", f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        if report_content:
            # 按用户目录保存报告
            report_gen = get_report_generator()
            user_report_dir = Path(settings.report_output_dir) / user_id
            user_report_dir.mkdir(parents=True, exist_ok=True)

            md_path = user_report_dir / f"{filename}.md"
            md_path.write_text(report_content, encoding="utf-8")
            logger.info("任务 %s Markdown 已保存: %s", task_id, md_path)

            pdf_path = user_report_dir / f"{filename}.pdf"
            try:
                from weasyprint import HTML
                html = report_gen.markdown_to_html(report_content)
                styled = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{ font-family: 'PingFang SC', sans-serif; padding: 40px; line-height: 1.8; }}
h1 {{ color: #1a1a1a; border-bottom: 2px solid #2563eb; }}
h2 {{ color: #2563eb; margin-top: 30px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; }}
</style></head><body>{html}</body></html>"""
                HTML(string=styled).write_pdf(str(pdf_path))
            except Exception as e:
                logger.warning("任务 %s PDF 生成失败: %s", task_id, e)
                pdf_path = None

            manager.update_task(
                task_id,
                status="completed",
                progress='{"step": "completed"}',
                report_md_path=str(md_path),
                report_pdf_path=str(pdf_path) if pdf_path else "",
            )
            logger.info("任务 %s 完成，报告已保存", task_id)
        else:
            manager.update_task(
                task_id,
                status="failed",
                error_message="报告内容为空",
            )

    except Exception as e:
        logger.error("任务 %s 执行失败: %s", task_id, e, exc_info=True)
        manager.update_task(task_id, status="failed", error_message=str(e))
    finally:
        loop.close()
