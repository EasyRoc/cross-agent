"""
模型枚举定义

定义系统中使用的所有枚举类型，包括：
- Platform: 数据来源平台
- Dimension: 分析维度
- TimeRange: 时间范围
- IntentType: 意图识别结果
- AgentStatus: Agent 状态流转
"""

from enum import Enum


class Platform(str, Enum):
    """数据来源平台枚举"""
    XIAOHONGSHU = "小红书"
    DOUYIN = "抖音"
    TAOBAO = "淘宝"
    AMAZON = "亚马逊"
    DEWU = "得物"
    TAVILY = "tavily"    # 网络检索 MCP
    ALL = "全网"          # 全部平台


class Dimension(str, Enum):
    """商品分析维度枚举，共 12 个维度"""
    爆款 = "爆款"           # 销量排名、增长率、爆款特征
    配色 = "配色"           # 热门色系、色彩分布趋势
    价格带 = "价格带"       # 价格区间分布、性价比分析
    品类 = "品类"           # 子品类分布、品类关联
    材质 = "材质"           # 材质分布、新兴材质趋势
    风格 = "风格"           # 风格分类、风格演变
    人群 = "人群"           # 目标人群画像、消费力分层
    购买动机 = "购买动机"   # 驱动因素、决策因素分析
    痛点 = "痛点"           # 用户不满、退货原因
    使用场景 = "使用场景"   # 场景分类、场景-品类关联
    购买路径 = "购买路径"   # 触点分析、决策链路
    生命周期 = "生命周期"   # 新品/成长期/成熟期/衰退期


# 所有维度的值列表，用于默认全量分析
ALL_DIMENSIONS = [d.value for d in Dimension]


class TimeRange(str, Enum):
    """时间范围枚举"""
    DAY7 = "近7天"
    DAY30 = "近30天"     # 默认值
    DAY90 = "近90天"
    CUSTOM = "自定义"     # 用户自定义起止日期


class IntentType(str, Enum):
    """意图识别结果枚举"""
    PRODUCT_ANALYSIS = "product_analysis"  # 商品分析请求
    NORMAL_CHAT = "normal_chat"            # 普通对话


class AgentStatus(str, Enum):
    """Agent 状态流转枚举

    状态转换图：
    pending → overview_generated → confirmed → completed
                                 → rejected → pending
                                 → terminated
    """
    PENDING = "pending"                   # 等待处理
    OVERVIEW_GENERATED = "overview_generated"  # 概览已生成，等待用户确认
    CONFIRMED = "confirmed"               # 用户已确认
    REJECTED = "rejected"                 # 用户拒绝，需要重新分析
    COMPLETED = "completed"               # 报告已生成
    TERMINATED = "terminated"             # 用户终止分析
