"""
MCP 工厂模块

管理所有数据源实例，提供统一的并行采集能力。
采用工厂模式，支持按需加载和扩展新的数据源。

数据源采集策略：
1. 并行调用所有指定平台
2. 自动过滤空值和无数据结果
3. 数据不足时自动触发 LLM 兜底
"""

from app.mcp.base import BaseMCP
from app.mcp.tavily import TavilyMCP
from app.models.enums import Platform
from app.logger import get_logger

logger = get_logger(__name__)


class MCPFactory:
    """MCP 工厂类

    管理和获取各平台 MCP 实例，支持并行采集和自动兜底。

    用法：
        factory = MCPFactory()
        results = await factory.search_all("男式衬衫", ["全网"], "近30天")
    """

    def __init__(self):
        # 缓存已初始化的 MCP 实例
        self._instances: dict[str, BaseMCP] = {}

    def get(self, source: str) -> BaseMCP | None:
        """获取指定数据源的 MCP 实例

        首次获取时会创建实例，后续复用。

        Args:
            source: 数据源标识（Platform 枚举值）

        Returns:
            MCP 实例，不支持的数据源返回 None
        """
        if source not in self._instances:
            self._instances[source] = self._create(source)
        return self._instances.get(source)

    def _create(self, source: str) -> BaseMCP | None:
        """创建数据源实例

        目前实现了 Tavily 网络检索，其他平台可在此扩展。

        Args:
            source: 数据源标识

        Returns:
            MCP 实例，不支持的源返回 None
        """
        if source == Platform.TAVILY.value:
            logger.debug("创建 Tavily MCP 实例")
            return TavilyMCP()
        # 扩展点：新增平台在此添加
        # if source == Platform.XIAOHONGSHU.value:
        #     return XiaohongshuMCP()
        # if source == Platform.DOUYIN.value:
        #     return DouyinMCP()
        logger.debug("不支持的平台: %s", source)
        return None

    async def search_all(
        self,
        query: str,
        platforms: list[str],
        time_range: str = "近30天",
    ) -> list[dict]:
        """从所有指定平台并行采集数据

        采集策略：
        1. Tavily 始终作为补充数据源
        2. 各电商平台 MCP 并行搜索
        3. 数据不足 3 条时触发 LLM 兜底

        Args:
            query: 搜索关键词
            platforms: 目标平台列表
            time_range: 时间范围

        Returns:
            去重后的商品数据字典列表
        """
        import asyncio

        logger.info("开始多源采集: query=%s, platforms=%s, time=%s",
                     query, platforms, time_range)

        tasks = []

        # 1. Tavily 网络检索（始终作为补充）
        tavily = self.get(Platform.TAVILY.value)
        if tavily:
            tasks.append(tavily.search(query, time_range=time_range))

        # 2. 各电商平台 MCP 搜索
        for p in platforms:
            if p in (Platform.ALL.value, Platform.TAVILY.value):
                continue  # "全网"不分配给具体平台
            mcp = self.get(p)
            if mcp:
                tasks.append(mcp.search(query, time_range=time_range))

        # 并行执行所有搜索
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 收集非异常结果
        all_products = []
        for i, r in enumerate(results):
            if isinstance(r, list):
                all_products.extend(p.to_dict() for p in r)
            elif isinstance(r, Exception):
                logger.warning("数据源 %d 采集失败: %s", i, r)

        logger.info("原始采集 %d 条商品数据", len(all_products))

        # 3. LLM 兜底：数据太少时自动触发
        if len(all_products) < 3 and tavily:
            logger.info("数据不足（%d条），触发 LLM 兜底生成", len(all_products))
            fallback = await tavily.fallback_generate(query, ",".join(platforms), time_range)
            all_products.extend(p.to_dict() for p in fallback)

        # 去重（按名称+平台去重）
        seen = set()
        unique = []
        for item in all_products:
            key = (item.get("name", ""), item.get("platform", ""))
            if key not in seen and item.get("name"):
                seen.add(key)
                unique.append(item)

        logger.info("去重后共 %d 条商品数据", len(unique))
        return unique


# ==================== 全局单例 ====================

_factory: MCPFactory | None = None


def get_mcp_factory() -> MCPFactory:
    """获取 MCP 工厂单例"""
    global _factory
    if _factory is None:
        _factory = MCPFactory()
    return _factory
