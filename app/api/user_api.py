"""
用户与任务管理 API 路由

提供用户注册/登录、任务列表/详情/下载等 RESTful 接口。

端点清单：
  POST /api/register         — 用户注册
  POST /api/login            — 用户登录
  GET  /api/me               — 获取当前用户信息（需鉴权）
  GET  /api/tasks            — 用户任务列表（需鉴权）
  GET  /api/tasks/{id}       — 任务详情（需鉴权）
  GET  /api/tasks/{id}/download/md   — 下载 Markdown 报告（需鉴权）
  GET  /api/tasks/{id}/download/pdf  — 下载 PDF 报告（需鉴权）
"""

from pathlib import Path
from fastapi import APIRouter, HTTPException, Header, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth import register_user, login_user, get_user_by_token
from app.task.manager import TaskManager
from app.logger import get_logger

router = APIRouter(prefix="/api")
logger = get_logger(__name__)


# ==================== 请求/响应模型 ====================


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


# ==================== 鉴权依赖 ====================


async def require_user(authorization: str = Header(""), token: str = "") -> dict:
    """从 Authorization header 或 token 查询参数解析 JWT，返回用户信息"""
    token_value = token
    if authorization.startswith("Bearer "):
        token_value = authorization[7:]
    if not token_value:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    user = get_user_by_token(token_value)
    if not user:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    return user


# ==================== 用户路由 ====================


@router.post("/register")
async def register(req: RegisterRequest):
    """用户注册"""
    if len(req.username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="密码至少 4 个字符")
    try:
        user = register_user(req.username, req.password, req.display_name)
        logger.info("新用户注册: %s", req.username)
        return {"message": "注册成功", "user": user}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/login")
async def login(req: LoginRequest):
    """用户登录，返回 JWT token"""
    try:
        result = login_user(req.username, req.password)
        logger.info("用户登录: %s", req.username)
        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/me")
async def get_me(user: dict = Depends(require_user)):
    """获取当前用户信息"""
    return {"user": user}


# ==================== 任务路由 ====================


@router.get("/tasks")
async def list_tasks(page: int = 1, page_size: int = 20, user: dict = Depends(require_user)):
    """获取当前用户的任务列表（按创建时间倒序）"""
    manager = TaskManager()
    offset = (page - 1) * page_size
    tasks = manager.list_user_tasks(user["id"], limit=page_size, offset=offset)
    return {"tasks": tasks, "page": page, "page_size": page_size}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: dict = Depends(require_user)):
    """获取任务详情"""
    manager = TaskManager()
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问此任务")
    return {"task": task}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user: dict = Depends(require_user)):
    """删除任务"""
    manager = TaskManager()
    ok = manager.delete_task(task_id, user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在或无权删除")
    return {"message": "任务已删除"}


@router.get("/tasks/{task_id}/download/{fmt}")
async def download_report(task_id: str, fmt: str, token: str = Query(""), user: dict = Depends(require_user)):
    """下载任务报告文件，支持 Authorization header 或 ?token= 查询参数"""
    """下载任务报告文件（md 或 pdf）"""
    manager = TaskManager()
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问此任务")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务未完成，无法下载")

    if fmt == "md":
        path = task.get("report_md_path", "")
    elif fmt == "pdf":
        path = task.get("report_pdf_path", "")
    else:
        raise HTTPException(status_code=400, detail="不支持的文件格式，仅支持 md/pdf")

    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="报告文件不存在")

    filepath = Path(path)
    media_type = "application/octet-stream" if fmt == "pdf" else "text/markdown"
    return FileResponse(path=str(filepath), filename=filepath.name, media_type=media_type)
