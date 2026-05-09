"""
SSE + REST API — 基于 LangGraph 的对话端点

端点：
  POST /api/chat            — 发送消息，返回 SSE 流（token/status/overview）
  POST /api/chat/decide     — 用户决策（confirm/reject），返回 SSE 流
  POST /api/chat/terminate  — 终止当前分析
  GET  /health              — 健康检查
  GET  /download/{filename} — 旧版匿名报告下载

执行流程（product_analysis）：
  1. 快速意图识别（chat.py 内完成）
  2. 若为产品分析 → 调用 LangGraph StateGraph
  3. Graph 执行：intent_recognition → data_collector → multi_dim_analyzer
     → quality_review → overview_generator → human_feedback (interrupt)
  4. SSE 流结束后，等待用户决策
  5. POST /api/chat/decide → Command(resume=...) 恢复 Graph
  6. confirm → final_report_generator → END
     reject → multi_dim_analyzer → ... → human_feedback (再次 interrupt)

SSE 事件：
  event: token       data: {"content": "..."}
  event: done        data: {"intent": "..."}
  event: status      data: {"content": "..."}
  event: overview    data: {...}
  event: report_ready data: {markdown_url, pdf_url}
  event: task_status data: {task_id, status, progress}
  event: error       data: {"content": "..."}
"""

import json
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from langgraph.types import Command

from app.config import settings
from app.models.state import INITIAL_STATE
from app.llm.client import get_llm_client
from app.memory.short_term import ShortTermMemory
from app.report.generator import get_report_generator
from app.auth import get_user_by_token
from app.task.manager import TaskManager
from app.agent.graph import get_analysis_graph
from app.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

# 快速意图识别 prompt（仅用于决定走 graph 还是普通对话）
INTENT_PROMPT = """你是一个商品分析系统的意图识别器。
判断用户输入属于以下哪一类：
1. product_analysis — 商品分析请求（如 "男式衬衫爆款分析"）
2. normal_chat — 普通对话（如 "你好"）

用户输入：{user_input}

输出 JSON（不要带 markdown 代码块标记）：
{{"intent": "product_analysis" | "normal_chat", "confidence": 0.0~1.0}}"""


class ChatRequest(BaseModel):
    content: str
    session_id: str = ""


class DecideRequest(BaseModel):
    session_id: str
    action: str = ""
    feedback: str = ""


# ==================== SSE 辅助 ====================


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _resolve_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.query_params.get("token", "")


# ==================== 流式生成器 ====================


async def _chat_stream(content: str, session_id: str, token: str):
    """处理用户消息：普通对话直接流式回复，商品分析走 LangGraph。"""
    llm = get_llm_client()
    short_term = ShortTermMemory(window=settings.short_term_window)

    # ---------- Token 认证 ----------
    current_user = None
    if token:
        current_user = get_user_by_token(token)
        if current_user:
            logger.info("用户已认证: %s (session=%s)", current_user["username"], session_id)

    # ---------- 1. 快速意图识别 ----------
    try:
        result = await llm.chat_json(
            messages=[{"role": "user", "content": INTENT_PROMPT.format(user_input=content)}],
            model=settings.intent_model,
        )
        intent = result.get("intent", "normal_chat")
        confidence = float(result.get("confidence", 0.0))
    except Exception as e:
        logger.error("意图识别失败: %s", e)
        intent = "normal_chat"
        confidence = 0.0

    logger.info("意图识别结果: %s (confidence=%.2f)", intent, confidence)

    # ---------- 2. 普通对话（不走 graph，直接流式 LLM） ----------
    if intent != "product_analysis" or confidence < 0.7:
        logger.info("普通对话模式，流式回复")
        messages = short_term.add([], "user", content)
        full = ""
        async for t in llm.chat_stream(messages=short_term.trim(messages), temperature=0.7):
            full += t
            yield _sse("token", {"content": t})
        yield _sse("done", {"intent": "normal_chat"})
        return

    # ---------- 3. 商品分析 — 走 LangGraph ----------
    # 未登录用户不允许使用商品分析
    if not current_user:
        yield _sse("error", {"content": "请先登录后再使用商品分析功能"})
        return

    state = dict(INITIAL_STATE)
    state["messages"] = [{"role": "user", "content": content}]
    state["intent"] = "product_analysis"
    state["intent_confidence"] = confidence
    state["user_id"] = current_user["id"]

    # 创建任务
    current_task_id = None
    try:
        manager = TaskManager()
        current_task_id = manager.create_task(
            user_id=current_user["id"],
            product_name=content[:50],
        )
        state["task_id"] = current_task_id
        yield _sse("task_status", {
            "task_id": current_task_id, "status": "pending", "progress": "任务已创建",
        })
    except RuntimeError as e:
        yield _sse("error", {"content": str(e)})
        return

    # 检查是否已有中断中的图（同一个 session_id 发来第二条消息）
    graph = get_analysis_graph()
    config = {"configurable": {"thread_id": session_id}}
    try:
        snapshot = await graph.aget_state(config)
        if snapshot and snapshot.next:
            yield _sse("error", {"content": "当前分析尚未完成，请先决策或终止"})
            return
    except ValueError:
        pass  # 新会话，无已有 checkpoint

    yield _sse("status", {"content": "正在分析请求参数并采集数据..."})

    try:
        async for event in graph.astream(state, config, stream_mode="updates"):
            name = next(iter(event))
            upd = event[name]
            if not upd:
                continue

            if name == "data_collector":
                _update_task_progress(current_task_id, "数据采集")
                yield _sse("status", {
                    "content": f"已采集 {len(upd.get('raw_data', []))} 条商品数据，正在进行多维度分析...",
                })

            elif name == "multi_dim_analyzer":
                _update_task_progress(current_task_id, "多维度分析")
                yield _sse("status", {
                    "content": f"已完成 {len(upd.get('analysis_results', {}))} 个维度分析，正在进行质量审核...",
                })

            elif name == "quality_review":
                _update_task_progress(current_task_id, "质量审核")
                review = upd.get("_quality_review", {})
                score = review.get("score", 80)
                passed = review.get("passed", True)
                if passed:
                    yield _sse("status", {"content": f"质量审核通过（得分 {score}）"})
                else:
                    yield _sse("status", {"content": f"质量审核得分 {score}，尝试改进中..."})

            elif name == "overview_generator":
                _update_task_progress(current_task_id, "生成概览")
                overview = upd.get("overview", {})
                if overview:
                    yield _sse("overview", {"data": overview})

            # human_feedback → graph 执行 interrupt → astream 自然结束

    except Exception as e:
        logger.error("分析流程出错: %s", e, exc_info=True)
        if current_task_id:
            TaskManager().update_task(current_task_id, status="failed", error_message=str(e))
        yield _sse("error", {"content": f"分析过程出错: {str(e)}"})


async def _decide_stream(session_id: str, action: str, feedback: str, token: str):
    """处理用户决策：用 Command(resume=...) 恢复 LangGraph 执行。

    - confirm → 生成报告 → report_ready
    - reject  → 重新分析 → overview
    - terminate → 结束
    """
    graph = get_analysis_graph()
    config = {"configurable": {"thread_id": session_id}}

    # 读取 checkpoint 中的会话状态
    try:
        snapshot = await graph.aget_state(config)
    except ValueError:
        yield _sse("error", {"content": "会话不存在或已过期"})
        return

    if not snapshot or not snapshot.next:
        yield _sse("error", {"content": "会话不在等待决策状态"})
        return

    state_values = snapshot.values
    current_task_id = state_values.get("task_id")
    download_token_prefix = f"?token={token}" if token else ""

    # 决策：terminate 直接设状态不回流
    if action == "terminate":
        try:
            async for _ in graph.astream(Command(resume={"action": "terminate"}), config, stream_mode="updates"):
                pass
        except Exception:
            pass
        if current_task_id:
            TaskManager().update_task(current_task_id, status="failed", error_message="用户终止")
        logger.info("用户终止分析 (session=%s)", session_id)
        return

    # confirm / reject — 恢复图执行并流式输出
    resume_data = {"action": action}
    if action == "reject":
        resume_data["feedback"] = feedback

    try:
        async for event in graph.astream(Command(resume=resume_data), config, stream_mode="updates"):
            name = next(iter(event))
            upd = event[name]
            if not upd:
                continue

            if name == "multi_dim_analyzer":
                yield _sse("status", {"content": "正在根据反馈重新分析..."})

            elif name == "overview_generator":
                overview = upd.get("overview", {})
                if overview:
                    yield _sse("overview", {"data": overview})

            elif name == "final_report_generator":
                yield _sse("status", {"content": "正在生成详细报告..."})
                report_content = upd.get("final_report", "")
                report_filename = upd.get("report_filename", "report")

                if not report_content:
                    yield _sse("error", {"content": "报告内容为空"})
                    continue

                # 保存文件
                report_gen = get_report_generator()
                md_path = report_gen.save_markdown(report_content, report_filename)
                pdf_path = report_gen.save_pdf(report_content, report_filename)

                # 认证用户：复制到用户目录 + 更新任务记录
                if current_task_id and state_values.get("user_id"):
                    manager = TaskManager()
                    user_dir = Path(settings.report_output_dir) / state_values["user_id"]
                    user_dir.mkdir(parents=True, exist_ok=True)
                    md_user_path = user_dir / Path(md_path).name
                    pdf_user_path = user_dir / Path(pdf_path).name
                    if not md_user_path.exists():
                        Path(md_path).rename(md_user_path)

                    manager.update_task(
                        current_task_id,
                        status="completed",
                        progress='{"step": "completed"}',
                        report_md_path=str(md_user_path),
                        report_pdf_path=str(pdf_user_path) if Path(pdf_path).exists() else "",
                    )

                    yield _sse("task_status", {
                        "task_id": current_task_id,
                        "status": "completed",
                        "progress": "报告已生成",
                    })

                    yield _sse("report_ready", {
                        "markdown_url": f"/api/tasks/{current_task_id}/download/md{download_token_prefix}",
                        "pdf_url": f"/api/tasks/{current_task_id}/download/pdf{download_token_prefix}",
                        "markdown_filename": Path(md_user_path).name,
                        "pdf_filename": Path(pdf_user_path).name,
                    })
                else:
                    # 匿名用户：使用通用下载路径
                    logger.info("报告已生成: md=%s, pdf=%s",
                                 Path(md_path).name, Path(pdf_path).name)
                    yield _sse("report_ready", {
                        "markdown_url": f"/download/{Path(md_path).name}",
                        "pdf_url": f"/download/{Path(pdf_path).name}",
                        "markdown_filename": Path(md_path).name,
                        "pdf_filename": Path(pdf_path).name,
                    })

    except Exception as e:
        logger.error("决策流程出错: %s", e, exc_info=True)
        if current_task_id:
            TaskManager().update_task(current_task_id, status="failed", error_message=str(e))
        yield _sse("error", {"content": f"处理决策时出错: {str(e)}"})


# ==================== SSE 端点 ====================


@router.post("/api/chat")
async def chat(request: ChatRequest, raw_request: Request):
    """发送消息，返回 SSE 流。"""
    token = _resolve_token(raw_request)
    return StreamingResponse(
        _chat_stream(request.content, request.session_id, token),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/chat/decide")
async def decide(request: DecideRequest, raw_request: Request):
    """用户决策（confirm/reject），返回 SSE 流。"""
    token = _resolve_token(raw_request)
    return StreamingResponse(
        _decide_stream(request.session_id, request.action, request.feedback, token),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/chat/terminate")
async def terminate(request: DecideRequest):
    """终止当前分析。"""
    graph = get_analysis_graph()
    config = {"configurable": {"thread_id": request.session_id}}
    try:
        snapshot = await graph.aget_state(config)
        if snapshot and snapshot.next:
            async for _ in graph.astream(Command(resume={"action": "terminate"}), config, stream_mode="updates"):
                pass
    except (ValueError, Exception):
        pass
    return {"status": "terminated", "content": "分析已终止。"}


# ==================== 遗留端点 ====================


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/download/{filename}")
async def download_report(filename: str):
    """旧版匿名报告下载。"""
    report_dir = Path(settings.report_output_dir)
    filepath = report_dir / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "application/octet-stream" if filepath.suffix == ".pdf" else "text/markdown"
    return FileResponse(path=str(filepath), filename=filepath.name, media_type=media_type)


# ==================== 辅助函数 ====================


def _update_task_progress(task_id: str | None, step: str):
    if not task_id:
        return
    try:
        TaskManager().update_task(task_id, progress=f'{{"step": "{step}"}}')
    except Exception as e:
        logger.warning("更新任务进度失败: %s", e)
