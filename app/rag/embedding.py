"""
向量化服务

使用阿里百炼 text-embedding-v3 模型将文本转为向量。
支持单条和批量向量化，供 Milvus 检索使用。
"""

from app.llm.client import get_llm_client
from app.logger import get_logger

logger = get_logger(__name__)


class EmbeddingService:
    """向量化服务

    封装了阿里百炼的 Embedding 调用，提供便捷的向量化接口。

    用法：
        service = EmbeddingService()
        vector = await service.embed("男式衬衫")
        vectors = await service.embed_batch(["衬衫", "运动鞋"])
    """

    def __init__(self):
        self.llm = get_llm_client()

    async def embed(self, text: str) -> list[float]:
        """单条文本向量化

        Args:
            text: 待向量化的文本

        Returns:
            float 向量列表
        """
        logger.debug("向量化文本: %s...", text[:50])
        vector = await self.llm.embed(text)
        logger.debug("向量化完成，维度 %d", len(vector))
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化

        Args:
            texts: 文本列表

        Returns:
            向量列表，与输入顺序一致
        """
        import asyncio
        logger.debug("批量向量化 %d 条文本", len(texts))
        tasks = [self.embed(t) for t in texts]
        results = await asyncio.gather(*tasks)
        logger.debug("批量向量化完成")
        return results


# ==================== 全局单例 ====================

_embedding: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """获取 Embedding 服务单例"""
    global _embedding
    if _embedding is None:
        logger.info("首次初始化 Embedding 服务")
        _embedding = EmbeddingService()
    return _embedding
