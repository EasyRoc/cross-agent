"""
统一 LLM 客户端

封装阿里百炼（付费）和 Ollama（本地）两个后端，
当阿里百炼额度不足时自动降级到本地 Ollama 模型。
所有模块通过 `get_llm_client()` 获取实例，接口与之前兼容。
"""

import json
import time
from typing import AsyncGenerator
from openai import AsyncOpenAI, RateLimitError, APIError, APIStatusError
import httpx
from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


def _is_quota_error(e: Exception) -> bool:
    """判断异常是否为额度/限流错误"""
    status = None
    if isinstance(e, RateLimitError):
        return True
    if isinstance(e, APIStatusError):
        status = e.status_code
    elif isinstance(e, APIError):
        status = getattr(e, "status_code", None)
    return status in (402, 429)


class LLMClient:
    """统一 LLM 客户端（阿里百炼 → Ollama 自动降级）

    与之前的 BailianClient 方法签名完全一致，
    使用时无需关心后端是哪一家。
    """

    def __init__(self):
        self._bailian = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )
        self._ollama = AsyncOpenAI(
            api_key="ollama",
            base_url=settings.ollama_base_url,
        )
        # Ollama 原生 API 地址（不带 /v1 后缀）
        self._ollama_native_base = settings.ollama_base_url.rstrip("/v1").rstrip("/")
        # 是否处于降级模式（True 时直接走 Ollama，不再重试 Bailian）
        self._fallback = False

        logger.info(
            "LLM 客户端初始化完成，"
            "主后端: 阿里百炼 (intent=%s, analysis=%s, report=%s, embedding=%s)，"
            "降级后端: Ollama (%s)",
            settings.intent_model,
            settings.analysis_model,
            settings.report_model,
            settings.embedding_model,
            settings.ollama_model,
        )

    # ---------- 模型映射 ----------

    def _resolve_model(self, model: str | None, task: str = "analysis") -> str:
        """根据任务类型和降级状态解析实际模型名"""
        if model:
            return model
        if self._fallback:
            return settings.ollama_model
        mapping = {
            "intent": settings.intent_model,
            "analysis": settings.analysis_model,
            "report": settings.report_model,
            "summary": settings.summary_model,
            "embedding": settings.embedding_model,
        }
        return mapping.get(task, settings.analysis_model)

    def _provider(self):
        """获取当前使用的后端客户端"""
        return self._ollama if self._fallback else self._bailian

    # ---------- 核心方法 ----------

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.1,
        response_format: dict | None = None,
    ) -> str:
        """非流式 LLM 对话（自动降级）"""
        provider_name = "Ollama" if self._fallback else "阿里百炼"
        resolved = self._resolve_model(model)

        start = time.time()
        kwargs = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format

        msg_preview = messages[-1]["content"][:100] if messages else ""
        logger.debug("LLM 请求 [%s@%s]: %s...", resolved, provider_name, msg_preview)

        try:
            resp = await self._provider().chat.completions.create(**kwargs)
            result = resp.choices[0].message.content or ""
            logger.debug(
                "LLM 响应完成 [%s@%s]，耗时 %.2fs，长度 %d",
                resolved, provider_name, time.time() - start, len(result),
            )
            return result
        except (RateLimitError, APIError) as e:
            if not self._fallback and _is_quota_error(e):
                logger.warning("阿里百炼额度不足 (%s)，降级到本地 Ollama 模型", e)
                self._fallback = True
                return await self.chat(messages, model, temperature, response_format)
            logger.error("LLM 调用失败 [%s]: %s", provider_name, e)
            raise

    async def chat_stream(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.1,
    ) -> AsyncGenerator[str, None]:
        """流式 LLM 对话（自动降级）"""
        provider_name = "Ollama" if self._fallback else "阿里百炼"
        resolved = self._resolve_model(model)

        logger.debug("LLM 流式请求 [%s@%s]", resolved, provider_name)

        try:
            stream = await self._provider().chat.completions.create(
                model=resolved,
                messages=messages,
                temperature=temperature,
                stream=True,
            )
            token_count = 0
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    token_count += 1
                    yield content
            logger.debug("LLM 流式完成 [%s@%s]，共 %d token", resolved, provider_name, token_count)
        except (RateLimitError, APIError) as e:
            if not self._fallback and _is_quota_error(e):
                logger.warning("阿里百炼流式额度不足 (%s)，降级到本地 Ollama", e)
                self._fallback = True
                async for token in self.chat_stream(messages, model, temperature):
                    yield token
            else:
                logger.error("LLM 流式调用失败 [%s]: %s", provider_name, e)
                raise

    async def chat_json(self, messages: list[dict], model: str | None = None) -> dict:
        """JSON 模式对话（自动降级）"""
        text = await self.chat(
            messages=messages,
            model=model,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("JSON 解析失败: %s, 原始内容: %s...", e, text[:200])
            return {}

    async def embed(self, text: str) -> list[float]:
        """生成文本向量（自动降级）

        阿里百炼走 OpenAI 兼容 API，Ollama 走原生 /api/embed。
        """
        start = time.time()

        # ----- 阿里百炼（OpenAI 兼容 API） -----
        if not self._fallback:
            try:
                resp = await self._bailian.embeddings.create(
                    model=settings.embedding_model,
                    input=text,
                )
                vector = resp.data[0].embedding
                logger.debug(
                    "向量化完成 [%s@阿里百炼]，耗时 %.2fs，维度 %d",
                    settings.embedding_model, time.time() - start, len(vector),
                )
                return vector
            except (RateLimitError, APIError) as e:
                if _is_quota_error(e):
                    logger.warning("阿里百炼向量化额度不足 (%s)，降级到本地 Ollama", e)
                    self._fallback = True
                    return await self.embed(text)
                logger.error("阿里百炼向量化失败: %s", e)
                raise

        # ----- Ollama（原生 /api/embed） -----
        url = f"{self._ollama_native_base}/api/embed"
        payload = {
            "model": settings.ollama_embedding_model,
            "input": text,
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error("Ollama 向量化失败: %s", e)
            raise

        embeddings = data.get("embeddings", [])
        if not embeddings:
            raise RuntimeError(f"Ollama 向量化返回空结果: {data}")

        vector = embeddings[0]
        logger.debug(
            "向量化完成 [%s@Ollama]，耗时 %.2fs，维度 %d",
            settings.ollama_embedding_model, time.time() - start, len(vector),
        )
        return vector


# ==================== 全局单例 ====================

_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例"""
    global _client
    if _client is None:
        logger.info("首次初始化 LLM 客户端")
        _client = LLMClient()
    return _client
