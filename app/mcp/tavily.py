"""
Tavily 网络检索 MCP

通过 Tavily Search API 进行网络检索，获取公开的商品和市场信息。
当 RAG 和各平台 MCP 数据不足时，也负责 LLM 兜底生成模拟数据。

数据来源优先级：
1. RAG（公司私有商品库）
2. 各平台 MCP（电商平台接口）
3. Tavily（网络检索） ← 本模块
4. LLM 兜底生成（完全由 LLM 生成模拟数据）
"""

from app.config import settings
from app.mcp.base import BaseMCP, ProductResult
from app.logger import get_logger

logger = get_logger(__name__)

# Tavily 搜索结果提取 prompt：从网页搜索结果中提取结构化商品信息
SEARCH_PROMPT = """你是一个商品信息采集助手。请根据以下搜索结果为用户提供结构化商品信息。

搜索结果：
{search_results}

用户查询：{query}

请从以上结果中提取商品信息，按以下 JSON 格式返回（数组）：
[
  {{
    "name": "商品名称",
    "price": 价格数字,
    "category": "品类",
    "material": "材质",
    "color": "配色",
    "style": "风格",
    "target_audience": "目标人群",
    "description": "描述"
  }}
]
如果某些字段无法从结果中推断，请留空字符串。
最多返回 5 条商品。"""

# LLM 兜底生成 prompt：当没有任何外部数据时，由 LLM 生成合理模拟数据
FALLBACK_PROMPT = """你是一个电商商品分析专家。用户需要分析以下品类/商品的市场情况，请根据你的知识生成合理的模拟商品数据。

品类：{query}
平台：{platform}
时间范围：{time_range}

请生成 5 条具有代表性的商品，按 JSON 格式返回：
[
  {{
    "name": "商品名称",
    "price": 价格数字,
    "category": "品类",
    "material": "材质",
    "color": "配色",
    "style": "风格",
    "target_audience": "目标人群",
    "description": "商品描述",
    "tags": ["标签1", "标签2"]
  }}
]

要求：数据要合理、有区分度，覆盖不同价格带和风格。"""


class TavilyMCP(BaseMCP):
    """Tavily 网络检索 MCP

    提供两种能力：
    1. search(): 通过 Tavily API 检索网络，再用 LLM 提取结构化信息
    2. fallback_generate(): 无外部数据时，LLM 直接生成模拟数据
    """

    def __init__(self):
        self.api_key = settings.tavily_api_key
        self._client = None

    @property
    def client(self):
        """延迟初始化 Tavily 客户端，避免缺少 API Key 时报错"""
        if self._client is None and self.api_key:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=self.api_key)
                logger.info("Tavily 客户端初始化成功")
            except Exception as e:
                logger.warning("Tavily 客户端初始化失败: %s", e)
                self._client = None
        return self._client

    async def search(
        self,
        query: str,
        time_range: str = "近30天",
        limit: int = 10,
        **kwargs,
    ) -> list[ProductResult]:
        """通过 Tavily 搜索网络商品信息

        流程：Tavily API 搜索 → LLM 提取结构化数据 → 映射为 ProductResult

        Args:
            query: 搜索关键词
            time_range: 时间范围（近7天/近30天/近90天）
            limit: 返回结果数量上限

        Returns:
            商品数据列表，无结果或出错时返回空列表
        """
        # 未配置 API Key 时直接返回空
        if not self.api_key or not self.client:
            logger.warning("Tavily 未配置 API Key，跳过网络检索")
            return []

        # 时间范围映射
        time_map = {"近7天": "week", "近30天": "month", "近90天": "quarter"}
        t_range = time_map.get(time_range)
        logger.info("Tavily 搜索: query=%s, time_range=%s", query, time_range)

        # 调用 Tavily API
        try:
            response = self.client.search(
                query=f"{query} 商品 市场 分析 趋势",
                search_depth="advanced",
                max_results=limit,
                time_range=t_range,
            )
            results = response.get("results", [])
            logger.info("Tavily 返回 %d 条结果", len(results))
        except Exception as e:
            logger.error("Tavily API 调用失败: %s", e)
            return []

        # 没有搜索结果时提前返回
        if not results:
            return []

        # 用 LLM 从搜索结果中提取结构化商品信息
        from app.llm.client import get_llm_client
        llm = get_llm_client()

        search_text = "\n\n".join(
            f"标题：{r.get('title','')}\n内容：{r.get('content','')}\n链接：{r.get('url','')}"
            for r in results[:10]
        )

        try:
            result_json = await llm.chat_json(
                messages=[{
                    "role": "user",
                    "content": SEARCH_PROMPT.format(search_results=search_text, query=query)
                }],
            )
            items = result_json if isinstance(result_json, list) else result_json.get("results", [])
            logger.debug("LLM 从搜索结果中提取了 %d 条商品", len(items))
        except Exception as e:
            logger.error("LLM 提取商品信息失败: %s", e)
            items = []

        # 映射为统一 ProductResult 格式
        products = []
        for item in items[:5]:
            products.append(ProductResult(
                platform="tavily",
                name=item.get("name", ""),
                price=float(item.get("price", 0)),
                category=item.get("category", ""),
                material=item.get("material", ""),
                color=item.get("color", ""),
                style=item.get("style", ""),
                target_audience=item.get("target_audience", ""),
                description=item.get("description", ""),
                tags=item.get("tags", []),
            ))

        return products

    async def fallback_generate(
        self,
        query: str,
        platform: str = "全网",
        time_range: str = "近30天",
    ) -> list[ProductResult]:
        """LLM 兜底生成商品数据

        当所有数据源（RAG、MCP、网络检索）都无数据时，
        由 LLM 根据自身知识生成合理的模拟商品数据。

        Args:
            query: 商品查询
            platform: 平台名称
            time_range: 时间范围

        Returns:
            模拟商品数据列表
        """
        logger.info("LLM 兜底生成数据: query=%s, platform=%s", query, platform)

        from app.llm.client import get_llm_client
        llm = get_llm_client()

        try:
            result_json = await llm.chat_json(
                messages=[{
                    "role": "user",
                    "content": FALLBACK_PROMPT.format(
                        query=query, platform=platform, time_range=time_range
                    )
                }],
            )
            items = result_json if isinstance(result_json, list) else result_json.get("results", [])
            logger.info("LLM 生成了 %d 条商品数据", len(items))
        except Exception as e:
            logger.error("LLM 兜底生成失败: %s", e)
            items = []

        products = []
        for item in items[:5]:
            products.append(ProductResult(
                platform="llm_fallback",
                name=item.get("name", ""),
                price=float(item.get("price", 0)),
                category=item.get("category", ""),
                material=item.get("material", ""),
                color=item.get("color", ""),
                style=item.get("style", ""),
                target_audience=item.get("target_audience", ""),
                description=item.get("description", ""),
                tags=item.get("tags", []),
            ))

        return products
