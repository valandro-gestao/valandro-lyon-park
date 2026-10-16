"""
Casos compartilhados da referência ("golden") dos relatórios das calculadoras
que NÃO podem mudar — usados por tests/testes_pdf_outras_calculadoras_inalterados.py
e por comparações pontuais de PDF em raster.

Não é um teste (o prefixo `_` o deixa fora do glob `testes_*.py`). Quem importa
precisa definir DATA_DIR (banco isolado) ANTES do import e chamar
`preparar_banco()`.

Os casos usam o data/seed.db versionado + todas as migrations (mesmo padrão
das demais suítes) e uma competência fixa, com a data de emissão congelada —
para que o HTML seja determinístico. Medcenter e Viva Open Mall (RESULTADO_SPLIT)
ficam FORA de propósito: são as únicas unidades cujo relatório muda.
"""
import os
import re
import sys
from datetime import date

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

MES = "2026-05"
HOJE_CONGELADO = date(2026, 10, 16)

# Unidades do seed com lançamento em MES, uma por situação relevante.
UNIDADES_DO_BANCO = [
    "a_schneider", "anitta_mall", "axis", "dom_pedro", "fiergs", "fk", "ilp", "in_1183",
    "monza", "mw_tristeza", "nl_2800", "park_tower", "patio_manutencao", "praia_de_bellas",
    "vasco", "viva_trindade", "w_tower_caxias",
]

EXTRAS_PATIO = {
    "receitas_midia": 4200.0,
    "outros_custos_midia": {"investimentos_equipamentos": 300.0, "troca_de_lona": 150.0},
    "receita_carregadores": 1800.0,
    "custo_energia_carregadores": 600.0,
    "investimento_inicial_carregadores": 0.0,
    "saldo_carregadores": 0.0,
    "custos_variaveis_real": {"condominio": 1500.0},
    "custos_variaveis_maiojama": {"condominio": 1300.0, "iptu": 450.0},
}
FAT_PATIO = 520000.0

UID_DU = "golden_du"
FAIXAS_DU = [{"percentual": 0.5, "ate": 100000.0}, {"percentual": 0.7}]


def preparar_banco():
    from migrations import runner
    runner.run_all(verbose=False)
    from app.models import criar_unidade, salvar_parametros
    from app.engine import load_units
    criar_unidade(UID_DU, "Golden DU", "Contratante DU", "2020-01-01", "COM_ALIQUOTA_CUMUL_DU")
    salvar_parametros(UID_DU, MES, {
        "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
        "faixas_aluguel": FAIXAS_DU,
    }, alterado_por="golden")
    load_units(force=True)


def congelar_data():
    """Congela `date.today()` em app.reporter — a data de emissão entra no HTML."""
    import app.reporter as reporter

    class _DataFixa(date):
        @classmethod
        def today(cls):
            return HOJE_CONGELADO

    reporter.date = _DataFixa


def casos() -> dict:
    """nome -> callable() que devolve o ReportData da competência MES."""
    from app import run_manager as rm
    from app.engine import calcular
    from app.reporter import build_report_data, build_report_data_du

    out = {}

    def _do_banco(uid):
        return lambda: build_report_data(rm.load_resultado_from_db(MES, uid), MES)

    for uid in UNIDADES_DO_BANCO:
        out[uid] = _do_banco(uid)

    def _patio(split):
        def f():
            r_patio = calcular("patio", MES, FAT_PATIO, extras_patio=EXTRAS_PATIO)
            return build_report_data(None, MES, patio_split_id=split, patio_resultado=r_patio)
        return f

    out["patio_real"] = _patio("real")
    out["patio_maiojama"] = _patio("maiojama")

    def _du():
        r = calcular(UID_DU, MES, 250000.0, saldo_override=0.0, custos_extras={})
        return build_report_data(r, MES)

    def _du_aux():
        r = calcular(UID_DU, MES, 250000.0, saldo_override=0.0, custos_extras={})
        return build_report_data_du(r, MES)

    out["cumul_du"] = _du
    out["cumul_du_pdf_auxiliar"] = _du_aux
    return out


def normalizar_html(html: str) -> str:
    """HTML comparável: sem o CSS embutido e o logo (checados à parte), com
    espaços em branco colapsados e uma tag por linha para diffs legíveis."""
    h = re.sub(r"<style.*?</style>", "<style/>", html, flags=re.S)
    h = re.sub(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+", "data:IMG", h)
    h = re.sub(r"\s+", " ", h)
    h = re.sub(r">\s+<", "><", h)
    h = h.replace("><", ">\n<")
    return h.strip() + "\n"
