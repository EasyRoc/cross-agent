"""
报告生成器

负责将最终分析报告保存为 Markdown 和 PDF 格式。
- Markdown: 直接保存 .md 文件
- PDF: 经 Markdown → HTML → weasyprint → PDF 转换

PDF 转换依赖 weasyprint 库，如安装失败会自动回退到 Markdown。
"""

import markdown
from pathlib import Path
from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


class ReportGenerator:
    """报告文件生成器

    将报告文本保存为文件，支持 Markdown 和 PDF 两种格式。

    用法：
        gen = ReportGenerator()
        md_path = gen.save_markdown(content, filename)
        pdf_path = gen.save_pdf(content, filename)
    """

    def __init__(self):
        self.output_dir = Path(settings.report_output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("报告输出目录: %s", self.output_dir.absolute())

    def save_markdown(self, content: str, filename: str) -> str:
        """保存 Markdown 文件

        Args:
            content: Markdown 格式的报告内容
            filename: 文件名（不含扩展名）

        Returns:
            文件的完整路径
        """
        filepath = self.output_dir / f"{filename}.md"
        filepath.write_text(content, encoding="utf-8")
        logger.info("Markdown 报告已保存: %s (%d 字符)", filepath, len(content))
        return str(filepath)

    def markdown_to_html(self, md_content: str) -> str:
        """将 Markdown 转换为 HTML

        使用 Python-Markdown 库，启用 extra 和 codehilite 扩展。

        Args:
            md_content: Markdown 文本

        Returns:
            HTML 字符串
        """
        return markdown.markdown(
            md_content,
            extensions=["extra", "codehilite", "toc"],
        )

    def save_pdf(self, md_content: str, filename: str) -> str:
        """将报告保存为 PDF

        流程：Markdown → HTML → 添加样式 → weasyprint 渲染 PDF。

        Args:
            md_content: Markdown 格式的报告内容
            filename: 文件名（不含扩展名）

        Returns:
            PDF 文件的完整路径；若 weasyprint 不可用则回退到 .md
        """
        html_content = self.markdown_to_html(md_content)

        # 为 PDF 添加打印样式
        styled_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; padding: 40px; line-height: 1.8; color: #333; }}
h1 {{ color: #1a1a1a; border-bottom: 2px solid #2563eb; padding-bottom: 10px; }}
h2 {{ color: #2563eb; margin-top: 30px; }}
h3 {{ color: #374151; }}
blockquote {{ background: #f3f4f6; padding: 10px 20px; border-left: 4px solid #2563eb; margin: 0; }}
p {{ margin: 8px 0; }}
ul {{ margin: 8px 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f3f4f6; }}
</style>
</head>
<body>
{html_content}
</body>
</html>"""

        filepath = self.output_dir / f"{filename}.pdf"
        try:
            from weasyprint import HTML
            HTML(string=styled_html).write_pdf(str(filepath))
            logger.info("PDF 报告已保存: %s", filepath)
        except Exception as e:
            logger.warning("PDF 生成失败（%s），回退到 Markdown", e)
            return self.save_markdown(md_content, filename)

        return str(filepath)


# ==================== 全局单例 ====================

_report_gen: ReportGenerator | None = None


def get_report_generator() -> ReportGenerator:
    """获取报告生成器单例"""
    global _report_gen
    if _report_gen is None:
        logger.info("首次初始化报告生成器")
        _report_gen = ReportGenerator()
    return _report_gen
