"""
混合检索模块

实现 Query Rewrite + 向量检索的 RAG 流程：
1. Query Rewrite: 用 LLM 将用户查询改写为更适合检索的关键词
2. 向量化: 将改写后的查询转为稠密向量
3. 向量检索: 在 Milvus 中执行近似最近邻搜索

当前实现使用稠密向量（语义匹配），预留稀疏向量接口供后续扩展。
"""

from app.rag.milvus_client import get_milvus_client
from app.rag.embedding import get_embedding_service
from app.logger import get_logger

logger = get_logger(__name__)

# Query Rewrite prompt：将口语化查询转为检索式关键词
SEARCH_REWRITE_PROMPT = """请将用户查询改写为适合商品向量检索的格式，提取核心商品关键词。

用户查询：{query}

只输出改写后的查询词（20字以内）："""


class HybridSearch:
    """混合检索服务

    流程：用户查询 → LLM 查询重写 → Embedding → Milvus 向量检索

    用法：
        searcher = HybridSearch()
        results = await searcher.search("男式衬衫")
    """

    def __init__(self):
        self.milvus = get_milvus_client()
        self.embedding = get_embedding_service()

    async def search(self, query: str, top_k: int = 20) -> list[dict]:
        """执行混合检索

        Args:
            query: 用户原始查询（如 "夏季男士商务衬衫"）
            top_k: 返回结果数量上限

        Returns:
            商品数据列表，每项包含商品字段和相似度分数
        """
        from app.llm.client import get_llm_client

        logger.info("混合检索开始: query=%s", query)

        # Step 1: Query Rewrite — 用 LLM 优化检索关键词
        llm = get_llm_client()
        try:
            rewritten = await llm.chat(
                messages=[{"role": "user", "content": SEARCH_REWRITE_PROMPT.format(query=query)}],
                temperature=0.1,
            )
            rewritten = rewritten.strip() or query
            logger.info("查询重写: '%s' → '%s'", query, rewritten)
        except Exception as e:
            logger.warning("查询重写失败，使用原始查询: %s", e)
            rewritten = query

        # Step 2: 生成查询向量
        vector = await self.embedding.embed(rewritten)

        # Step 3: Milvus 向量检索
        results = self.milvus.search(vector, top_k=top_k)
        logger.info("混合检索完成: 查询 '%s' 返回 %d 条结果", rewritten, len(results))

        return results
