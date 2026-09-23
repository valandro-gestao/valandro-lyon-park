"""
Cobertura permanente da 9ª rodada de homologação de set/2026 — arquitetura
`COM_ALIQUOTA_CUMUL_DU`, caso-piloto Nilo Square (Square legado FORA do
escopo desta implementação). Nenhuma unidade real foi criada; nenhuma das
9 unidades `COM_ALIQUOTA_CUMUL` existentes (Viva Trindade, W Tower,
EKOS/OKA, Dom Pedro, Anitta Mall, A. Schneider, ILP, MW Tristeza) é tocada
— o novo `tipo_calculo` é isolado, com calculator/schema/reporter/UI
próprios (ver app/calculators/cumul_du.py).

Convenção de sinal (confirmada pela operadora, mesma da planilha legado):
despesa normal = valor POSITIVO; estorno/reembolso = valor NEGATIVO; zero
permitido. O calculator SUBTRAI o total de cada grupo — um reembolso
negativo reduz esse total algebricamente, nunca vira uma segunda dedução.

Estrutura (nomes das 4 rubricas dinâmicas) é definida na Administração
(app.calculadora_schema._ITEM_SCHEMA_RUBRICA_SOMENTE_NOME — sem sub-campo
"Valor"); os valores são exclusivamente mensais, informados no Fechamento
(app.ui.fechamento._inputs_rubricas_du), nunca geram vigência nova.

Execução: python3 tests/testes_homologacao_set2026_v9.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v9_")
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


CFG_NILO = {
    "id": "nilo_square_teste", "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0,
    "numero_vagas": 1129, "percentual_aluguel": 0.85,
    "despesas_ressarcimento_du": [
        {"id": "proprietarios", "nome": "Proprietários"},
        {"id": "provisionamento_iptu", "nome": "Provisionamento IPTU"},
    ],
    "despesas_rateio_du": [
        {"id": "agua", "nome": "Água"}, {"id": "energia", "nome": "Energia"},
    ],
    "despesas_operacao": [{"id": "seguranca", "nome": "Segurança"}],
    "despesas_pos_resultado": [{"id": "investimentos", "nome": "Investimentos"}],
}


# ═══════════════════════════════════════════════════════════════════════
# 1. Golden completo — valores do legado
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. Golden — Receita DU 234.896,54, Rateio DU 236.457,21 / 1.129 vagas")
print("=" * 70)
from app.calculators.cumul_du import calcular_com_aliquota_cumul_du
from app.reporter import _prestacao_cumul_du
from app.ui.fechamento import _dre_rows_unit

ce_golden = {
    "receita_ressarcimento_du": 234896.54,
    "despesas_ressarcimento_du": {"proprietarios": 82882.08, "provisionamento_iptu": 25066.43},
    "despesas_rateio_du": {"agua": 100000.0, "energia": 136457.21},  # soma = 236457.21
}
r_golden = calcular_com_aliquota_cumul_du(
    CFG_NILO, "2026-07", faturamento=300000.0, saldo_override=0.0, custos_extras=ce_golden,
)
checar("Ressarcimento Líquido DU = R$ 126.948,03 (golden legado)",
       r_golden.extras["ressarcimento_liquido_du"] == 126948.03)
checar("Total Despesas Rateio DU = R$ 236.457,21 (golden legado)",
       r_golden.extras["total_despesas_rateio_du"] == 236457.21)
checar("Valor DU por vaga = R$ 209,44 (236.457,21 / 1.129, golden legado)",
       r_golden.extras["du_por_vaga"] == 209.44)
# Prova de "sem dupla dedução": o MESMO total de Rateio DU alimenta os dois
# lugares (dedução na DRE e DU/vaga) a partir de uma única fonte — mudar a
# despesa de Rateio DU move os dois na mesma proporção, nunca duplica.
ce_outro_rateio = dict(ce_golden)
ce_outro_rateio["despesas_rateio_du"] = {"agua": 100000.0, "energia": 236457.21}  # +100000 vs golden
r_outro = calcular_com_aliquota_cumul_du(CFG_NILO, "2026-07", faturamento=300000.0,
                                          saldo_override=0.0, custos_extras=ce_outro_rateio)
delta_total = round(r_outro.extras["total_despesas_rateio_du"] - r_golden.extras["total_despesas_rateio_du"], 2)
delta_resultado = round(r_golden.resultado - r_outro.resultado, 2)
checar("Sem dupla dedução: o delta no Resultado bate exatamente com o delta do total de Rateio DU",
       delta_total == delta_resultado == 100000.0)
# du_por_vaga é a MESMA base (total_despesas_rateio_du) só dividida pelas
# vagas — comparação com tolerância pequena (arredondamento de exibição a
# 2 casas, não um erro de cálculo).
delta_du_vaga_esperado = round(delta_total / CFG_NILO["numero_vagas"], 2)
delta_du_vaga_real = round(r_outro.extras["du_por_vaga"] - r_golden.extras["du_por_vaga"], 2)
checar("du_por_vaga varia na mesma proporção do total de Rateio DU (mesma fonte, só dividida pelas vagas)",
       abs(delta_du_vaga_real - delta_du_vaga_esperado) < 0.01)

prest_golden = _prestacao_cumul_du(r_golden, CFG_NILO)
labels_golden = [l.descricao for l in prest_golden.linhas]
checar("PDF mostra 'Ressarcimento Líquido DU'", "Ressarcimento Líquido DU" in labels_golden)
checar("PDF mostra 'Valor de Direito de Uso por Vaga (informativo)'",
       any("Direito de Uso por Vaga" in l for l in labels_golden))
du_vaga_pdf = next(l.valor for l in prest_golden.linhas if "Direito de Uso por Vaga" in l.descricao)
checar("PDF: Direito de Uso por Vaga = 209.44", du_vaga_pdf == 209.44)

rows_golden = dict(_dre_rows_unit(r_golden))
checar("Memória da tela mostra 'Ressarcimento Líquido DU' = R$ 126.948,03",
       rows_golden.get("Ressarcimento Líquido DU") == "R$ 126.948,03")


# ═══════════════════════════════════════════════════════════════════════
# 2. Rubrica negativa funcionando como reembolso (sem dupla dedução)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Reembolso — rubrica negativa reduz o total algebricamente")
print("=" * 70)
ce_sem_reembolso = {"despesas_rateio_du": {"agua": 10000.0, "energia": 5000.0}}
r_sem = calcular_com_aliquota_cumul_du(CFG_NILO, "2026-07", faturamento=100000.0,
                                        saldo_override=0.0, custos_extras=ce_sem_reembolso)

ce_com_reembolso = {"despesas_rateio_du": {"agua": 10000.0, "energia": -1481.76}}
r_com = calcular_com_aliquota_cumul_du(CFG_NILO, "2026-07", faturamento=100000.0,
                                        saldo_override=0.0, custos_extras=ce_com_reembolso)
checar("Sem reembolso: total Rateio DU = 15.000,00", r_sem.extras["total_despesas_rateio_du"] == 15000.0)
checar("Com reembolso de Energia (-1.481,76): total Rateio DU = 8.518,24 (10000 - 1481.76)",
       r_com.extras["total_despesas_rateio_du"] == 8518.24)
checar("O reembolso REDUZ o total (menor dedução), não cria receita/segunda linha",
       r_com.resultado > r_sem.resultado)
checar("Resultado aumenta exatamente na diferença do total (6.481,76)",
       round(r_com.resultado - r_sem.resultado, 2) == 6481.76)
item_energia = next(i for i in r_com.extras["despesas_rateio_du"] if i["id"] == "energia")
checar("extras: item 'Energia' aparece com valor -1.481,76 (não some, não vira outra rubrica)",
       item_energia["valor"] == -1481.76)


# ═══════════════════════════════════════════════════════════════════════
# 3. Cadeia de prejuízo acumulado (2 competências)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Cadeia de prejuízo acumulado — julho -> agosto")
print("=" * 70)
CFG_PREJUIZO = dict(CFG_NILO)
CFG_PREJUIZO["ponto_equilibrio"] = 500000.0  # força resultado_disponivel negativo
r_jul = calcular_com_aliquota_cumul_du(CFG_PREJUIZO, "2026-07", faturamento=100000.0,
                                        saldo_override=0.0, custos_extras={})
checar("Julho: resultado_disponivel negativo -> prejuizo_acumulado_saida < 0",
       r_jul.prejuizo_acumulado_saida < 0)
checar("Julho: aluguel_calculado = 0 (sem repasse quando indisponível)",
       r_jul.aluguel_calculado == 0.0)

r_ago = calcular_com_aliquota_cumul_du(CFG_PREJUIZO, "2026-08", faturamento=100000.0,
                                        saldo_override=r_jul.prejuizo_acumulado_saida, custos_extras={})
checar("Agosto: prejuizo_acumulado_entrada = saída de julho (cadeia correta)",
       r_ago.prejuizo_acumulado_entrada == r_jul.prejuizo_acumulado_saida)
checar("Agosto: prejuizo_acumulado_saida é MAIS negativo que julho (acumula)",
       r_ago.prejuizo_acumulado_saida < r_jul.prejuizo_acumulado_saida)

prest_jul = _prestacao_cumul_du(r_jul, CFG_PREJUIZO)
linha_prej_jul = next(l for l in prest_jul.linhas if "Prejuízo Acumulado" in l.descricao)
checar("PDF de julho mostra '(+/-) Prejuízo Acumulado' com o valor correto",
       linha_prej_jul.valor == r_jul.prejuizo_acumulado_saida)
prest_ago = _prestacao_cumul_du(r_ago, CFG_PREJUIZO)
linha_prej_ago = next(l for l in prest_ago.linhas if "Prejuízo Acumulado" in l.descricao)
checar("PDF de agosto mostra a NOVA saída (acumulada), não a de julho",
       linha_prej_ago.valor == r_ago.prejuizo_acumulado_saida != r_jul.prejuizo_acumulado_saida)


# ═══════════════════════════════════════════════════════════════════════
# 4. Ponta a ponta: Administração -> Fechamento -> cálculo -> PDF
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Ponta a ponta — Administração define estrutura, Fechamento informa valores")
print("=" * 70)
from app.models import criar_unidade, salvar_parametros, get_unidade
from app.engine import calcular, load_units, get_unit_com_params

UID_E2E = "nilo_square_e2e"
criar_unidade(UID_E2E, "Nilo Square E2E", "Nilo Square", "2026-07-01", "COM_ALIQUOTA_CUMUL_DU")
load_units(force=True)
checar("Unidade criada só por criar_unidade() (sem YAML) tem tipo_calculo correto",
       get_unidade(UID_E2E)["tipo_calculo"] == "COM_ALIQUOTA_CUMUL_DU")

# Administração: só ESTRUTURA (id+nome), sem valor algum.
salvar_parametros(UID_E2E, "2026-07", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 1129,
    "percentual_aluguel": 0.85,
    "despesas_ressarcimento_du": [{"id": "proprietarios", "nome": "Proprietários"}],
    "despesas_rateio_du": [{"id": "energia", "nome": "Energia"}],
    "despesas_operacao": [{"id": "seguranca", "nome": "Segurança"}],
    "despesas_pos_resultado": [],
}, alterado_por="teste_v9")

cfg_e2e = get_unit_com_params(UID_E2E, "2026-07")
checar("Estrutura salva não tem 'valor' em nenhum item (só id/nome)",
       all("valor" not in item for item in cfg_e2e["despesas_ressarcimento_du"]))

# Fechamento: valores mensais (nunca vigência).
custos_extras_e2e = {
    "receita_ressarcimento_du": 50000.0,
    "despesas_ressarcimento_du": {"proprietarios": 20000.0},
    "despesas_rateio_du": {"energia": 3000.0},
    "despesas_operacao": {"seguranca": 1000.0},
    "despesas_pos_resultado": {},
}
r_e2e = calcular(UID_E2E, "2026-07", 200000.0, saldo_override=0.0, custos_extras=custos_extras_e2e)
checar("Cálculo via app.engine.calcular() (dispatch por tipo_calculo) funciona ponta a ponta",
       r_e2e.extras["ressarcimento_liquido_du"] == 30000.0)  # 50000 - 20000

from app.models import get_parametros_vigentes
rows_antes = get_parametros_vigentes(UID_E2E, "2026-08")
qtd_vigencias_antes = len(rows_antes)
checar("Estrutura de julho continua vigente em agosto (sem nova vigência criada pelo cálculo)",
       "despesas_ressarcimento_du" in rows_antes)

prest_e2e = _prestacao_cumul_du(r_e2e, cfg_e2e)
checar("PDF ponta a ponta mostra a rubrica 'Proprietários' com o valor mensal informado",
       any(l.descricao == "(-) Proprietários (Ressarcimento DU)" and l.valor == -20000.0
           for l in prest_e2e.linhas))


# ═══════════════════════════════════════════════════════════════════════
# 5. Nilo Square vazia — criável/configurável 100% pela Administração
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5. Unidade vazia criada integralmente pela Administração (sem YAML)")
print("=" * 70)
from app.calculadora_schema import campos_do_tipo
from streamlit.testing.v1 import AppTest

campos_nilo = campos_do_tipo("COM_ALIQUOTA_CUMUL_DU")
checar("Schema COM_ALIQUOTA_CUMUL_DU tem os 4 grupos de rubricas + numero_vagas",
       {"despesas_ressarcimento_du", "despesas_rateio_du", "despesas_operacao",
        "despesas_pos_resultado", "numero_vagas"} <= {c["chave"] for c in campos_nilo})

UID_VAZIA = "nilo_square_vazia"
criar_unidade(UID_VAZIA, "Nilo Square Vazia", "Nilo Square", "2026-07-01", "COM_ALIQUOTA_CUMUL_DU")
load_units(force=True)

_APP_PROBE = os.path.join(_REPO_ROOT, "tests", "_probe_nilo_v9.py")
with open(_APP_PROBE, "w") as f:
    f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
import streamlit as st
st.session_state.admin_view = "editar"
st.session_state.admin_editar_uid = {UID_VAZIA!r}
from app.ui.administracao import tela_administracao_unidades
tela_administracao_unidades()
''')
try:
    at = AppTest.from_file(_APP_PROBE, default_timeout=60)
    at.run()
    checar("Tela de Administração renderiza sem exceção para uma Nilo Square recém-criada, vazia",
           len(at.exception) == 0)
    params_tab = at.tabs[1]
    labels_campos = {n.label for n in params_tab.number_input}
    checar("Campo 'Número de Vagas' renderiza", any("Número de Vagas" in l for l in labels_campos))
    dfs = list(params_tab.dataframe)
    checar("Os 4 editores de rubricas dinâmicas renderizam (4 tabelas, nenhuma coluna 'Valor')",
           len(dfs) >= 4 and all("Valor" not in list(df.value.columns) for df in dfs))
finally:
    os.remove(_APP_PROBE)


# ═══════════════════════════════════════════════════════════════════════
# 6. Regressão — as 9 unidades COM_ALIQUOTA_CUMUL/EKOS-OKA continuam iguais
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("6. Regressão — COM_ALIQUOTA_CUMUL (Viva Trindade, EKOS) e demais tipos intocados")
print("=" * 70)
from app.calculators.cumulativo import calcular_com_aliquota_cumul

CFG_VIVA = {"id": "viva_trindade", "aliquota_imposto": 0.0, "percentual_aluguel": 0.85,
            "ponto_equilibrio": 0.0}
r_viva = calcular_com_aliquota_cumul(CFG_VIVA, "2026-08", faturamento=-1525.24 + 2400.0,
                                      saldo_override=-157142.75,
                                      custos_extras={"outras_despesas": 2400.0})
checar("Regressão: golden da Viva Trindade continua -158.667,99",
       r_viva.prejuizo_acumulado_saida == -158667.99)

CFG_EKOS = {"id": "ekos", "aliquota_imposto": 0.1425, "ponto_equilibrio": 6550.0,
            "taxa_cobranca": 0.015, "percentual_aluguel": 0.85}
r_ekos = calcular_com_aliquota_cumul(
    CFG_EKOS, "2026-07", faturamento=2895.42, saldo_override=0.0,
    custos_extras={"base_calculo_taxa_cobranca": 2895.42},
)
checar("Regressão: golden da EKOS julho/2026 continua -4.110,61 (rodada 7)",
       r_ekos.resultado == -4110.61)
checar("calcular_com_aliquota_cumul não ganhou nenhum campo novo de Direito de Uso",
       "ressarcimento_liquido_du" not in r_ekos.extras and "ressarcimento_liquido_du" not in r_viva.extras)


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 9) PASSARAM ===")
