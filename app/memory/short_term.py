"""
短期记忆模块

维护最近 N 轮对话历史，超出窗口时自动裁剪。
短期记忆是 AgentState.messages 的管理工具，提供添加和裁剪方法。
"""

from app.logger import get_logger

logger = get_logger(__name__)


class ShortTermMemory:
    """短期记忆管理器

    特点：
    - 固定窗口大小，超过时丢弃最早的消息
    - 消息以 [{"role": "user"/"assistant", "content": str}] 格式存储
    - 只做简单的数组管理，不涉及语义理解

    用法：
        memory = ShortTermMemory(window=20)
        messages = memory.add(messages, "user", "你好")
        messages = memory.trim(messages)
    """

    def __init__(self, window: int = 20):
        """
        Args:
            window: 保留的最大对话轮数（不是消息条数）
        """
        self.window = window
        logger.debug("短期记忆初始化，窗口大小: %d 轮", window)

    def add(self, messages: list[dict], role: str, content: str) -> list[dict]:
        """添加一条消息到对话历史

        自动裁剪超出窗口的消息。

        Args:
            messages: 当前消息列表
            role: 角色，user 或 assistant
            content: 消息内容

        Returns:
            更新后的消息列表
        """
        messages.append({"role": role, "content": content})
        if len(messages) > self.window:
            trimmed = len(messages) - self.window
            messages = messages[-self.window:]
            logger.debug("短期记忆已裁剪 %d 条消息", trimmed)
        return messages

    def trim(self, messages: list[dict]) -> list[dict]:
        """裁剪消息列表到窗口大小

        Args:
            messages: 当前消息列表

        Returns:
            裁剪后的消息列表
        """
        if len(messages) > self.window:
            logger.debug("裁剪短期记忆: %d → %d 条", len(messages), self.window)
            return messages[-self.window:]
        return messages
