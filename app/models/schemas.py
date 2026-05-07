"""
Pydantic 数据模型定义

定义了系统中使用的核心数据结构，包括：
- Product: 商品数据模型（统一结构，多平台通用）
- AnalysisParams: 分析请求参数
- OverviewData: 分析概览
- UserDecision: 用户决策
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from .enums import Platform, Dimension, TimeRange


class Product(BaseModel):
    """统一商品数据模型

    所有数据源（RAG / MCP / LLM 兜底）返回的数据都映射为此结构。
    字段设计覆盖了各电商平台的共有属性，缺失字段留空。
    """
    id: str = ""                           # 商品唯一标识
    platform: str = Platform.TAVILY.value   # 来源平台
    name: str = ""                         # 商品名称
    price: float = 0.0                     # 价格
    category: str = ""                     # 品类
    material: str = ""                     # 材质
    color: str = ""                        # 配色
    style: str = ""                        # 风格
    target_audience: str = ""              # 目标人群
    sales_volume: int = 0                  # 销量
    revenue: Optional[float] = None        # 销售额（部分平台提供）
    description: str = ""                  # 商品描述
    tags: list[str] = []                   # 标签列表
    publish_time: Optional[datetime] = None  # 发布时间
    source_url: str = ""                   # 来源链接


class AnalysisParams(BaseModel):
    """分析请求参数

    从用户输入的意图识别中提取，驱动后续数据采集和分析流程。
    """
    product: str = ""                      # 分析的商品/品类名称
    platforms: list[str] = Field(          # 数据来源平台列表
        default_factory=lambda: [Platform.ALL.value]
    )
    dimensions: list[str] = Field(         # 分析维度列表
        default_factory=lambda: [d.value for d in Dimension]
    )
    time_range: str = TimeRange.DAY30.value  # 时间范围
    custom_start: Optional[str] = None     # 自定义起始日期
    custom_end: Optional[str] = None       # 自定义结束日期


class OverviewData(BaseModel):
    """分析概览数据

    在最终报告生成前展示给用户确认的概要信息。
    用户确认后进入最终报告生成，拒绝后可输入反馈重新分析。
    """
    title: str = ""                        # 报告标题
    summary: str = ""                      # 总体摘要
    key_findings: list[str] = []           # 核心发现列表
    dimension_count: int = 0               # 已分析维度数
    platform_count: int = 0                # 数据来源平台数
    data_points: int = 0                   # 数据量


class UserDecision(BaseModel):
    """用户决策模型

    Human-in-the-Loop 中用户对概览的反馈。
    action 取值：confirm（确认）/ reject（拒绝+反馈）/ terminate（终止）
    """
    action: str        # 用户操作类型
    feedback: str = ""  # 改进建议（reject 时必填）
