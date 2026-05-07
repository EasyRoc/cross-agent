"""
WebSocket API 端点

提供实时双向通信能力，支持流式 LLM 输出和 Human-in-the-Loop 交互。

协议说明（JSON 格式）：

客户端 → 服务端：
  - {type: "user_message", content: "男式衬衫爆款分析"}
  - {type: "decision", action: "confirm"|"reject"|"terminate", feedback: "..."}
  - {type: "list_tasks", page: 1, page_size: 20}

服务端 → 客户端：
  - {type: "token", content: "..."}          — 流式输出 token
  - {type: "done", intent: "..."}            — 流式结束
  - {type: "status", content: "..."}         — 状态提示
  - {type: "overview", data: {...}}          — 分析概览
  - {type: "report_ready", markdown_url: "...", pdf_url: "..."}  — 报告就绪
  - {type: "task_status", task_id: "...", status: "...", progress: "..."} — 任务状态
  - {type: "task_list", tasks: [...], page: 1} — 任务列表
  - {type: "error", content: "..."}          — 错误提示
  - {type: "terminated", content: "..."}     — 流程终止
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import FileResponse


from app.config import settings
from app.models.state import INITIAL_STATE
from app.llm.client import get_llm_client
from app.report.generator import get_report_generator
from app.auth import get_user_by_token
from app.task.manager import TaskManager
from app.logger import get_logger

# 直接引入各节点（避免 LangGraph 全图执行的 HIL 不便）
from app.agent.nodes.intent_recognition import intent_recognition_node
from app.agent.nodes.data_collector import data_collector_node
from app.agent.nodes.analyzer import analyze_all_dimensions
from app.agent.nodes.quality_review import quality_review_node
from app.agent.nodes.overview_generator import overview_generator_node
from app.agent.nodes.report_generator import final_report_generator_node

router = APIRouter()
logger = get_logger(__name__)

# 活跃会话存储：{session_id: AgentState}
active_sessions: dict[str, dict] = {}

# 意图识别 prompt（快速判断）
INTENT_PROMPT = """你是一个商品分析系统的意图识别器。
判断用户输入属于以下哪一类：
1. product_analysis — 商品分析请求（如 "男式衬衫爆款分析"）
2. normal_chat — 普通对话（如 "你好"）

用户输入：{user_input}

输出 JSON（不要带 markdown 代码块标记）：
{{"intent": "product_analysis" | "normal_chat", "confidence": 0.0~1.0}}"""


@router.get("/health")
async def health():
    """健康检查端点"""
    return {"status": "ok"}


# ==================== 文件下载（兼容旧版无 token 路径） ====================


@router.get("/download/{filename}")
async def download_report(filename: str):
    """下载报告文件（旧版，无用户绑定）"""
    report_dir = Path(settings.report_output_dir)
    filepath = report_dir / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "application/octet-stream" if filepath.suffix == ".pdf" else "text/markdown"
    logger.info("文件下载（旧版）: %s", filename)
    return FileResponse(path=str(filepath), filename=filepath.name, media_type=media_type)


# ==================== WebSocket 端点 ====================


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(""),
):
    """WebSocket 主处理器

    支持通过 token 查询参数进行用户认证。
    认证后可绑定任务、查看任务列表。

    Args:
        websocket: WebSocket 连接
        session_id: 会话唯一标识
        token: JWT 令牌（可选）
    """
    await websocket.accept()
    state = dict(INITIAL_STATE)
    active_sessions[session_id] = state
    llm = get_llm_client()

    # 尝试 token 认证
    current_user = None
    if token:
        current_user = get_user_by_token(token)
        if current_user:
            state["user_id"] = current_user["id"]
            logger.info("用户已认证: %s (session=%s)", current_user["username"], session_id)
        else:
            logger.warning("无效 token（session=%s）", session_id)

    logger.info("新 WebSocket 会话: session_id=%s", session_id)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "")

            if msg_type == "user_message":
                content = msg.get("content", "")
                state["messages"] = state.get("messages", []) + [{"role": "user", "content": content}]
                logger.info("用户输入 [%s]: %s", session_id, content[:60])

                # ============ 1. 意图识别 ============
                prompt = INTENT_PROMPT.format(user_input=content)
                try:
                    result = await llm.chat_json(
                        messages=[{"role": "user", "content": prompt}],
                        model=settings.intent_model,
                    )
                    intent = result.get("intent", "normal_chat")
                    confidence = float(result.get("confidence", 0.0))
                except Exception as e:
                    logger.error("意图识别失败: %s", e)
                    intent = "normal_chat"
                    confidence = 0.0

                state["intent"] = intent
                logger.info("意图识别结果: %s (confidence=%.2f)", intent, confidence)

                # ----- 普通对话分支 -----
                if intent != "product_analysis" or confidence < 0.7:
                    logger.info("普通对话模式，流式回复")
                    full = ""
                    async for token_text in llm.chat_stream(messages=state["messages"][-10:], temperature=0.7):
                        full += token_text
                        await websocket.send_text(json.dumps(
                            {"type": "token", "content": token_text}, ensure_ascii=False
                        ))
                    state["messages"] += [{"role": "assistant", "content": full}]
                    await websocket.send_text(json.dumps(
                        {"type": "done", "intent": "normal_chat"}, ensure_ascii=False
                    ))
                    continue

                # ============ 2. 产品分析流程 ============

                # ---- 2a. 创建任务（用户已认证时） ----
                current_task_id = None
                if current_user:
                    try:
                        manager = TaskManager()
                        current_task_id = manager.create_task(
                            user_id=current_user["id"],
                            product_name=content[:50],
                        )
                        state["task_id"] = current_task_id
                        await websocket.send_text(json.dumps({
                            "type": "task_status",
                            "task_id": current_task_id,
                            "status": "pending",
                            "progress": "任务已创建",
                        }, ensure_ascii=False))
                        logger.info("任务已创建: %s (user=%s)", current_task_id, current_user["id"])
                    except RuntimeError as e:
                        await _safe_send(websocket, {"type": "error", "content": str(e)})
                        # 不阻断，继续执行但不绑定任务

                try:
                    # Step 2b: 参数提取 + 数据采集
                    # 构建带 token 的下载 URL 前缀（用于前端直接链接下载）
                    download_token_prefix = ""
                    if token:
                        download_token_prefix = f"?token={token}"

                    if current_task_id:
                        _update_task_progress(current_task_id, "参数提取")

                    await websocket.send_text(json.dumps(
                        {"type": "status", "content": "🔍 正在分析请求参数并采集数据..."}, ensure_ascii=False
                    ))
                    state.update(await intent_recognition_node(state))
                    if not state.get("params"):
                        await websocket.send_text(json.dumps(
                            {"type": "error", "content": "无法识别分析参数，请重新描述"}, ensure_ascii=False
                        ))
                        continue

                    if current_task_id:
                        _update_task_progress(current_task_id, "数据采集")
                    state.update(await data_collector_node(state))
                    data_count = len(state.get("raw_data", []))
                    logger.info("数据采集完成: %d 条", data_count)

                    await websocket.send_text(json.dumps(
                        {"type": "status", "content": f"📦 已采集 {data_count} 条商品数据，正在进行多维度分析..."},
                        ensure_ascii=False
                    ))

                    # Step 2c: 多维并行分析
                    if current_task_id:
                        _update_task_progress(current_task_id, "多维度分析")
                    state.update(await analyze_all_dimensions(state))
                    dim_count = len(state.get("analysis_results", {}))
                    logger.info("维度分析完成: %d 个维度", dim_count)

                    await websocket.send_text(json.dumps(
                        {"type": "status", "content": f"📊 已完成 {dim_count} 个维度分析，正在进行质量审核..."},
                        ensure_ascii=False
                    ))

                    # Step 2d: 质量审核
                    if current_task_id:
                        _update_task_progress(current_task_id, "质量审核")
                    state.update(await quality_review_node(state))
                    review = state.get("_quality_review", {})
                    passed = review.get("passed", True)
                    score = review.get("score", 80)
                    logger.info("质量审核完成: passed=%s, score=%d", passed, score)

                    if not passed:
                        await websocket.send_text(json.dumps(
                            {"type": "status", "content": f"⚠️ 质量审核得分 {score}，尝试改进中..."},
                            ensure_ascii=False
                        ))
                    else:
                        await websocket.send_text(json.dumps(
                            {"type": "status", "content": f"✅ 质量审核通过（得分 {score}）"},
                            ensure_ascii=False
                        ))

                    # Step 2e: 生成概览
                    if current_task_id:
                        _update_task_progress(current_task_id, "生成概览")
                    state.update(await overview_generator_node(state))
                    overview = state.get("overview", {})
                    logger.info("概览生成完成: %s", overview.get("title", ""))

                    if overview:
                        await websocket.send_text(json.dumps(
                            {"type": "overview", "data": overview}, ensure_ascii=False
                        ))

                except Exception as e:
                    logger.error("分析流程出错: %s", e, exc_info=True)
                    if current_task_id:
                        manager = TaskManager()
                        manager.update_task(current_task_id, status="failed", error_message=str(e))
                    await _safe_send(websocket, {"type": "error", "content": f"分析过程出错: {str(e)}"})

            elif msg_type == "decision":
                action = msg.get("action", "")
                feedback = msg.get("feedback", "")
                logger.info("用户决策 [%s]: %s", session_id, action)

                # 获取当前任务 ID
                current_task_id = state.get("task_id")

                if action == "confirm":
                    state["status"] = "confirmed"
                    await websocket.send_text(json.dumps(
                        {"type": "status", "content": "📝 正在生成详细报告..."}, ensure_ascii=False
                    ))

                    try:
                        if current_task_id:
                            _update_task_progress(current_task_id, "生成报告")
                        state.update(await final_report_generator_node(state))
                        report_content = state.get("final_report", "")
                        filename = state.get("report_filename", "report")

                        if report_content:
                            report_gen = get_report_generator()
                            md_path = report_gen.save_markdown(report_content, filename)
                            pdf_path = report_gen.save_pdf(report_content, filename)

                            # 更新任务状态（如果已认证）
                            if current_task_id and state.get("user_id"):
                                manager = TaskManager()
                                # 复制到用户目录
                                user_dir = Path(settings.report_output_dir) / state["user_id"]
                                user_dir.mkdir(parents=True, exist_ok=True)
                                md_user_path = user_dir / Path(md_path).name
                                pdf_user_path = user_dir / Path(pdf_path).name
                                # 复制文件
                                Path(md_path).rename(md_user_path) if not md_user_path.exists() else None
                                manager.update_task(
                                    current_task_id,
                                    status="completed",
                                    progress='{"step": "completed"}',
                                    report_md_path=str(md_user_path),
                                    report_pdf_path=str(pdf_user_path) if Path(pdf_path).exists() else "",
                                )

                                # 通知前端任务完成
                                await websocket.send_text(json.dumps({
                                    "type": "task_status",
                                    "task_id": current_task_id,
                                    "status": "completed",
                                    "progress": "报告已生成",
                                }, ensure_ascii=False))

                                # 使用带用户路径的报告链接（含 token 便于前端直接下载）
                                download_md = f"/api/tasks/{current_task_id}/download/md{download_token_prefix}"
                                download_pdf = f"/api/tasks/{current_task_id}/download/pdf{download_token_prefix}"
                                await websocket.send_text(json.dumps({
                                    "type": "report_ready",
                                    "markdown_url": download_md,
                                    "pdf_url": download_pdf,
                                    "markdown_filename": Path(md_user_path).name,
                                    "pdf_filename": Path(pdf_user_path).name,
                                }, ensure_ascii=False))
                            else:
                                # 未登录用户，使用旧版下载路径
                                logger.info("报告已生成: md=%s, pdf=%s",
                                             Path(md_path).name, Path(pdf_path).name)
                                await websocket.send_text(json.dumps({
                                    "type": "report_ready",
                                    "markdown_url": f"/download/{Path(md_path).name}",
                                    "pdf_url": f"/download/{Path(pdf_path).name}",
                                    "markdown_filename": Path(md_path).name,
                                    "pdf_filename": Path(pdf_path).name,
                                }, ensure_ascii=False))
                        else:
                            await websocket.send_text(json.dumps(
                                {"type": "error", "content": "报告内容为空"}, ensure_ascii=False
                            ))

                    except Exception as e:
                        logger.error("报告生成失败: %s", e, exc_info=True)
                        if current_task_id:
                            manager = TaskManager()
                            manager.update_task(current_task_id, status="failed", error_message=str(e))
                        await _safe_send(websocket, {"type": "error", "content": f"报告生成出错: {str(e)}"})

                elif action == "reject":
                    state["status"] = "rejected"
                    state["iteration"] = state.get("iteration", 0) + 1
                    state["feedback"] = feedback
                    iteration = state["iteration"]

                    logger.info("用户拒绝，反馈: %s（第 %d 轮）", feedback, iteration)

                    if iteration >= settings.max_iterations:
                        logger.warning("已达到最大迭代次数 %d", settings.max_iterations)
                        await websocket.send_text(json.dumps(
                            {"type": "status",
                             "content": f"已达到最大迭代次数({settings.max_iterations})，请重新开始分析。"},
                            ensure_ascii=False
                        ))
                        continue

                    await websocket.send_text(json.dumps(
                        {"type": "status",
                         "content": f"🔄 正在根据您的反馈重新分析（第{iteration}轮）..."},
                        ensure_ascii=False
                    ))

                    try:
                        state.update(await analyze_all_dimensions(state))
                        state.update(await overview_generator_node(state))
                        overview = state.get("overview", {})
                        if overview:
                            await websocket.send_text(json.dumps(
                                {"type": "overview", "data": overview}, ensure_ascii=False
                            ))
                    except Exception as e:
                        logger.error("重新分析失败: %s", e, exc_info=True)
                        await _safe_send(websocket, {"type": "error", "content": f"重新分析出错: {str(e)}"})

                elif action == "terminate":
                    state["status"] = "terminated"
                    if current_task_id:
                        manager = TaskManager()
                        manager.update_task(current_task_id, status="failed", error_message="用户终止")
                    logger.info("用户终止分析")
                    await websocket.send_text(json.dumps(
                        {"type": "terminated", "content": "分析已终止。"}, ensure_ascii=False
                    ))

            elif msg_type == "list_tasks":
                # 查询用户任务列表（需已认证）
                if not current_user:
                    await websocket.send_text(json.dumps(
                        {"type": "error", "content": "未登录，无法查询任务列表"}, ensure_ascii=False
                    ))
                    continue

                page = msg.get("page", 1)
                page_size = msg.get("page_size", 20)
                manager = TaskManager()
                tasks = manager.list_user_tasks(
                    current_user["id"],
                    limit=page_size,
                    offset=(page - 1) * page_size,
                )
                await websocket.send_text(json.dumps({
                    "type": "task_list",
                    "tasks": tasks,
                    "page": page,
                }, ensure_ascii=False))

    except WebSocketDisconnect:
        logger.info("WebSocket 断开: session_id=%s", session_id)
        # 如果分析未完成，后台继续执行
        task_id = state.get("task_id")
        user_id = state.get("user_id")
        if task_id and user_id and state.get("params"):
            logger.info("WebSocket 断开，后台继续完成任务 %s", task_id)
            asyncio.ensure_future(_complete_task_background(dict(state), task_id, user_id))
    except Exception as e:
        logger.error("WebSocket 异常 [%s]: %s", session_id, e, exc_info=True)
    finally:
        active_sessions.pop(session_id, None)
        logger.debug("会话已清理: %s", session_id)


# ==================== 辅助函数 ====================


async def _safe_send(websocket: WebSocket, data: dict):
    """安全发送 WebSocket 消息，忽略客户端已断开的情况"""
    try:
        await websocket.send_text(json.dumps(data, ensure_ascii=False))
    except (WebSocketDisconnect, RuntimeError):
        pass


def _update_task_progress(task_id: str | None, step: str):
    """更新任务进度（安全调用，无 task_id 时跳过）"""
    if not task_id:
        return
    try:
        manager = TaskManager()
        manager.update_task(task_id, progress=f'{{"step": "{step}"}}')
    except Exception as e:
        logger.warning("更新任务进度失败: %s", e)


async def _complete_task_background(state: dict, task_id: str, user_id: str):
    """WebSocket 断开后，在后台继续完成未结束的分析任务

    跳过 HIL 审核，自动生成报告并更新任务状态。
    已完成的步骤自动跳过避免重复工作。
    """
    logger.info("后台继续执行任务 %s (user=%s)", task_id, user_id)
    manager = TaskManager()
    try:
        manager.update_task(task_id, status="running", progress='{"step": "background_resume"}')

        from app.report.generator import get_report_generator

        # 如果报告已经生成（断开发生在保存/发送阶段），直接保存
        if state.get("final_report"):
            logger.info("任务 %s 报告已生成，直接保存", task_id)
        else:
            # Step 1: 数据采集（如果还没采）
            if not state.get("raw_data"):
                manager.update_task(task_id, progress='{"step": "background_collect"}')
                state.update(await data_collector_node(state))

            # Step 2: 多维分析（如果还没做）
            if not state.get("analysis_results"):
                manager.update_task(task_id, progress='{"step": "background_analyze"}')
                state.update(await analyze_all_dimensions(state))

            # Step 3: 质量审核
            manager.update_task(task_id, progress='{"step": "background_review"}')
            state.update(await quality_review_node(state))

            # Step 4: 跳过 HIL，直接生成报告
            state["status"] = "confirmed"
            manager.update_task(task_id, progress='{"step": "background_report"}')
            state.update(await final_report_generator_node(state))

        report_content = state.get("final_report", "")
        if not report_content:
            manager.update_task(task_id, status="failed", error_message="报告内容为空")
            return

        # 按用户目录保存报告
        from datetime import datetime
        user_dir = Path(settings.report_output_dir) / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        md_path = user_dir / f"{filename}.md"
        md_path.write_text(report_content, encoding="utf-8")

        pdf_path = None
        try:
            from weasyprint import HTML
            report_gen = get_report_generator()
            html_content = report_gen.markdown_to_html(report_content)
            styled_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{ font-family: 'PingFang SC', sans-serif; padding: 40px; line-height: 1.8; }}
h1 {{ color: #1a1a1a; border-bottom: 2px solid #2563eb; }}
h2 {{ color: #2563eb; margin-top: 30px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; }}
</style></head><body>{html_content}</body></html>"""
            pdf_path = user_dir / f"{filename}.pdf"
            HTML(string=styled_html).write_pdf(str(pdf_path))
        except Exception as e:
            logger.warning("后台任务 %s PDF 生成跳过: %s", task_id, e)

        manager.update_task(
            task_id,
            status="completed",
            progress='{"step": "completed"}',
            report_md_path=str(md_path),
            report_pdf_path=str(pdf_path) if pdf_path else "",
        )
        logger.info("后台任务 %s 完成，报告已保存", task_id)

    except Exception as e:
        logger.error("后台任务 %s 失败: %s", task_id, e, exc_info=True)
        manager.update_task(task_id, status="failed", error_message=str(e))
