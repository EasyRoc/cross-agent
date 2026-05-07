"""
Agent Prompt 模板

集中管理所有 LLM Prompt 模板，便于维护和调优。
每个模板使用 '{placeholder}' 格式的参数占位符。

Prompt 目录：
1. INTENT_PROMPT — 意图识别（二分类：分析请求 vs 普通对话）
2. PARAMS_EXTRACT_PROMPT — 分析参数提取（商品/平台/维度/时间）
3. ANALYSIS_PROMPT — 单维度商品分析
4. OVERVIEW_PROMPT — 概览生成（汇总各维度结果）
5. QUALITY_REVIEW_PROMPT — 质量审核
6. REPORT_PROMPT — 最终报告生成
7. REANALYSIS_PROMPT — 根据用户反馈重新分析
"""

# ==================== 意图识别 ====================

INTENT_PROMPT = """你是一个商品分析系统的意图识别器。
判断用户输入属于以下哪一类：
1. product_analysis — 商品分析请求（如 "男式衬衫爆款分析"、"运动鞋2025趋势"、"帮我分析一下夏季女装"）
2. normal_chat — 普通对话（如 "你好"、"今天天气怎么样"、"你是谁"）

用户输入：{user_input}

输出 JSON（不要带 markdown 代码块标记）：
{{"intent": "product_analysis" | "normal_chat", "confidence": 0.0~1.0}}"""

# ==================== 参数提取 ====================

PARAMS_EXTRACT_PROMPT = """从用户请求中提取商品分析参数。

用户请求：{user_input}

可用平台：{platforms}
可用分析维度：{dimensions}
时间范围选项：近7天、近30天、近90天、自定义

输出 JSON（不要带 markdown 代码块标记）：
{{
  "product": "商品/品类名称",
  "platforms": ["平台1", "平台2"],
  "dimensions": ["维度1", "维度2"],
  "time_range": "近7天|近30天|近90天|自定义",
  "custom_start": null,
  "custom_end": null
}}

注意：如果用户没有指定时间范围，默认用"近30天"。如果用户没指定平台，默认用["全网"]。如果用户没指定维度，默认包含所有维度。"""

# ==================== 单维度分析 ====================

ANALYSIS_PROMPT = """你是电商商品分析专家。请根据以下商品数据，从"{dimension}"维度进行深入分析。

分析要求：
- 商品品类：{product}
- 时间范围：{time_range}
- 数据维度：{dimension}

商品数据（JSON）：
{raw_data}

请从以下方面进行分析（用中文回答）：
1. 这个维度的整体情况
2. 主要发现和趋势
3. 具体数据支撑
4. 如果有多个平台，做跨平台对比

回答要简洁、有数据支撑、有洞察。控制在 300 字以内。"""

# ==================== 概览生成 ====================

OVERVIEW_PROMPT = """你是商品分析报告的总编。请根据以下多维度分析结果，生成一份简洁的分析概览，用于给用户确认。

商品品类：{product}
时间范围：{time_range}
数据源：{platforms}
数据量：{data_count} 条商品数据
分析维度：{dimensions}

各维度分析结果：
{analysis_results}

请生成 JSON 格式的概览：
{{
  "title": "报告标题",
  "summary": "一段总体摘要（100字以内）",
  "key_findings": ["核心发现1", "核心发现2", "核心发现3"],
  "dimension_summaries": {{
    "维度名": "该维度的关键结论（30字以内）"
  }}
}}

不要带 markdown 代码块标记。"""

# ==================== 质量审核 ====================

QUALITY_REVIEW_PROMPT = """你是质量审核专家。审核以下商品分析结果的完整性和质量。

请求参数：{params}
分析维度结果：{analysis_results}
原始数据量：{data_count}

审核维度：
1. 完整性：是否覆盖了所有请求的分析维度？
2. 数据支撑：分析结论是否有数据支持？
3. 一致性：各维度分析结论是否矛盾？
4. 深度：分析是否流于表面？
5. 可操作性：建议是否具体可行？

输出 JSON（不要带 markdown 代码块标记）：
{{
  "passed": true/false,
  "score": 0-100,
  "issues": [{{"severity": "high|medium|low", "description": "..."}}],
  "missing_dimensions": ["..."],
  "suggestions": ["改进建议1", "改进建议2"]
}}"""

# ==================== 最终报告 ====================

REPORT_PROMPT = """你是商品分析报告撰写专家。请根据以下分析结果，生成一份完整的 Markdown 格式分析报告。

商品品类：{product}
时间范围：{time_range}
数据源：{platforms}
数据量：{data_count}

各维度分析结果：
{analysis_results}

请按照以下模板生成报告：

# {product} 市场分析报告

> 分析时间范围：{time_range}
> 数据来源：{platforms}
> 生成时间：{generated_time}

---

## 一、核心发现

（列出 3-5 条核心发现）

## 二、市场概况

### 2.1 市场体量
### 2.2 增长趋势
### 2.3 竞争格局

## 三、多维度分析

（每个维度作为一个小节）

## 四、策略建议

### 4.1 产品策略
### 4.2 定价策略
### 4.3 营销策略

## 五、风险提示

---

*本报告由 AI 商品分析 Agent 自动生成，数据仅供参考。*

注意：报告内容要详实、有洞察，每个维度分析要有数据支撑和 actionable 的建议。不要只写标题没有内容。"""

# ==================== 重新分析（根据反馈改进） ====================

REANALYSIS_PROMPT = """用户对之前的分析结果不满意，给出了以下反馈：
{feedback}

请根据用户反馈，重新从"{dimension}"维度进行分析。

原始商品数据（JSON）：
{raw_data}

要求：
- 认真考虑用户反馈中的改进建议
- 输出更有深度和针对性的分析
- 用中文回答，300字以内"""
