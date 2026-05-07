"""
MCP（Model Context Protocol）基类

定义统一的数据源接口和数据模型。
所有平台 MCP 实现（小红书、抖音、淘宝、Tavily 等）都继承 BaseMCP。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ProductResult:
    """统一商品数据模型

    各平台的数据结构不同，但通过此模型统一对外输出。
    缺失的字段留空，不影响后续分析流程。

    设计原则：
    - 覆盖各电商平台的共有属性
    - 缺失字段留空而非抛出异常
    - 提供 to_dict() 方法方便序列化
    """
    platform: str = ""              # 来源平台标识
    name: str = ""                  # 商品名称
    price: float = 0.0              # 价格（元）
    category: str = ""              # 品类
    material: str = ""              # 材质
    color: str = ""                 # 配色
    style: str = ""                 # 风格
    target_audience: str = ""       # 目标人群
    sales_volume: int = 0           # 销量（近30天）
    revenue: Optional[float] = None # 销售额
    description: str = ""           # 商品描述
    tags: list[str] = field(default_factory=list)  # 标签
    source_url: str = ""            # 来源链接
    publish_date: str = ""          # 发布日期

    def to_dict(self) -> dict:
        """转为字典，过滤空值字段"""
        return {k: v for k, v in asdict(self).items() if v}


class BaseMCP(ABC):
    """数据源基类

    所有平台 MCP 必须实现 search 方法。
    """

    @abstractmethod
    async def search(self, query: str, **kwargs) -> list[ProductResult]:
        """搜索商品数据

        Args:
            query: 搜索关键词
            **kwargs: 各平台的特定参数（如时间范围、数量限制等）

        Returns:
            匹配的商品列表
        """
        ...
