"""
摘要记忆模块

当短期记忆超出窗口时，自动调用 LLM 对历史对话进行总结摘要。
保留最近 N 轮完整的对话，较旧的内容用摘要代替，兼顾上下文和 Token 限制。
"""

from app.llm.client import get_llm_client
from app.logger import get_logger

logger = get_logger(__name__)

# 用于 LLM 摘要生成的 prompt 模板
SUMMARY_PROMPT = """请总结以上对话的核心内容，保留与商品分析相关的关键信息。
如果已有历史摘要，请在原有摘要基础上补充新内容，不要重复。

历史摘要：{summary}

新对话内容：{new_messages}

请生成一个简洁的摘要（200字以内）："""


class SummaryMemory:
    """摘要记忆管理器

    当消息数量超过阈值时，将较早的消息总结为一段摘要文本，
    只保留最近 N 条完整消息，解决长会话的 Token 超限问题。

    用法：
        memory = SummaryMemory()
        new_summary, recent_msgs = await memory.summarize(messages, existing_summary)
    """

    def __init__(self, max_token_limit: int = 2000):
        """
        Args:
            max_token_limit: 摘要的最大 Token 限制（暂未严格使用，保留扩展）
        """
        self.max_token_limit = max_token_limit
        self.llm = get_llm_client()

    async def summarize(
        self,
        messages: list[dict],
        existing_summary: str = "",
        keep_last: int = 10,
    ) -> tuple[str, list[dict]]:
        """总结历史消息

        将 keep_last 条之前的消息总结为摘要，保留最近 keep_last 条完整消息。

        Args:
            messages: 完整消息列表
            existing_summary: 已有的历史摘要（追加模式）
            keep_last: 保留的最近消息条数

        Returns:
            (新摘要, 保留的最近消息列表) 的元组
        """
        # 如果消息数量未超过阈值，不做摘要处理
        if len(messages) <= keep_last:
            logger.debug("消息数量 %d 未超过阈值 %d，跳过摘要", len(messages), keep_last)
            return existing_summary, messages

        # 分离老消息和最近消息
        old_messages = messages[:-keep_last]
        recent_messages = messages[-keep_last:]

        # 将老消息拼接为文本
        old_text = "\n".join(
            f"{m['role']}: {m['content'][:500]}"
            for m in old_messages
        )

        prompt = SUMMARY_PROMPT.format(
            summary=existing_summary or "无历史摘要",
            new_messages=old_text,
        )

        logger.info("正在生成对话摘要，历史摘要长度 %d，新消息 %d 条",
                     len(existing_summary), len(old_messages))

        new_summary = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model="qwen-plus",
        )

        logger.info("摘要生成完成，新摘要长度 %d 字符", len(new_summary))
        return new_summary.strip(), recent_messages
