"""
全局配置模块

使用 pydantic-settings 从环境变量和 .env 文件加载配置。
所有配置项集中管理，各模块通过 `from app.config import settings` 引用。

环境变量配置项（.env 文件）：
- DASHSCOPE_API_KEY / DASHSCOPE_BASE_URL: 阿里百炼 API
- TAVILY_API_KEY: Tavily 网络搜索 API
- MILVUS_HOST / MILVUS_PORT: Milvus 向量数据库
- APP_HOST / APP_PORT: Web 服务地址
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置类，所有配置项的集中定义

    配置加载优先级：环境变量 > .env 文件 > 默认值
    """
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # ==================== 阿里百炼 LLM ====================
    # API Key，从 https://bailian.console.aliyun.com/ 获取
    dashscope_api_key: str = ""
    # 阿里百炼兼容 OpenAI SDK 的端点
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # ==================== Tavily 网络搜索 ====================
    # 可选配置，不配置时自动跳过 Tavily 检索，使用 LLM 兜底
    tavily_api_key: Optional[str] = None

    # ==================== Milvus 向量数据库 ====================
    # 本地 Docker 部署的 Milvus 单机版地址
    milvus_host: str = "localhost"
    milvus_port: int = 19530

    # ==================== Web 服务 ====================
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # ==================== LLM 模型选择 ====================
    # 不同任务使用不同模型，平衡速度与效果
    intent_model: str = "qwen-plus"          # 意图识别：快速低成本
    analysis_model: str = "qwen-max"         # 数据分析：强推理能力
    report_model: str = "qwen-max"           # 报告生成：长文本能力强
    embedding_model: str = "text-embedding-v3"  # 文本向量化
    summary_model: str = "qwen-plus"         # 摘要生成

    # ==================== 记忆系统 ====================
    short_term_window: int = 20   # 短期记忆保留的对话轮数
    summary_max_tokens: int = 2000  # 摘要最大 Token 数

    # ==================== Human-in-the-Loop ====================
    max_iterations: int = 3  # 用户拒绝后最大重新分析次数

    # ==================== Ollama 本地模型（降级方案） ====================
    # 当阿里百炼额度不足时自动降级到本地 Ollama 模型
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:8b"
    ollama_embedding_model: str = "qwen2.5:7b"

    # ==================== Milvus 集合配置 ====================
    milvus_collection: str = "product_catalog"  # 商品目录集合名
    milvus_dense_dim: int = 1024  # 密集向量维度

    # ==================== RAG 检索参数 ====================
    rag_dense_weight: float = 0.7   # 密集向量检索权重（语义匹配）
    rag_sparse_weight: float = 0.3  # 稀疏向量检索权重（关键词匹配）
    rag_top_k: int = 20  # 检索返回 TOP K 条结果

    # ==================== 报告输出 ====================
    report_output_dir: str = "reports"  # 报告文件输出目录

    # ==================== 用户认证 ====================
    jwt_secret_key: str = "change-me-in-production"  # JWT 签名密钥，生产环境务必修改
    jwt_expire_hours: int = 24  # Token 过期时间（小时）

    # ==================== 数据库 ====================
    auth_db_path: str = "data/auth.db"  # 用户认证数据库路径
    task_db_path: str = "data/tasks.db"  # 任务管理数据库路径


# 全局单例，各模块直接导入使用
settings = Settings()
