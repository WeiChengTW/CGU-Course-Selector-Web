"""模板配置 - 使用 Jinja2 直接渲染"""

from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from fastapi.responses import HTMLResponse

# 模板目錄
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Jinja2 環境
env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(['html', 'xml']),
)


def render_template(name: str, context: dict) -> HTMLResponse:
    """渲染模板並返回 HTMLResponse"""
    template = env.get_template(name)
    return HTMLResponse(content=template.render(**context))