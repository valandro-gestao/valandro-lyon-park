"""
Cobertura permanente da rodada de refinamentos pós-homologação Aucon:
Nilo Square (terminologia, faixas de repasse, PDF auxiliar de Direito de
Uso, referências visuais [A]/[B]/[C]) e interface geral do Fechamento
(remoção da UI global de Planilha de Faturamentos, eventos movidos para
dentro de FIERGS/ILP, botão "Buscar no Aucon", indicadores clicáveis).

Restrições explicitamente respeitadas e cobertas aqui:
  - regra de cálculo homologada do Nilo intocada (repasse idêntico antes/
    depois do detalhamento por faixa);
  - integração Aucon não tocada (nenhum teste deste arquivo mexe em
    app/integrations/ nem em _importar_faturamento_aucon);
  - cálculos FIERGS/ILP não tocados (COM_FAIXAS/_aplicar_faixas,
    _prestacao_faixas continuam exatamente como estavam);
  - parsers legados preservados (fat_parser/eventos_parser, só a UI de
    upload global mudou de lugar/sumiu).

Execução: python3 tests/testes_homologacao_nilo_refinamento_v1.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_nilo_refinamento_v1_")
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


import json
import streamlit as st
from app.models import criar_unidade, salvar_parametros, salvar_lancamento, get_db
from app.engine import load_units, get_unit, get_unit_com_params, calcular
from app.calculators.cumul_du import calcular_com_aliquota_cumul_du
from app.calculators.cumulativo import _aplicar_faixas, _detalhar_faixas
from app.calculators.faixas import calcular_com_faixas
from app.reporter import (
    _prestacao_cumul_du, _blocos_cumul_du, build_report_data, build_report_data_du,
)
from app.report_data import (
    ReportData, UnidadeInfo, Cards, Prestacao, Historico, BlocoReceita, LinhaPrestacao,
)
from app.renderer import render_html
from app.parsers import eventos as eventos_parser


# ═══════════════════════════════════════════════════════════════════════
# 1. Faixas de repasse do Nilo — total idêntico antes/depois; soma das
#    faixas = repasse; COM_ALIQUOTA_CUMUL/FIERGS não tocados
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1 — Faixas de repasse: totais idênticos, soma das faixas = repasse")
print("=" * 70)

FAIXAS_TESTE = [
    {"percentual": 0.5, "ate": 100000.0},
    {"percentual": 0.7},  # sem "ate" = excedente
]

UID_FAIXAS = "nilo_refin_v1_faixas"
criar_unidade(UID_FAIXAS, "Nilo Refin V1 Faixas", "Nilo Square", "2020-01-01",
              "COM_ALIQUOTA_CUMUL_DU")
salvar_parametros(UID_FAIXAS, "2026-08", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
    "faixas_aluguel": FAIXAS_TESTE,
}, alterado_por="teste_nilo_refin_v1")
load_units(force=True)
CFG_FAIXAS = get_unit_com_params(UID_FAIXAS, "2026-08")

# 1a-1c: resultado_disponivel atravessa as duas faixas (250.000)
total_esperado_1 = _aplicar_faixas(250000.0, FAIXAS_TESTE)
checar("1a. _aplicar_faixas (função antiga, intocada) = R$ 155.000,00 (golden manual: "
       "100.000*0,5 + 150.000*0,7)", total_esperado_1 == 155000.0)

r1 = calcular_com_aliquota_cumul_du(
    CFG_FAIXAS, "2026-08", faturamento=250000.0, saldo_override=0.0, custos_extras={},
)
checar("1b. Repasse calculado (aluguel_calculado) é EXATAMENTE igual ao valor que "
       "_aplicar_faixas (antiga, sem detalhamento) já produzia — total nunca muda",
       r1.aluguel_calculado == total_esperado_1)

soma_faixas_1 = round(sum(f["aluguel"] for f in r1.extras["faixas_detalhe"]), 2)
checar("1c. Soma das faixas do detalhamento == repasse total (garantia por construção, "
       "última faixa não-zero absorve o resíduo de arredondamento)",
       soma_faixas_1 == r1.aluguel_calculado)
checar("1d. Detalhamento tem uma entrada por faixa configurada (2)",
       len(r1.extras["faixas_detalhe"]) == 2)
checar("1e. Primeira faixa: percentual=0.5, base=100.000,00 (limite atingido)",
       r1.extras["faixas_detalhe"][0]["percentual"] == 0.5
       and r1.extras["faixas_detalhe"][0]["base"] == 100000.0)
checar("1f. Segunda faixa (excedente): percentual=0.7, base=150.000,00",
       r1.extras["faixas_detalhe"][1]["percentual"] == 0.7
       and r1.extras["faixas_detalhe"][1]["base"] == 150000.0)

# 1g-1i: saldo se esgota ANTES da última faixa — entrada zero, mas soma
# continua batendo (prova de que o "continue" preserva o tamanho da lista
# e o resíduo é absorvido corretamente mesmo com faixas zeradas no fim).
total_esperado_2 = _aplicar_faixas(50000.0, FAIXAS_TESTE)
r2 = calcular_com_aliquota_cumul_du(
    CFG_FAIXAS, "2026-08", faturamento=50000.0, saldo_override=0.0, custos_extras={},
)
checar("1g. Resultado disponível menor que a primeira faixa: repasse ainda bate com "
       "_aplicar_faixas (R$ 25.000,00)", r2.aluguel_calculado == total_esperado_2 == 25000.0)
checar("1h. Segunda faixa (saldo já esgotado) aparece com base=0.0, aluguel=0.0 — "
       "não é omitida da lista", r2.extras["faixas_detalhe"][1] == {
           "percentual": 0.7, "base": 0.0, "aluguel": 0.0})
soma_faixas_2 = round(sum(f["aluguel"] for f in r2.extras["faixas_detalhe"]), 2)
checar("1i. Soma das faixas == repasse total também neste caso", soma_faixas_2 == r2.aluguel_calculado)

# 1j: unidade SEM faixas_aluguel (só percentual_aluguel) — faixas_detalhe
# vazio, nenhuma linha de faixa é inserida no relatório (regressão do
# comportamento já homologado do Nilo).
UID_PCT = "nilo_refin_v1_percentual"
criar_unidade(UID_PCT, "Nilo Refin V1 Percentual", "Nilo Square", "2020-01-01",
              "COM_ALIQUOTA_CUMUL_DU")
salvar_parametros(UID_PCT, "2026-08", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
    "percentual_aluguel": 0.85,
}, alterado_por="teste_nilo_refin_v1")
load_units(force=True)
CFG_PCT = get_unit_com_params(UID_PCT, "2026-08")
r_pct = calcular_com_aliquota_cumul_du(CFG_PCT, "2026-08", faturamento=100000.0,
                                        saldo_override=0.0, custos_extras={})
checar("1j. Unidade sem faixas_aluguel: faixas_detalhe vazio (regra homologada intacta)",
       r_pct.extras["faixas_detalhe"] == [])
checar("1k. Repasse via percentual continua sendo faturamento*percentual (85.000,00)",
       r_pct.aluguel_calculado == 85000.0)

# 1l-1m: COM_ALIQUOTA_CUMUL (Dom Pedro/Axis/etc.) e COM_FAIXAS (FIERGS) —
# calculadoras NÃO tocadas por este refinamento.
from app.calculators.cumulativo import calcular_com_aliquota_cumul
CFG_CUMUL_REGRESSAO = {"id": "regressao_cumul", "aliquota_imposto": 0.0,
                       "percentual_aluguel": 0.85, "ponto_equilibrio": 0.0}
r_cumul = calcular_com_aliquota_cumul(CFG_CUMUL_REGRESSAO, "2026-08", faturamento=50000.0)
checar("1l. Regressão COM_ALIQUOTA_CUMUL: extras não ganhou faixas_detalhe "
       "(calculadora não tocada)", "faixas_detalhe" not in (r_cumul.extras or {}))

CFG_FIERGS_REGRESSAO = {
    "id": "regressao_fiergs", "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0,
    "faixas": [{"percentual": 0.5, "ate": 50000.0}, {"percentual": 0.7}],
}
r_fiergs = calcular_com_faixas(CFG_FIERGS_REGRESSAO, "2026-08", faturamento=100000.0)
checar("1m. Regressão COM_FAIXAS/FIERGS: golden continua 60.000,00 (50.000*0,5 + 50.000*0,7)",
       r_fiergs.aluguel_calculado == 60000.0)
checar("1n. Regressão COM_FAIXAS/FIERGS: extras['faixas_detalhe'] próprio continua existindo "
       "(mecanismo original, não duplicado)", "faixas_detalhe" in (r_fiergs.extras or {}))


# ═══════════════════════════════════════════════════════════════════════
# 2. _prestacao_cumul_du: linhas de faixa só aparecem quando configuradas;
#    refs [A]/[B]/[C] presentes e pareados entre resumo e detalhamento
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2 — Linhas de faixa no relatório principal; referências [A]/[B]/[C]")
print("=" * 70)

prest_faixas = _prestacao_cumul_du(r1, CFG_FAIXAS)
labels_faixas = [l.descricao for l in prest_faixas.linhas]
checar("2a. Linha 'Repasse 50% (até R$ 100,000)' presente — mesmo formato de "
       "milhar (vírgula) já usado literalmente por _prestacao_faixas/FIERGS, "
       "reaproveitado sem alteração",
       any("Repasse 50%" in l and "100,000" in l for l in labels_faixas))
checar("2b. Linha 'Repasse 70% (excedente)' presente",
       any("Repasse 70%" in l and "excedente" in l for l in labels_faixas))
checar("2c. Linha final 'Repasse' com o valor total (R$ 155.000,00) continua a última linha",
       prest_faixas.linhas[-1].descricao == "Repasse" and prest_faixas.linhas[-1].valor == 155000.0)

prest_pct = _prestacao_cumul_du(r_pct, CFG_PCT)
labels_pct = [l.descricao for l in prest_pct.linhas]
checar("2d. Sem faixas_aluguel: nenhuma linha 'Repasse N%' aparece (só percentual, "
       "como já era)", not any(l.startswith("Repasse ") and "%" in l for l in labels_pct))

# Referências visuais — usando o golden já conhecido (receita/despesas DU +
# rateio + despesas de operação configurados).
UID_REFS = "nilo_refin_v1_refs"
criar_unidade(UID_REFS, "Nilo Refin V1 Refs", "Nilo Square", "2020-01-01",
              "COM_ALIQUOTA_CUMUL_DU")
salvar_parametros(UID_REFS, "2026-08", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 1129,
    "percentual_aluguel": 0.85,
    "despesas_ressarcimento_du": [{"id": "proprietarios", "nome": "Proprietários"}],
    "despesas_rateio_du": [{"id": "agua", "nome": "Água"}],
    "despesas_operacao": [{"id": "folha", "nome": "Folha"}],
}, alterado_por="teste_nilo_refin_v1")
load_units(force=True)
CFG_REFS = get_unit_com_params(UID_REFS, "2026-08")
r_refs = calcular_com_aliquota_cumul_du(
    CFG_REFS, "2026-08", faturamento=300000.0, saldo_override=0.0,
    custos_extras={
        "receita_ressarcimento_du": 234896.54,
        "despesas_ressarcimento_du": {"proprietarios": 82882.08},
        "despesas_rateio_du": {"agua": 100000.0},
        "despesas_operacao": {"folha": 5000.0},
    },
)
prest_refs = _prestacao_cumul_du(r_refs, CFG_REFS)
blocos_refs = _blocos_cumul_du(r_refs)

linha_resumo_a = next(l for l in prest_refs.linhas if "Recebimento Líquido DU" in l.descricao)
checar("2e. Linha-resumo (branca) do Recebimento Líquido DU tem ref='A'", linha_resumo_a.ref == "A")
bloco_recebimento = next(b for b in blocos_refs if b.titulo == "Recebimento de Direitos de Uso")
linha_total_a = next(l for l in bloco_recebimento.linhas if l.descricao == "Recebimento Líquido DU")
checar("2f. Total detalhado do Bloco 2 (linha verde) NÃO tem mais ref próprio "
       "— proposta visual aprovada removeu a referência repetida da linha "
       "de total, deixando-a limpa", linha_total_a.ref is None)
checar("2f2. Bloco 2 (título/cabeçalho) tem ref='A' — a contraparte da "
       "referência da linha-resumo branca foi para o título do bloco "
       "detalhado, não mais para a linha verde de total",
       bloco_recebimento.ref == "A")

linha_resumo_b = next(l for l in prest_refs.linhas if "Total Despesas Rateio DU" in l.descricao)
checar("2g. Linha-resumo (branca) de Despesas Rateio DU tem ref='B'", linha_resumo_b.ref == "B")
bloco_rateio_refs = next(b for b in blocos_refs if b.titulo == "Rateio de Direito de Uso")
linha_total_b = next(l for l in bloco_rateio_refs.linhas if l.descricao == "Total Despesas Rateio DU")
checar("2h. Total detalhado do Bloco 3 (linha verde) NÃO tem mais ref próprio",
       linha_total_b.ref is None)
checar("2h2. Bloco 3 (título/cabeçalho) tem ref='B'", bloco_rateio_refs.ref == "B")

linha_resumo_c = next(l for l in prest_refs.linhas if "Total Despesas da Operação" in l.descricao)
checar("2i. Linha-resumo (branca) de Despesas da Operação tem ref='C'", linha_resumo_c.ref == "C")
bloco_operacao_refs = next(b for b in blocos_refs if b.titulo == "Despesas da Operação")
linha_total_c = next(l for l in bloco_operacao_refs.linhas if l.descricao == "Total Despesas da Operação")
checar("2j. Total detalhado do Bloco 4 (linha verde) NÃO tem mais ref próprio",
       linha_total_c.ref is None)
checar("2j2. Bloco 4 (título/cabeçalho) tem ref='C'", bloco_operacao_refs.ref == "C")

checar("2k. Linhas sem ref explícito (ex. 'Faturamento') continuam com ref=None — "
       "campo inerte para o resto do relatório",
       next(l for l in prest_refs.linhas if l.descricao == "Faturamento").ref is None)


# ═══════════════════════════════════════════════════════════════════════
# 3. PDF principal continua completo; PDF DU só tem Rateio DU
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3 — PDF principal completo; PDF DU restrito ao Rateio de Direito de Uso")
print("=" * 70)

report_principal = build_report_data(r_refs, "2026-08")
checar("3a. PDF principal: cards preenchidos (Faturamento/Resultado/Repasse)",
       report_principal.cards is not None and report_principal.cards.faturamento == 300000.0)
checar("3b. PDF principal: prestação de contas principal presente (linhas não vazias)",
       len(report_principal.prestacao.linhas) > 0)
checar("3c. PDF principal: blocos_receitas contém os 3 blocos de Direito de Uso",
       len(report_principal.blocos_receitas) == 3)

html_principal = render_html(report_principal)
checar("3d. HTML do PDF principal contém a seção 'Prestação de Contas'",
       "Prestação de Contas" in html_principal)
checar("3e. HTML do PDF principal contém os cards (Valor do Repasse)",
       "Valor do Repasse" in html_principal)
checar("3f. HTML do PDF principal contém o bloco Rateio de Direito de Uso",
       "Rateio de Direito de Uso" in html_principal)

report_du = build_report_data_du(r_refs, "2026-08")
checar("3g. PDF DU: cards=None (nenhum card de faturamento/resultado/repasse)",
       report_du.cards is None)
checar("3h. PDF DU: prestação de contas principal VAZIA (nenhuma linha)",
       report_du.prestacao.linhas == [])
checar("3i. PDF DU: blocos_receitas contém SÓ o bloco Rateio de Direito de Uso",
       len(report_du.blocos_receitas) == 1
       and report_du.blocos_receitas[0].titulo == "Rateio de Direito de Uso")
checar("3j. PDF DU: NÃO contém o bloco Recebimento de Direitos de Uso "
       "(só Rateio, como pedido)",
       not any(b.titulo == "Recebimento de Direitos de Uso" for b in report_du.blocos_receitas))
checar("3k. PDF DU: mesma unidade/competência do relatório principal",
       report_du.unidade.nome == report_principal.unidade.nome
       and report_du.unidade.competencia == "2026-08")

html_du = render_html(report_du)
checar("3l. HTML do PDF DU NÃO contém a seção 'Prestação de Contas'",
       "Prestação de Contas" not in html_du)
checar("3m. HTML do PDF DU NÃO contém os cards principais ('Valor do Repasse')",
       "Valor do Repasse" not in html_du)
checar("3n. HTML do PDF DU NÃO contém 'Faturamento' nem 'Resultado da Operação' "
       "(cards)", "Faturamento</div>" not in html_du and "Resultado da Operação" not in html_du)
checar("3o. HTML do PDF DU CONTÉM a seção Rateio de Direito de Uso",
       "Rateio de Direito de Uso" in html_du)
checar("3p. HTML do PDF DU contém cabeçalho (nome da unidade) e competência",
       report_du.unidade.nome in html_du and report_du.unidade.competencia_label in html_du)
checar("3q. HTML do PDF DU contém data de emissão",
       "Emitido em" in html_du)


# ═══════════════════════════════════════════════════════════════════════
# 4. Relatórios não-DU permanecem visual/estruturalmente inalterados
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4 — Regressão: relatórios não-DU (ex. PERCENTUAL_SIMPLES) inalterados")
print("=" * 70)
UID_NAO_DU = "nilo_refin_v1_nao_du"
criar_unidade(UID_NAO_DU, "Nao DU Regressao", "Contratante Teste", "2020-01-01",
              "PERCENTUAL_SIMPLES")
salvar_parametros(UID_NAO_DU, "2026-08", {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                  alterado_por="teste_nilo_refin_v1")
load_units(force=True)
r_nao_du = calcular(UID_NAO_DU, "2026-08", 50000.0)
report_nao_du = build_report_data(r_nao_du, "2026-08")
checar("4a. Unidade não-DU: cards continuam preenchidos normalmente",
       report_nao_du.cards is not None)
checar("4b. Unidade não-DU: prestação de contas continua com linhas (não é vazia)",
       len(report_nao_du.prestacao.linhas) > 0)
checar("4c. Unidade não-DU: blocos_receitas continua vazio (nunca teve blocos DU)",
       report_nao_du.blocos_receitas == [])
html_nao_du = render_html(report_nao_du)
checar("4d. HTML de unidade não-DU contém 'Prestação de Contas' normalmente",
       "Prestação de Contas" in html_nao_du)
checar("4e. HTML de unidade não-DU contém os cards normalmente",
       "Valor do Repasse" in html_nao_du)
checar("4f. Nenhuma linha da prestação de unidade não-DU tem ref preenchido "
       "(campo novo, inerte para quem não é Nilo)",
       all(l.ref is None for l in report_nao_du.prestacao.linhas))


# ═══════════════════════════════════════════════════════════════════════
# 5-7. Interface geral: upload de eventos na nova posição (FIERGS/ILP);
#      UI global de Planilha de Faturamentos removida mas parser
#      preservado; indicadores pendentes/andamento/aprovadas clicáveis
# ═══════════════════════════════════════════════════════════════════════
from streamlit.testing.v1 import AppTest
from app.models import salvar_lancamento, ResultadoUnidade, atualizar_unidade

_PROBE_PATHS: list[str] = []
atexit.register(lambda: [os.remove(p) for p in _PROBE_PATHS if os.path.exists(p)])
_PROBE_COUNTER = [0]


def _escrever_probe_unidade(uid: str, mes_ref: str) -> str:
    _PROBE_COUNTER[0] += 1
    path = os.path.join(_REPO_ROOT, "tests", f"_probe_nilo_refin_{_PROBE_COUNTER[0]}.py")
    with open(path, "w") as f:
        f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
import streamlit as st
st.session_state.selected_unit = {uid!r}
from app.ui.fechamento import tela_fechamento
tela_fechamento({mes_ref!r})
''')
    _PROBE_PATHS.append(path)
    return path


def _escrever_probe_lista(mes_ref: str) -> str:
    _PROBE_COUNTER[0] += 1
    path = os.path.join(_REPO_ROOT, "tests", f"_probe_nilo_refin_{_PROBE_COUNTER[0]}.py")
    with open(path, "w") as f:
        f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
import streamlit as st
st.session_state.selected_unit = None
from app.ui.fechamento import tela_fechamento
tela_fechamento({mes_ref!r})
''')
    _PROBE_PATHS.append(path)
    return path


def _abrir_unidade(uid: str, mes_ref: str) -> AppTest:
    at = AppTest.from_file(_escrever_probe_unidade(uid, mes_ref), default_timeout=60)
    at.run()
    return at


def _abrir_lista(mes_ref: str) -> AppTest:
    at = AppTest.from_file(_escrever_probe_lista(mes_ref), default_timeout=60)
    at.run()
    return at


print("=" * 70)
print("5 — Upload de Eventos funciona na nova posição (dentro de FIERGS/ILP)")
print("=" * 70)
MES5 = "2026-08"
UID_EVENTOS = "nilo_refin_v1_fiergs_like"
criar_unidade(UID_EVENTOS, "Fiergs-like Refin V1", "Contratante Teste", "2020-01-01",
              "COM_FAIXAS", tipo_relatorio="com_eventos")
salvar_parametros(UID_EVENTOS, MES5, {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0,
    "faixas": [{"percentual": 0.5, "ate": 50000.0}, {"percentual": 0.7}],
}, alterado_por="teste_nilo_refin_v1")
load_units(force=True)

at5a = _abrir_unidade(UID_EVENTOS, MES5)
checar("5a. Sem eventos ainda: 'Eventos: Não carregados' aparece na unidade",
       any("Não carregados" in str(m.value) for m in at5a.metric))
checar("5b. Expander 'Planilha de Eventos' está presente dentro da PRÓPRIA unidade",
       any("Planilha de Eventos" in (e.label or "") for e in at5a.expander))

parsed_eventos = {
    "eventos": [{"data": "01/08/26", "evento": "Show", "horario": "20h",
                 "qtd_extras": 10, "valor_unitario": 150.0, "valor_total": 1500.0,
                 "mes_ref": MES5}],
    "resumo": [{"mes_label": "ago/2026", "mes_ref": MES5, "qtd_extras": 10, "valor_total": 1500.0}],
}
eventos_parser.salvar_uid(MES5, UID_EVENTOS, parsed_eventos)

at5b = _abrir_unidade(UID_EVENTOS, MES5)
# len(ev_mes) conta REGISTROS de evento (1, neste teste), não qtd_extras
# (10, um campo dentro do único evento) — mesma composição de sempre
# (f"{_fmt(total)} · {len(ev_mes)} eventos"), só relocada.
checar("5c. Depois de salvar eventos (mesmo mecanismo de sempre, "
       "eventos_parser.salvar_uid intocado): evidência mostra 'R$ 1.500,00 · 1 eventos'",
       any("1.500,00" in str(m.value) and "1 eventos" in str(m.value) for m in at5b.metric))
checar("5d. Expander de eventos agora mostra 'Substituir' (dado já carregado)",
       any(b.label == f"Substituir" for b in at5b.button
           if b.key == f"btn_sub_ev_{UID_EVENTOS}"))
checar("5e. Nenhuma exceção ao abrir a unidade com eventos na nova posição",
       len(at5b.exception) == 0)

at5_lista = _abrir_lista(MES5)
texto_lista5 = "\n".join(str(md.value) for md in at5_lista.markdown)
checar("5f. Tela geral (lista) NÃO mostra mais 'Planilhas de Eventos' — "
       "upload ficou só dentro da unidade", "Planilhas de Eventos" not in texto_lista5)


print("=" * 70)
print("6 — UI global de Planilha de Faturamentos removida; parser/legado preservado")
print("=" * 70)
at6_lista = _abrir_lista(MES5)
texto_lista6 = "\n".join(str(md.value) for md in at6_lista.markdown)
checar("6a. Tela geral NÃO contém mais o card 'Planilha de Faturamentos'",
       "Planilha de Faturamentos" not in texto_lista6)
checar("6b. Botão 'Buscar no Aucon' com o rótulo encurtado (não 'Buscar "
       "faturamentos no Aucon')",
       not any("Buscar faturamentos no Aucon" == (b.label or "") for b in at6_lista.button))

# Suporte legado: uma planilha já importada ANTES desta rodada continua
# alimentando uid_map/fat_importado normalmente — só a UI de upload sumiu,
# não o parser nem o efeito de uma importação já existente.
from app.parsers import faturamento as fat_parser
UID_LEGADO = "nilo_refin_v1_legado_planilha"
criar_unidade(UID_LEGADO, "Legado Planilha Refin V1", "Contratante Teste", "2020-01-01",
              "PERCENTUAL_SIMPLES")
salvar_parametros(UID_LEGADO, MES5, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                  alterado_por="teste_nilo_refin_v1")
load_units(force=True)
fat_parser.salvar(MES5, {
    "uid_map": {UID_LEGADO: 12345.67}, "nao_mapeados": [], "sem_fat": [],
    "col_nome": "Nome", "col_fat": "Valor", "raw_rows": [], "sheet": "Sheet1",
})
at6_unidade = _abrir_unidade(UID_LEGADO, MES5)
checar("6c. Unidade sem Aucon continua recebendo o valor de uma planilha já "
       "importada (fat_importado, suporte legado preservado) como evidência",
       any("12.345,67" in str(m.value) for m in at6_unidade.metric))
checar("6d. fat_parser.load continua funcionando (função de suporte legado "
       "nunca apagada)", fat_parser.load(MES5) is not None)


print("=" * 70)
print("7 — Indicadores Pendentes/Em andamento/Aprovadas são clicáveis")
print("=" * 70)
MES7 = "2026-08"
UID_P = "nilo_refin_v1_pend"
UID_A = "nilo_refin_v1_aprov"
for uid_x, nome_x in [(UID_P, "Pendente Refin V1"), (UID_A, "Aprovada Refin V1")]:
    criar_unidade(uid_x, nome_x, "Contratante Teste", "2020-01-01", "PERCENTUAL_SIMPLES")
    salvar_parametros(uid_x, MES7, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                      alterado_por="teste_nilo_refin_v1")
    # get_unidades_ativas exige ativo=1 — criar_unidade sempre nasce ativo=0
    # (proteção contra uso operacional sem parâmetros válidos); aqui é só
    # para a unidade aparecer na lista geral, mesmo padrão de outras
    # rodadas deste projeto.
    atualizar_unidade(uid_x, ativo=True)
load_units(force=True)
r_aprovado = calcular(UID_A, MES7, 10000.0)
r_aprovado.status = "aprovado"
r_aprovado.mes_referencia = MES7
salvar_lancamento(r_aprovado)
# A agrupação da lista (_lista_unidades_agrupada) lê o status do
# run_manager (status.json), não de lancamentos.status diretamente — este
# teste só precisa simular uma unidade já aprovada para exercitar o clique
# no indicador, não o workflow de aprovação em si (gerar -> revisar ->
# aprovar); por isso escreve o status diretamente via _update_unit, sem
# passar pela máquina de estados completa.
from app import run_manager as rm
rm._update_unit(MES7, UID_A, status="aprovado")

at7 = _abrir_lista(MES7)
checar("7a. Sem clique ainda: expander 'Pendentes' aberto por padrão (comportamento "
       "de sempre, preservado)",
       next(e for e in at7.expander if "Pendentes" in (e.label or "")).proto.expanded)

btn_aprovadas = next(b for b in at7.button if "aprovadas" in (b.label or ""))
btn_aprovadas.click()
at7.run()
checar("7b. Depois de clicar em 'N aprovadas': expander 'Aprovadas' está aberto",
       next(e for e in at7.expander if e.label.startswith("Aprovadas")).proto.expanded)
checar("7c. Depois de clicar em 'N aprovadas': expander 'Pendentes' NÃO está mais "
       "aberto (só o grupo clicado abre)",
       not next(e for e in at7.expander if e.label.startswith("Pendentes")).proto.expanded)
checar("7d. session_state guarda o foco selecionado ('aprovado')",
       at7.session_state["_resumo_foco"] == "aprovado")
checar("7e. Nenhuma exceção ao clicar no indicador", len(at7.exception) == 0)


# ═══════════════════════════════════════════════════════════════════════
# 8. Unidades ordenadas alfabeticamente (amigável, case-insensitive, sem
#    acento) dentro de cada grupo — Pendentes/Em andamento/Aprovadas
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("8 — Ordenação alfabética das unidades dentro de cada grupo")
print("=" * 70)
MES8 = MES7  # mesma competência já usada na seção 7 — reaproveita a tela

# Nomes criados fora de ordem de propósito, em cada grupo — inclui acento
# e caractere não-alfabético (".") para provar a ordenação "amigável".
NOMES_PENDENTE = ["Zebra Pendente", "Ávila Pendente", "Axis Pendente"]
NOMES_ANDAMENTO = ["Dom Pedro Andamento", "A. Schneider Andamento", "Anitta Mall Andamento"]
NOMES_APROVADO = ["W Tower Aprovada", "Água Aprovada", "Bônus Aprovada"]

for i, nome in enumerate(NOMES_PENDENTE):
    uid = f"nilo_refin_v1_ord_pend_{i}"
    criar_unidade(uid, nome, "Contratante Teste", "2020-01-01", "PERCENTUAL_SIMPLES")
    salvar_parametros(uid, MES8, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                      alterado_por="teste_nilo_refin_v1")
    atualizar_unidade(uid, ativo=True)
    # status "pendente" é o default — nenhuma escrita em run_manager necessária.

for i, nome in enumerate(NOMES_ANDAMENTO):
    uid = f"nilo_refin_v1_ord_and_{i}"
    criar_unidade(uid, nome, "Contratante Teste", "2020-01-01", "PERCENTUAL_SIMPLES")
    salvar_parametros(uid, MES8, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                      alterado_por="teste_nilo_refin_v1")
    atualizar_unidade(uid, ativo=True)
    rm._update_unit(MES8, uid, status="gerado")

for i, nome in enumerate(NOMES_APROVADO):
    uid = f"nilo_refin_v1_ord_apr_{i}"
    criar_unidade(uid, nome, "Contratante Teste", "2020-01-01", "PERCENTUAL_SIMPLES")
    salvar_parametros(uid, MES8, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                      alterado_por="teste_nilo_refin_v1")
    atualizar_unidade(uid, ativo=True)
    rm._update_unit(MES8, uid, status="aprovado")

load_units(force=True)
at8 = _abrir_lista(MES8)

# _linha_unidade renderiza o nome via row[0].write(f"**{u['nome']}**") —
# reconstrói a ordem em que os nomes aparecem no documento, filtrando só
# os markdowns que batem com "**<nome>**" de cada conjunto conhecido.
todos_markdowns_em_ordem = [str(md.value) for md in at8.markdown]


def _ordem_renderizada(nomes: list[str]) -> list[str]:
    alvo = {f"**{n}**" for n in nomes}
    return [n for md in todos_markdowns_em_ordem for n in nomes if f"**{n}**" == md]


ordem_pend = _ordem_renderizada(NOMES_PENDENTE)
esperado_pend = ["Ávila Pendente", "Axis Pendente", "Zebra Pendente"]
checar(f"8a. Pendentes em ordem alfabética amigável: {esperado_pend}",
       ordem_pend == esperado_pend)

ordem_and = _ordem_renderizada(NOMES_ANDAMENTO)
esperado_and = ["A. Schneider Andamento", "Anitta Mall Andamento", "Dom Pedro Andamento"]
checar(f"8b. Em andamento em ordem alfabética amigável: {esperado_and}",
       ordem_and == esperado_and)

ordem_apr = _ordem_renderizada(NOMES_APROVADO)
esperado_apr = ["Água Aprovada", "Bônus Aprovada", "W Tower Aprovada"]
checar(f"8c. Aprovadas em ordem alfabética amigável: {esperado_apr}",
       ordem_apr == esperado_apr)

checar("8d. Nenhuma exceção ao renderizar a lista com as unidades novas",
       len(at8.exception) == 0)

# Confirma que a ordenação NÃO mudou quem entra em cada grupo (só a ordem
# dentro dele) — cada nome aparece só uma vez no total, no grupo certo.
checar("8e. Cada unidade de teste aparece exatamente uma vez na tela "
       "(ordenação não duplicou nem moveu unidade de grupo)",
       all(todos_markdowns_em_ordem.count(f"**{n}**") == 1
           for n in NOMES_PENDENTE + NOMES_ANDAMENTO + NOMES_APROVADO))


# ═══════════════════════════════════════════════════════════════════════
# 9. Bug real de produção (Nilo Square, Out/2026): get_unit() puro não
#    enxerga faixas_aluguel (só existe em parametros_vigentes, unidade
#    100% Admin, sem bloco em data/units.yaml) — o reporter usava get_unit
#    para montar o cfg, então o detalhamento por faixa nunca aparecia no
#    PDF, mesmo com o Repasse certo (calculado via get_unit_com_params em
#    app.engine.calcular). Teste passa OBRIGATORIAMENTE pelo caminho
#    público/real build_report_data — não chama _prestacao_cumul_du
#    diretamente — porque foi exatamente esse caminho que os testes da
#    rodada anterior não cobriram e que deixou o bug passar para produção.
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("9 — build_report_data (caminho real) resolve faixas_aluguel via "
      "get_unit_com_params — bug de produção do Nilo Square")
print("=" * 70)

UID_BUILD_FAIXAS = "nilo_refin_v1_build_faixas"
criar_unidade(UID_BUILD_FAIXAS, "Nilo Build Faixas", "Nilo Square", "2020-01-01",
              "COM_ALIQUOTA_CUMUL_DU")
salvar_parametros(UID_BUILD_FAIXAS, "2026-08", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
    "faixas_aluguel": FAIXAS_TESTE,
}, alterado_por="teste_nilo_refin_v1")
load_units(force=True)

# 9a: prova da causa raiz — get_unit() PURO (identidade, sem params) não
# tem faixas_aluguel para uma unidade só-Admin, ao contrário do FIERGS
# (cujo YAML já embute "faixas" — ver seção 1l-1n, calculadoras intocadas).
cfg_get_unit_puro = get_unit(UID_BUILD_FAIXAS)
checar("9a. get_unit() puro NÃO enxerga faixas_aluguel (causa raiz do bug: "
       "unidade só-Admin, sem bloco em data/units.yaml)",
       "faixas_aluguel" not in cfg_get_unit_puro)
cfg_get_unit_com_params = get_unit_com_params(UID_BUILD_FAIXAS, "2026-08")
checar("9a2. get_unit_com_params() já enxerga faixas_aluguel (mesma "
       "função que app.engine.calcular já usava — por isso o Repasse "
       "sempre saiu certo, só o detalhamento no PDF que faltava)",
       cfg_get_unit_com_params.get("faixas_aluguel") == FAIXAS_TESTE)

r_build_faixas = calcular(UID_BUILD_FAIXAS, "2026-08", 250000.0)
report_build_faixas = build_report_data(r_build_faixas, "2026-08")
labels_build = [l.descricao for l in report_build_faixas.prestacao.linhas]
checar("9b. build_report_data (caminho público real): linha 'Repasse 50% "
       "(até R$ 100,000)' aparece na Prestação de Contas",
       any("Repasse 50%" in l and "100,000" in l for l in labels_build))
checar("9c. build_report_data: linha 'Repasse 70% (excedente)' aparece",
       any("Repasse 70%" in l and "excedente" in l for l in labels_build))
checar("9d. build_report_data: Repasse total (linha final) continua batendo "
       "com o golden de _aplicar_faixas (R$ 155.000,00) — o detalhamento "
       "não altera o total, só deixa de estar escondido",
       report_build_faixas.prestacao.linhas[-1].descricao == "Repasse"
       and report_build_faixas.prestacao.linhas[-1].valor == 155000.0)
checar("9e. cards.repasse também bate com o total (155.000,00) — card e "
       "detalhamento sempre consistentes entre si",
       report_build_faixas.cards.repasse == 155000.0)

# 9f: build_report_data_du (PDF auxiliar de Direito de Uso) tem a mesma
# troca get_unit → get_unit_com_params — mesmo bug, mesma correção,
# caminho de código separado.
report_du_build_faixas = build_report_data_du(r_build_faixas, "2026-08")
checar("9f. build_report_data_du: unidade só-Admin resolve corretamente "
       "nome/contratante via get_unit_com_params (não quebrou)",
       report_du_build_faixas.unidade.nome == "Nilo Build Faixas")


# ═══════════════════════════════════════════════════════════════════════
# 10. Regressão do fix get_unit → get_unit_com_params no reporter para
#     unidades reais YAML-backed (Dom Pedro/COM_ALIQUOTA_CUMUL, FIERGS/
#     COM_FAIXAS) via build_report_data — a troca de fonte do cfg não pode
#     quebrar o caminho mais comum de produção. linhas_cfg
#     (cfg["relatorio"]["linhas"]) só existe em bloco YAML, nunca em
#     parametros_vigentes/Admin — maior risco de regressão desta troca.
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("10 — Regressão real (Dom Pedro/FIERGS): get_unit_com_params no "
      "reporter não quebra unidades YAML-backed")
print("=" * 70)

# bootstrap_unidades_se_vazia (disparado por migrations.runner.run_all no
# topo deste arquivo) semeia TODAS as unidades reais de data/units.yaml na
# base sandboxada deste teste (DATA_DIR=_SCRATCH) — dom_pedro/fiergs já
# existem aqui, com seus blocos YAML reais (relatorio.linhas, faixas etc.),
# sem tocar em data/seed.db.
load_units(force=True)
MES10 = "2026-08"

r_dom_pedro = calcular("dom_pedro", MES10, 200000.0)
report_dom_pedro = build_report_data(r_dom_pedro, MES10)
labels_dp = [l.descricao for l in report_dom_pedro.prestacao.linhas]
checar("10a. Dom Pedro (COM_ALIQUOTA_CUMUL, relatorio.linhas do YAML real "
       "['faturamento','aliquota','subtotal','pe','resultado','prejuizo',"
       "'aluguel']): PDF continua com 'Receita Bruta' (linhas_cfg "
       "'faturamento' resolvido igual a antes)", "Receita Bruta" in labels_dp)
checar("10b. Dom Pedro: 'Receita Líquida' presente (linhas_cfg 'aliquota')",
       "Receita Líquida" in labels_dp)
checar("10c. Dom Pedro: '(-) Ponto de Equilíbrio' presente (linhas_cfg "
       "'pe', unidade tem ponto_equilibrio=10.803,71 no YAML)",
       any("Ponto de Equilíbrio" in l for l in labels_dp))
checar("10d. Dom Pedro: 'Resultado' presente (linhas_cfg 'resultado')",
       "Resultado" in labels_dp)
checar("10e. Dom Pedro: linha final de repasse presente (fluxo padrão "
       "completo até o fim, cfg['relatorio']['linhas'] resolvido de "
       "get_unit_com_params exatamente como get_unit() já resolvia)",
       report_dom_pedro.prestacao.linhas[-1].descricao in
       ("Repasse", "Taxa de Administração (Resultado Negativo)", "Saldo a Pagar"))
checar("10f. Dom Pedro: prestação não ficou vazia por acidente",
       len(report_dom_pedro.prestacao.linhas) > 0)

r_fiergs = calcular("fiergs", MES10, 150000.0)
report_fiergs = build_report_data(r_fiergs, MES10)
labels_fiergs = [l.descricao for l in report_fiergs.prestacao.linhas]
checar("10g. FIERGS (COM_FAIXAS, 'faixas' do próprio bloco YAML): PDF "
       "continua com linha de faixa de Aluguel (get_unit_com_params "
       "resolve o bloco YAML puro tão bem quanto get_unit() já resolvia)",
       any(l.startswith("Aluguel ") for l in labels_fiergs))
checar("10h. FIERGS: 'Total Aluguel' (linha final) presente",
       report_fiergs.prestacao.linhas[-1].descricao == "Total Aluguel")
checar("10i. FIERGS: prestação não ficou vazia por acidente",
       len(report_fiergs.prestacao.linhas) > 0)


# ═══════════════════════════════════════════════════════════════════════
# 11. _com_mes_atual: a competência do PDF sempre reflete o resultado em
#     memória, mesmo quando já existe um lançamento APROVADO persistido
#     para a MESMA competência — bug real de homologação (Nilo Square,
#     Out/2026): comparativo mostrava valores antigos (Resultado
#     125.875,00 / Repasse 108.948,55) enquanto o corpo do PDF já mostrava
#     o cálculo novo (112.713,64 / 97.103,33). Cenário exato confirmado em
#     produção (consulta read-only): banco tem Out/26 aprovado com
#     resultado/repasse antigos; PDF gerado com NOVO ResultadoUnidade para
#     Out/26 (parâmetro mudou, "Gerar PDF" clicado antes de reaprovar).
#     `lancamentos` NUNCA é escrito por este caminho — só a composição em
#     memória do comparativo muda.
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("11 — _com_mes_atual: competência do PDF sempre reflete o resultado "
      "em memória, mesmo com lançamento aprovado antigo persistido")
print("=" * 70)

UID_COMP = "nilo_refin_v1_com_mes_atual"
criar_unidade(UID_COMP, "Comp Mes Atual Refin V1", "Contratante Teste", "2020-01-01",
              "PERCENTUAL_SIMPLES")
salvar_parametros(UID_COMP, "2026-09", {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                  alterado_por="teste_nilo_refin_v1")
load_units(force=True)

# Mês anterior (Set/26) — persistido, aprovado, nunca deve mudar.
r_set = calcular(UID_COMP, "2026-09", 100000.0)
r_set.status = "aprovado"
salvar_lancamento(r_set)

# Out/26 — persistido como aprovado com valores ANTIGOS (simula um
# fechamento já aprovado antes de um parâmetro mudar).
r_out_antigo = calcular(UID_COMP, "2026-10", 125875.00)
r_out_antigo.status = "aprovado"
salvar_lancamento(r_out_antigo)

with get_db() as _conn:
    _row_antes = _conn.execute(
        "SELECT resultado_json, status FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
        (UID_COMP, "2026-10"),
    ).fetchone()
checar("11a. Pré-condição: Out/26 já está persistido como 'aprovado' antes "
       "de gerar o novo PDF", _row_antes is not None and _row_antes["status"] == "aprovado")

# PDF gerado com um NOVO ResultadoUnidade para a MESMA competência
# (Out/26) — "Gerar PDF" nunca chama salvar_lancamento, então o banco
# continua com o registro antigo enquanto este resultado só existe em
# memória.
r_out_novo = calcular(UID_COMP, "2026-10", 90000.0)
report_comp = build_report_data(r_out_novo, "2026-10")

entradas_out26 = [m for m in report_comp.comparativo_12m if m.competencia == "2026-10"]
checar("11b. Comparativo contém Out/26 exatamente UMA vez (nunca duplicado "
       "entre o valor novo em memória e o antigo do banco)",
       len(entradas_out26) == 1)
checar("11c. Valores de Out/26 no comparativo são os do NOVO resultado em "
       "memória (faturamento=90.000,00), não os antigos persistidos "
       "(125.875,00)", entradas_out26[0].faturamento == r_out_novo.faturamento == 90000.0)
checar("11d. Valores de Out/26 no comparativo são os do NOVO resultado "
       "(resultado), não os antigos", entradas_out26[0].resultado == r_out_novo.resultado)
checar("11e. Repasse de Out/26 no comparativo é o do NOVO resultado "
       "(aluguel_calculado) — não o antigo, que é um valor diferente",
       entradas_out26[0].repasse == r_out_novo.aluguel_calculado
       and r_out_novo.aluguel_calculado != r_out_antigo.aluguel_calculado
       and entradas_out26[0].repasse != r_out_antigo.aluguel_calculado)

entradas_set26 = [m for m in report_comp.comparativo_12m if m.competencia == "2026-09"]
checar("11f. Mês anterior (Set/26) continua presente exatamente uma vez "
       "(a substituição só vale para mes_ref, nunca para outros meses)",
       len(entradas_set26) == 1)
checar("11g. Mês anterior (Set/26): valores são os persistidos "
       "(faturamento=100.000,00), intocados pela substituição de Out/26",
       entradas_set26[0].faturamento == r_set.faturamento == 100000.0)

# 11h-11i: confirma por leitura direta do banco que `lancamentos` NUNCA foi
# escrito por build_report_data/_com_mes_atual — Out/26 continua com o
# registro ANTIGO (aprovado, faturamento/resultado antigos).
with get_db() as _conn2:
    _row_depois = _conn2.execute(
        "SELECT faturamento, resultado_json, status FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
        (UID_COMP, "2026-10"),
    ).fetchone()
checar("11h. Depois de gerar o PDF: registro de Out/26 em `lancamentos` "
       "continua com o faturamento ANTIGO (125.875,00) — build_report_data "
       "nunca grava no banco", _row_depois["faturamento"] == 125875.00)
_resultado_persistido = json.loads(_row_depois["resultado_json"])
checar("11i. Registro de Out/26 em `lancamentos` continua com status "
       "'aprovado' e resultado antigo — nenhuma escrita/sobrescrita "
       "ocorreu por gerar o PDF", _row_depois["status"] == "aprovado"
       and _resultado_persistido["resultado"] == r_out_antigo.resultado)


# ═══════════════════════════════════════════════════════════════════════
# 12. Proposta visual A/B/C: BlocoReceita.ref é opcional (default None,
#     inerte para qualquer bloco que não o defina explicitamente); o
#     template só imprime "— Referência X" quando bloco.ref existe, nunca
#     "vaza" para um bloco vizinho sem ref.
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("12 — BlocoReceita.ref: opcional/default None; template isola cada "
      "bloco corretamente")
print("=" * 70)

checar("12a. BlocoReceita.ref tem default None (campo opcional, inerte "
       "para todo bloco que não o define — nenhum outro bloco/relatório "
       "muda por causa deste campo novo)",
       BlocoReceita(titulo="x", linhas=[]).ref is None)

_report_ref_html = ReportData(
    unidade=UnidadeInfo(nome="Teste Ref", contratante="Teste", competencia="2026-08",
                         competencia_label="Agosto / 2026", data_emissao="01/08/2026",
                         tipo_relatorio="padrao"),
    cards=Cards(faturamento=1000.0, resultado=500.0, repasse=100.0),
    comparativo_12m=[],
    prestacao=Prestacao(linhas=[LinhaPrestacao("Faturamento", 1000.0, "subtotal")]),
    historico=Historico(colunas=[], linhas=[]),
    blocos_receitas=[
        BlocoReceita(titulo="Bloco Com Ref", linhas=[LinhaPrestacao("Total", 100.0, "total")], ref="X"),
        BlocoReceita(titulo="Bloco Sem Ref", linhas=[LinhaPrestacao("Total", 200.0, "total")]),
    ],
)
html_ref = render_html(_report_ref_html)
checar("12b. Bloco com ref='X': título mostra 'Bloco Com Ref' junto de "
       "'— Referência X'", "Bloco Com Ref" in html_ref and "— Referência X" in html_ref)
checar("12c. Bloco sem ref: título 'Bloco Sem Ref' aparece normalmente",
       "Bloco Sem Ref" in html_ref)
# Isola só a marcação de título de bloco (vd-ref-bloco), ignorando o
# comentário de exemplo em templates/report.css (que também contém o
# texto literal "— Referência A" e ficaria embutido no <style> do HTML).
checar("12d. Só existe UMA ocorrência da marcação de referência de bloco "
       "(span.vd-ref-bloco) no corpo do HTML — o bloco sem ref não herda/"
       "vaza a referência do bloco vizinho",
       html_ref.count('class="vd-ref-bloco"') == 1)
checar("12e. O título 'Bloco Sem Ref' não é seguido de nenhum "
       "'— Referência' (a ausência de bloco.ref não vaza texto)",
       "Bloco Sem Ref — Referência" not in html_ref)


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DO REFINAMENTO NILO/UI PASSARAM ===")
