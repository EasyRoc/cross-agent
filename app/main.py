"""
商品分析 Agent — FastAPI 应用入口

启动命令：
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

API 端点：
    GET  /              — 前端页面
    GET  /health       — 健康检查
    GET  /download/... — 报告下载
    WS   /ws/{id}      — WebSocket 实时分析
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.websocket import router as api_router
from app.api.user_api import router as user_router
from app.config import settings
from app.logger import setup_logging, get_logger

# ===== 初始化日志系统 =====
setup_logging()
logger = get_logger(__name__)

# ===== 创建 FastAPI 应用 =====
app = FastAPI(
    title="商品分析 Agent",
    description="多 Agent 商品分析系统 · LangGraph Supervisor · 多渠道数据采集 · 多维度分析",
    version="0.1.0",
)

# ===== 挂载路由 =====
app.include_router(api_router)
app.include_router(user_router)
logger.info("API 路由挂载完成")

# ===== 挂载静态文件（前端） =====
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info("静态文件目录: %s", static_dir)
else:
    logger.warning("静态文件目录不存在: %s", static_dir)


@app.get("/login")
async def login_page():
    """登录页面"""
    login_path = static_dir / "login.html"
    if login_path.exists():
        return FileResponse(str(login_path))
    return {"message": "登录页面不存在"}


@app.get("/")
async def root():
    """根路径：返回前端页面"""
    index_path = static_dir / "index.html"
    if index_path.exists():
        logger.debug("返回前端页面")
        return FileResponse(str(index_path))
    logger.warning("前端页面不存在")
    return {"message": "商品分析 Agent API 已启动", "docs": "/docs"}


@app.on_event("startup")
async def startup():
    """应用启动时的初始化"""
    logger.info("=" * 50)
    logger.info("商品分析 Agent 启动")
    logger.info("配置文件: .env")
    logger.info("LLM 模型: intent=%s, analysis=%s, report=%s",
                 settings.intent_model, settings.analysis_model, settings.report_model)
    logger.info("Milvus: %s:%s", settings.milvus_host, settings.milvus_port)
    logger.info("Tavily: %s", "已配置" if settings.tavily_api_key else "未配置（使用 LLM 兜底）")
    logger.info("JWT 密钥: %s", "已配置" if settings.jwt_secret_key != "change-me-in-production" else "使用默认密钥（请修改）")
    logger.info("服务地址: http://%s:%s", settings.app_host, settings.app_port)
    logger.info("=" * 50)


@app.on_event("shutdown")
async def shutdown():
    """应用关闭时的清理"""
    logger.info("商品分析 Agent 关闭")
