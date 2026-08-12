"""
Renderizador: ReportData → HTML → PDF
Única responsabilidade: transformar o objeto de dados em arquivo.
"""
from __future__ import annotations
import os, base64
from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.report_data import ReportData

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "../templates")
ASSETS_DIR    = os.path.join(os.path.dirname(__file__), "../assets")
OUTPUT_DIR    = os.path.join(os.path.dirname(__file__), "../output")
LOGO_PATH     = os.path.join(ASSETS_DIR, "logo.png")
CSS_PATH      = os.path.join(TEMPLATES_DIR, "report.css")


def _read_css() -> str:
    with open(CSS_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _logo_base64() -> str:
    with open(LOGO_PATH, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{data}"


def _fmt_br(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    neg = value < 0
    s = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"({s})" if neg else s


def _fmt_pct(value) -> str:
    if value is None:
        return "—"
    return f"{abs(value):.1f}%"


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["fmt_br"]  = _fmt_br
    env.filters["fmt_pct"] = _fmt_pct
    env.filters["abs"]     = abs
    return env


def render_html(report: ReportData) -> str:
    env = _build_env()
    template = env.get_template("relatorio.html")
    return template.render(
        css=_read_css(),
        logo_base64=_logo_base64(),
        unidade=report.unidade,
        cards=report.cards,
        comparativo_12m=report.comparativo_12m,
        comparativo_meses_disponiveis=report.comparativo_meses_disponiveis,
        prestacao=report.prestacao,
        historico=report.historico,
        blocos_receitas=report.blocos_receitas,
        bloco_eventos=report.bloco_eventos,
    )


def export_pdf(html: str, filename: str) -> str:
    try:
        from weasyprint import HTML as WP
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        path = os.path.join(OUTPUT_DIR, filename)
        WP(string=html, base_url=ASSETS_DIR).write_pdf(path)
        return path
    except ImportError:
        raise RuntimeError(
            "WeasyPrint não instalado. Execute: pip install weasyprint"
        )


def render_and_export(report: ReportData, filename: str = None) -> tuple[str, str]:
    """Retorna (html, caminho_pdf)."""
    html = render_html(report)
    nome = filename or f"{report.unidade.competencia}_{report.unidade.nome.replace(' ','_').replace('/','_')}.pdf"
    path = export_pdf(html, nome)
    return html, path
