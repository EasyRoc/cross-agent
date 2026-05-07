"""
阿里百炼 LLM 客户端

基于阿里百炼兼容的 OpenAI SDK 封装，提供：
- chat: 非流式对话，返回完整文本
- chat_stream: 流式对话，异步生成器逐 token 返回
- chat_json: JSON 模式对话，自动解析返回结构体
- embed: 文本向量化

注：阿里百炼兼容 OpenAI SDK 协议，因此使用 openai 包即可直连。
"""

import json
import time
from typing import AsyncGenerator
from openai import AsyncOpenAI, APIError
from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


class BailianClient:
    """阿里百炼 LLM 客户端

    单例模式，全局共享一个客户端实例。
    所有 LLM 调用通过此类完成，便于统一管理 API Key、模型选择和重试策略。
    """

    def __init__(self):
        """初始化 OpenAI 兼容客户端"""
        self.client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )
        logger.info(
            "阿里百炼客户端初始化完成，模型配置: intent=%s, analysis=%s, report=%s, embedding=%s",
            settings.intent_model,
            settings.analysis_model,
            settings.report_model,
            settings.embedding_model,
        )

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.1,
        response_format: dict | None = None,
    ) -> str:
        """非流式 LLM 对话

        Args:
            messages: 对话消息列表 [{"role": "user", "content": "..."}]
            model: 模型名，默认使用 analysis_model
            temperature: 生成温度，0.1 偏确定，0.7 偏创造
            response_format: 响应格式约束，如 {"type": "json_object"}

        Returns:
            模型返回的文本内容

        Raises:
            APIError: API 调用失败
        """
        start_time = time.time()
        kwargs = {
            "model": model or settings.analysis_model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format

        # 记录请求摘要（消息太长时截断）
        msg_preview = messages[-1]["content"][:100] if messages else ""
        logger.debug("LLM 请求 [%s]: %s...", kwargs["model"], msg_preview)

        try:
            resp = await self.client.chat.completions.create(**kwargs)
            result = resp.choices[0].message.content or ""
            elapsed = time.time() - start_time
            logger.debug("LLM 响应完成，耗时 %.2fs，长度 %d 字符", elapsed, len(result))
            return result
        except APIError as e:
            logger.error("LLM API 调用失败: %s", e)
            raise

    async def chat_stream(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.1,
    ) -> AsyncGenerator[str, None]:
        """流式 LLM 对话

        通过异步生成器逐 token 返回结果，适合实时展示场景。
        使用 async for token in client.chat_stream(...) 消费。

        Yields:
            逐 token 的文本片段
        """
        stream = await self.client.chat.completions.create(
            model=model or settings.analysis_model,
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

        logger.debug("流式响应完成，共 %d 个 token", token_count)

    async def chat_json(self, messages: list[dict], model: str | None = None) -> dict:
        """JSON 模式对话

        调用 LLM 并强制返回 JSON 格式，自动解析为 Python dict。
        用于意图识别、参数提取等需要结构化输出的场景。

        Args:
            messages: 对话消息
            model: 模型名

        Returns:
            解析后的 JSON 字典
        """
        text = await self.chat(
            messages=messages,
            model=model or settings.analysis_model,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("JSON 解析失败: %s, 原始内容: %s...", e, text[:200])
            return {}

    async def embed(self, text: str) -> list[float]:
        """生成文本向量

        使用 text-embedding-v3 模型将文本转为向量。
        用于 Milvus 向量检索的查询向量生成。

        Args:
            text: 待向量化的文本

        Returns:
            float 类型的向量列表
        """
        start_time = time.time()
        resp = await self.client.embeddings.create(
            model=settings.embedding_model,
            input=text,
        )
        vector = resp.data[0].embedding
        elapsed = time.time() - start_time
        logger.debug("向量化完成，耗时 %.2fs，维度 %d", elapsed, len(vector))
        return vector


# ==================== 全局单例 ====================

_client: BailianClient | None = None


def get_llm_client() -> BailianClient:
    """获取 LLM 客户端单例

    全局共享一个客户端实例，避免重复创建连接。
    """
    global _client
    if _client is None:
        logger.info("首次初始化 LLM 客户端")
        _client = BailianClient()
    return _client
