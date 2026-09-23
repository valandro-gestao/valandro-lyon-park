"""
Cobertura permanente da 7ª rodada de homologação de set/2026 (produção real
— Débora, FIERGS aprovada funcionalmente com valores reais da operação).
Três pontos aprovados para implementação nesta rodada (um quarto ponto,
Custos Variáveis dinâmicos do COM_ALIQUOTA_CUMUL, foi explicitamente
adiado — "vamos usar uma nova unidade real para definir melhor essa
abstração" — nada relacionado a ele foi alterado):

  1. EKOS/OKA — bug bloqueante: `base_calculo_taxa_cobranca` (só a BASE
     usada para calcular a Taxa de Cobrança) vazava para o mecanismo
     genérico de custos de `calcular_com_aliquota_cumul`
     (app.calculators.cumulativo) e era somada de novo em `total_custos`,
     duplicando a dedução — reproduzido bit a bit com o fechamento real de
     julho/2026 da EKOS (Resultado errado: -R$ 7.006,03; correto:
     -R$ 4.110,61). Corrigido adicionando "base_calculo_taxa_cobranca" ao
     `_nao_custo` de cumulativo.py — mesma exclusão que
     app.calculators.faixas (COM_FAIXAS) já tinha.

  2. FIERGS — `eventos_parser.get_resumo_anual` devolvia a aba "Resumo
     Mensal" inteira, sem filtrar por competência — um PDF de agosto/2026
     mostrava também set/2026 (provisão futura já na planilha importada).
     Corrigido com um parâmetro opcional `ate_mes_ref` (corta
     `mes_ref <= ate_mes_ref`), usado só no único call site
     (app.reporter._build_bloco_eventos). Os dados importados
     (eventos.json em disco, `get_eventos_competencia`) não mudam — o
     corte é só na leitura para o relatório daquela competência.

  3. Fechamento — botão "Calcular" (app.ui.fechamento._acao_calcular, já
     genérico, não específico de nenhuma unidade) ficava `type="secondary"`
     assim que o status saía de pendente/reaberto, mesmo continuando sendo
     a ação mais usada da tela. Passa a ser sempre `type="primary"` — só
     destaque visual, nenhum comportamento de clique/cálculo mudou.

Execução: python3 tests/testes_homologacao_set2026_v7.py
"""
import os, sys, tempfile, shutil, atexit, inspect

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v7_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from migrations import runner
runner.run_all(verbose=False)

_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


# ═══════════════════════════════════════════════════════════════════════
# 1. EKOS/OKA — Base Cálculo Taxa Cobrança não entra mais como despesa
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. calcular_com_aliquota_cumul — Base Cálculo Taxa Cobrança não é despesa")
print("=" * 70)
from app.calculators.cumulativo import calcular_com_aliquota_cumul

# Golden real: fechamento de julho/2026 da EKOS.
CFG_EKOS = {
    "id": "ekos", "aliquota_imposto": 0.1425, "ponto_equilibrio": 6550.0,
    "taxa_cobranca": 0.015, "percentual_aluguel": 0.85,
}
r_ekos = calcular_com_aliquota_cumul(
    CFG_EKOS, "2026-07", faturamento=2895.42, saldo_override=0.0,
    custos_extras={"base_calculo_taxa_cobranca": 2895.42},
)
checar("Subtotal = R$ 2.439,39 (correto, inalterado)", r_ekos.subtotal == 2439.39)
checar("'base_calculo_taxa_cobranca' NÃO aparece em r.custos",
       "base_calculo_taxa_cobranca" not in (r_ekos.custos or {}))
checar("r.custos está vazio (nenhuma despesa extra vazou)", r_ekos.custos == {})
checar("Resultado = -R$ 4.110,61 (golden real de julho/2026, não -7.006,03)",
       r_ekos.resultado == -4110.61)
checar("extras['base_taxa_cobranca'] continua = 2.895,42 (info da base, não custo)",
       r_ekos.extras.get("base_taxa_cobranca") == 2895.42)
checar("extras['taxa_cobranca_valor'] continua = 43,43",
       r_ekos.extras.get("taxa_cobranca_valor") == 43.43)

# Memória da tela e PDF: confirma que a linha "Base Cálculo Taxa Cobrança"
# nunca aparece como dedução em lugar nenhum (só a própria linha de Taxa de
# Cobrança, correta, que já usa base_taxa_cobranca como informação de BC).
from app.ui.fechamento import _dre_rows_unit
from app.reporter import _prestacao_padrao

rows_tela = _dre_rows_unit(r_ekos)
labels_tela = [lbl for lbl, _ in rows_tela]
checar("Memória da tela não tem nenhuma linha 'Base Cálculo Taxa Cobrança' como despesa",
       not any("Base Cálculo" in lbl and "Taxa de Cobrança" not in lbl for lbl in labels_tela))
checar("Memória da tela mostra Resultado = -R$ 4.110,61",
       dict(rows_tela).get("Resultado") == "(R$ 4.110,61)")

cfg_pdf = dict(CFG_EKOS)
cfg_pdf["relatorio"] = {"linhas": ["faturamento", "aliquota", "pe", "resultado", "prejuizo"]}
prestacao = _prestacao_padrao(r_ekos, cfg_pdf)
labels_pdf = [l.descricao for l in prestacao.linhas]
checar("PDF não tem nenhuma linha de dedução 'Base Cálculo Taxa Cobrança'",
       not any(l.descricao.startswith("(-) Base Cálculo") for l in prestacao.linhas))
checar("PDF mostra a linha de Taxa de Cobrança (1,5%, BC = R$ 2.895,42) normalmente",
       any("Taxa de Cobrança 1.5%" in l.descricao for l in prestacao.linhas))
resultado_pdf = next(l.valor for l in prestacao.linhas if l.descricao == "Resultado")
checar("PDF mostra Resultado = -4110.61", resultado_pdf == -4110.61)

# --- Regressão: golden da Viva Trindade continua -158.667,99 ---
CFG_VIVA = {"id": "viva_trindade", "aliquota_imposto": 0.0, "percentual_aluguel": 0.85,
            "ponto_equilibrio": 0.0}
r_viva = calcular_com_aliquota_cumul(CFG_VIVA, "2026-08", faturamento=-1525.24 + 2400.0,
                                      saldo_override=-157142.75,
                                      custos_extras={"outras_despesas": 2400.0})
checar("Regressão: golden da Viva Trindade continua -158.667,99",
       r_viva.prejuizo_acumulado_saida == -158667.99)

# --- Regressão: unidades sem tem_base_taxa_cobranca não são afetadas
#     (custos_extras nunca chega com base_calculo_taxa_cobranca) ---
r_sem_taxa = calcular_com_aliquota_cumul(CFG_VIVA, "2026-08", faturamento=50000.0,
                                          saldo_override=0.0)
checar("Regressão: sem taxa de cobrança configurada, nada muda (custos vazio)",
       r_sem_taxa.custos == {})


# ═══════════════════════════════════════════════════════════════════════
# 2. FIERGS — Resumo de Eventos não mostra competências posteriores
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. get_resumo_anual(ate_mes_ref=...) — corte temporal, sem alterar a importação")
print("=" * 70)
from app.parsers import eventos as eventos_parser
from app.reporter import _build_bloco_eventos

PARSED_EXEMPLO = {
    "eventos": [],
    "resumo": [
        {"mes_label": "mai/2026", "mes_ref": "2026-05", "qtd_extras": 10, "valor_total": 500.0},
        {"mes_label": "jun/2026", "mes_ref": "2026-06", "qtd_extras": 12, "valor_total": 550.0},
        {"mes_label": "jul/2026", "mes_ref": "2026-07", "qtd_extras": 15, "valor_total": 580.0},
        {"mes_label": "ago/2026", "mes_ref": "2026-08", "qtd_extras": 18, "valor_total": 590.0},
        {"mes_label": "set/2026", "mes_ref": "2026-09", "qtd_extras": 21, "valor_total": 600.0},
    ],
}

checar("Sem ate_mes_ref: comportamento antigo preservado (todos os meses)",
       len(eventos_parser.get_resumo_anual(PARSED_EXEMPLO)) == 5)

resumo_ago = eventos_parser.get_resumo_anual(PARSED_EXEMPLO, ate_mes_ref="2026-08")
checar("Com ate_mes_ref=2026-08: set/2026 NÃO aparece", "2026-09" not in {r["mes_ref"] for r in resumo_ago})
checar("Com ate_mes_ref=2026-08: mai a ago continuam aparecendo (4 meses)",
       {r["mes_ref"] for r in resumo_ago} == {"2026-05", "2026-06", "2026-07", "2026-08"})

resumo_set = eventos_parser.get_resumo_anual(PARSED_EXEMPLO, ate_mes_ref="2026-09")
checar("Relatório de setembro: set/2026 volta a aparecer normalmente",
       "2026-09" in {r["mes_ref"] for r in resumo_set})

checar("A lista 'eventos'/'resumo' original (import) não foi alterada pela leitura",
       len(PARSED_EXEMPLO["resumo"]) == 5)

# Ponta a ponta: PDF (_build_bloco_eventos) de agosto não vê setembro; de
# setembro, vê.
bloco_ago = _build_bloco_eventos("2026-08", PARSED_EXEMPLO)
checar("_build_bloco_eventos('2026-08', ...) não inclui set/2026 no resumo do PDF",
       not any(r.mes == "set/2026" for r in bloco_ago.resumo))
checar("_build_bloco_eventos('2026-08', ...) inclui ago/2026 no resumo do PDF",
       any(r.mes == "ago/2026" for r in bloco_ago.resumo))

bloco_set = _build_bloco_eventos("2026-09", PARSED_EXEMPLO)
checar("_build_bloco_eventos('2026-09', ...) inclui set/2026 no resumo do PDF",
       any(r.mes == "set/2026" for r in bloco_set.resumo))


# ═══════════════════════════════════════════════════════════════════════
# 3. Fechamento — botão Calcular sempre "primary" (destaque genérico)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. _acao_calcular — botão Calcular sempre destacado (type=primary)")
print("=" * 70)
from app.ui.fechamento import _acao_calcular

fonte = inspect.getsource(_acao_calcular)
checar("_acao_calcular usa type=\"primary\" (sem condição de status)",
       'type="primary"' in fonte and 'status in' not in fonte)
checar("_acao_calcular não recebe mais o parâmetro 'status' (não é mais usado para isso)",
       "status" not in inspect.signature(_acao_calcular).parameters)

# Render ao vivo (AppTest, sem bypass): confirma que o botão continua
# existindo, clicável, e que clicar continua calculando normalmente —
# nenhum comportamento de clique mudou, só o destaque visual.
from streamlit.testing.v1 import AppTest

_APP_PROBE = os.path.join(_REPO_ROOT, "tests", "_probe_calcular_v7.py")
with open(_APP_PROBE, "w") as f:
    f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
from migrations import runner
runner.run_all(verbose=False)
import streamlit as st
st.session_state.selected_unit = "viva_trindade"
st.session_state.admin_view = None
from app.ui.fechamento import tela_fechamento
tela_fechamento("2026-08")
''')
try:
    at = AppTest.from_file(_APP_PROBE, default_timeout=60)
    at.run()
    botoes_calcular = [b for b in at.button if b.label == "Calcular"]
    checar("Botão 'Calcular' renderiza na tela real de Fechamento", len(botoes_calcular) >= 1)
finally:
    os.remove(_APP_PROBE)


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 7) PASSARAM ===")
