"""
Cobertura permanente da 6ª rodada de homologação de set/2026 (produção real
— Débora). Achado desta rodada, confirmado via leitura READ-ONLY do banco
real de produção: EKOS e OKA têm `tipo_calculo = COM_ALIQUOTA_CUMUL` (não
COM_FAIXAS, como a documentação/comentário do código sugeria) — e o schema
desse tipo não expunha `tem_base_taxa_cobranca`/`taxa_cobranca`, embora
ambos os parâmetros já estivessem persistidos (`taxa_cobranca=0.015`,
`tem_base_taxa_cobranca=true`). Pior: o input "Base Cálculo Taxa Cobrança"
no Fechamento já é genérico (gated só por `tem_base_taxa_cobranca`, não por
tipo_calculo) — ou seja, se EKOS/OKA fossem ativadas ANTES desta correção,
o Fechamento mostraria o campo e a operadora poderia digitar um valor ali,
mas `calcular_com_aliquota_cumul` nunca o lia: dedução silenciosamente
ignorada.

Corrigido de ponta a ponta, reaproveitando EXATAMENTE a regra já usada por
COM_FAIXAS (app.calculators.faixas) — nenhuma fórmula financeira nova:
  - app/calculadora_schema.py: COM_ALIQUOTA_CUMUL ganha os campos
    tem_base_taxa_cobranca/taxa_cobranca (cópia dos já existentes em
    COM_FAIXAS).
  - app/calculators/cumulativo.py: calcula
    taxa_cobranca_valor = base_calculo_taxa_cobranca (custos_extras, com
    fallback para a receita bruta) × taxa_cobranca, deduzido do subtotal no
    mesmo estágio do imposto (antes de PE/custos/outras_despesas) — mesma
    fórmula/estágio de calcular_com_faixas. Popula extras com as mesmas
    chaves já padronizadas: taxa_cobranca, base_taxa_cobranca,
    taxa_cobranca_valor.
  - app/reporter.py (_prestacao_padrao): mostra a dedução no PDF, mesma
    posição/texto de _prestacao_faixas (depois do imposto, antes da Receita
    Líquida). O cálculo de "(-) Impostos" deixou de ser por diferença
    (faturamento - subtotal) e passou a ser direto (faturamento × alíquota)
    — necessário porque agora o subtotal também desconta a taxa de
    cobrança, e a diferença passaria a misturar as duas deduções.
  - app/ui/fechamento.py (_dre_rows_unit): mesma correção na memória de
    cálculo da tela (mesmo bug de "(-) Impostos / ISS" por diferença
    corrigido ali também — era pré-existente desde a rodada 4 e só não
    tinha sido notado porque nenhuma unidade testada até agora combinava
    Impostos + Taxa de Cobrança no mesmo subtotal).
  - app/ui/administracao.py (_aba_parametros): aviso inline (não bloqueante,
    não altera/apaga parâmetro nenhum) quando percentual_aluguel E
    faixas_aluguel estão configurados na mesma competência — faixas_aluguel
    continua tendo prioridade no calculator (cumulativo.py, inalterado
    nesta rodada).

Execução: python3 tests/testes_homologacao_set2026_v6.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v6_")
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
# 1. Calculator: COM_ALIQUOTA_CUMUL deduz Taxa de Cobrança (base default e
#    base informada), com a MESMA fórmula de COM_FAIXAS
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. calcular_com_aliquota_cumul — Taxa de Cobrança (base default e base informada)")
print("=" * 70)
from app.calculators.cumulativo import calcular_com_aliquota_cumul
from app.calculators.faixas import calcular_com_faixas

CFG_BASE = {
    "id": "ekos_cfg_teste",
    "aliquota_imposto": 0.1425,
    "ponto_equilibrio": 6550.0,
    "percentual_aluguel": 0.85,
    "taxa_cobranca": 0.015,
}

# --- 1a. Base default (sem custos_extras) = receita bruta (faturamento) ---
r_default = calcular_com_aliquota_cumul(CFG_BASE, "2027-01", faturamento=50000.0,
                                         saldo_override=0.0)
checar("extras['taxa_cobranca'] = 0.015", r_default.extras.get("taxa_cobranca") == 0.015)
checar("extras['base_taxa_cobranca'] usa a receita bruta como default (50000.0)",
       r_default.extras.get("base_taxa_cobranca") == 50000.0)
checar("extras['taxa_cobranca_valor'] = 50000.0 * 0.015 = 750.0",
       r_default.extras.get("taxa_cobranca_valor") == 750.0)
checar("subtotal já desconta a taxa de cobrança (50000*(1-0.1425) - 750)",
       r_default.subtotal == round(50000.0 * (1 - 0.1425) - 750.0, 2))

# --- 1b. Base informada via custos_extras (Fechamento -> Base Cálculo Taxa
#     Cobrança) tem prioridade sobre a receita bruta ---
r_base_informada = calcular_com_aliquota_cumul(
    CFG_BASE, "2027-01", faturamento=50000.0, saldo_override=0.0,
    custos_extras={"base_calculo_taxa_cobranca": 40000.0},
)
checar("Base informada (40000.0) prevalece sobre a receita bruta (50000.0)",
       r_base_informada.extras.get("base_taxa_cobranca") == 40000.0)
checar("taxa_cobranca_valor usa a base informada: 40000 * 0.015 = 600.0",
       r_base_informada.extras.get("taxa_cobranca_valor") == 600.0)

# --- 1c. Equivalência com COM_FAIXAS: mesma base/taxa/faturamento produzem
#     exatamente o mesmo taxa_cobranca_valor nos dois calculators ---
CFG_FAIXAS_EQUIV = {
    "id": "ekos_cfg_teste", "aliquota_imposto": 0.1425, "ponto_equilibrio": 6550.0,
    "taxa_cobranca": 0.015, "faixas": [{"ate": None, "percentual": 0.85}],
}
r_faixas_equiv = calcular_com_faixas(CFG_FAIXAS_EQUIV, "2027-01", faturamento=50000.0)
checar("taxa_cobranca_valor idêntico entre COM_ALIQUOTA_CUMUL e COM_FAIXAS (mesma regra)",
       r_default.extras["taxa_cobranca_valor"] == r_faixas_equiv.extras["taxa_cobranca_valor"])
checar("subtotal idêntico entre os dois calculators para a mesma entrada",
       r_default.subtotal == r_faixas_equiv.subtotal)

# --- 1d. Sem taxa_cobranca configurada (regressão: nenhuma unidade sem
#     essa rubrica pode ser afetada) ---
CFG_SEM_TAXA = {"id": "viva_teste", "aliquota_imposto": 0.0, "percentual_aluguel": 0.85,
                 "ponto_equilibrio": 0.0}
r_sem_taxa = calcular_com_aliquota_cumul(CFG_SEM_TAXA, "2027-01", faturamento=-1525.24 + 2400.0,
                                          saldo_override=-157142.75,
                                          custos_extras={"outras_despesas": 2400.0})
checar("Sem taxa_cobranca configurada, extras não tem nenhuma das 3 chaves",
       not any(k in r_sem_taxa.extras for k in ("taxa_cobranca", "base_taxa_cobranca", "taxa_cobranca_valor")))
checar("Golden da Viva Trindade continua -158.667,99 (regressão da rodada 3/4)",
       r_sem_taxa.prejuizo_acumulado_saida == -158667.99)


# ═══════════════════════════════════════════════════════════════════════
# 2. Faixas de Aluguel continuam tendo prioridade sobre Percentual de
#    Aluguel (comportamento do calculator inalterado nesta rodada)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. faixas_aluguel tem prioridade sobre percentual_aluguel (inalterado)")
print("=" * 70)
CFG_AMBOS = {
    "id": "ekos_prioridade_teste", "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0,
    "percentual_aluguel": 0.50,  # deliberadamente diferente da faixa, para provar a prioridade
    "faixas_aluguel": [{"ate": None, "percentual": 0.85}],
}
r_prioridade = calcular_com_aliquota_cumul(CFG_AMBOS, "2027-01", faturamento=10000.0,
                                            saldo_override=0.0)
checar("Com os dois configurados, o aluguel usa a FAIXA (85%), não o percentual (50%)",
       r_prioridade.aluguel_calculado == round(10000.0 * 0.85, 2))


# ═══════════════════════════════════════════════════════════════════════
# 3. Administração: schema COM_ALIQUOTA_CUMUL agora expõe Taxa de Cobrança;
#    aviso de ambiguidade Percentual×Faixas aparece só quando os dois estão
#    configurados; pode_ativar_unidade() continua [] para EKOS/OKA
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Administração — schema, render ao vivo, aviso de ambiguidade")
print("=" * 70)
from app.calculadora_schema import campos_do_tipo

campos_cumul = campos_do_tipo("COM_ALIQUOTA_CUMUL")
chaves_cumul = {c["chave"] for c in campos_cumul}
checar("COM_ALIQUOTA_CUMUL agora tem 'tem_base_taxa_cobranca' no schema",
       "tem_base_taxa_cobranca" in chaves_cumul)
checar("COM_ALIQUOTA_CUMUL agora tem 'taxa_cobranca' no schema",
       "taxa_cobranca" in chaves_cumul)

from app.models import criar_unidade, salvar_parametros
from app.engine import get_unit_com_params, load_units
from app.models import pode_ativar_unidade

UID_TESTE = "ekos_teste_v6"
criar_unidade(UID_TESTE, "EKOS Teste v6", "EKOS Teste", "2026-07-01", "COM_ALIQUOTA_CUMUL")
# Réplica exata dos fatos confirmados em produção para EKOS/OKA (leitura
# READ-ONLY já feita nas rodadas anteriores) — nenhum dado real é tocado,
# esta é uma unidade sintética isolada no sandbox de teste.
salvar_parametros(UID_TESTE, "2026-07", {
    "aliquota_imposto": 0.1425,
    "ponto_equilibrio": 6550.0,
    "tem_base_taxa_cobranca": True,
    "taxa_cobranca": 0.015,
    "percentual_aluguel": 0.85,
    "faixas_aluguel": [{"ate": None, "percentual": 0.85}],
}, alterado_por="teste_v6")

pendencias = pode_ativar_unidade(UID_TESTE, "2026-09")
checar("pode_ativar_unidade() == [] para a réplica de EKOS/OKA (nenhuma pendência nova)",
       pendencias == [])

from streamlit.testing.v1 import AppTest

_APP_PROBE = os.path.join(_REPO_ROOT, "tests", "_probe_admin_v6.py")
with open(_APP_PROBE, "w") as f:
    f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
import streamlit as st
st.session_state.admin_view = "editar"
st.session_state.admin_editar_uid = {UID_TESTE!r}
from app.ui.administracao import tela_administracao_unidades
tela_administracao_unidades()
''')
try:
    at = AppTest.from_file(_APP_PROBE, default_timeout=60)
    at.run()
    checar("Tela de Administração renderiza sem exceção", len(at.exception) == 0)

    params_tab = at.tabs[1]
    toggles = {t.label: t.value for t in params_tab.toggle}
    numeros = {n.label: n.value for n in params_tab.number_input}

    checar("Toggle 'Tem Taxa de Cobrança' renderiza e está ligado",
           toggles.get("Tem Taxa de Cobrança") is True)
    checar("Input 'Percentual da Taxa de Cobrança' renderiza com 1,5%",
           any("Taxa de Cobrança" in lbl and abs(v - 1.5) < 1e-6 for lbl, v in numeros.items()))

    avisos = [w.value for w in params_tab.warning]
    checar("Aviso de ambiguidade Percentual x Faixas aparece (os dois estão configurados)",
           any("Faixas de Aluguel está configurado e tem prioridade" in w for w in avisos))
finally:
    os.remove(_APP_PROBE)


# ═══════════════════════════════════════════════════════════════════════
# 4. Aviso de ambiguidade NÃO aparece quando só um dos dois está configurado
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Aviso de ambiguidade some quando só um dos dois campos tem valor")
print("=" * 70)
UID_SO_PERCENTUAL = "ekos_teste_v6_so_pct"
criar_unidade(UID_SO_PERCENTUAL, "Só Percentual Teste v6", "Teste", "2026-07-01", "COM_ALIQUOTA_CUMUL")
salvar_parametros(UID_SO_PERCENTUAL, "2026-07", {
    "aliquota_imposto": 0.1425, "ponto_equilibrio": 6550.0,
    "percentual_aluguel": 0.85,
}, alterado_por="teste_v6")

_APP_PROBE2 = os.path.join(_REPO_ROOT, "tests", "_probe_admin_v6b.py")
with open(_APP_PROBE2, "w") as f:
    f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
import streamlit as st
st.session_state.admin_view = "editar"
st.session_state.admin_editar_uid = {UID_SO_PERCENTUAL!r}
from app.ui.administracao import tela_administracao_unidades
tela_administracao_unidades()
''')
try:
    at2 = AppTest.from_file(_APP_PROBE2, default_timeout=60)
    at2.run()
    avisos2 = [w.value for w in at2.tabs[1].warning]
    checar("Sem faixas_aluguel configurado, o aviso de ambiguidade NÃO aparece",
           not any("Faixas de Aluguel está configurado e tem prioridade" in w for w in avisos2))
finally:
    os.remove(_APP_PROBE2)


# ═══════════════════════════════════════════════════════════════════════
# 5. Memória de cálculo da tela (_dre_rows_unit) e PDF (_prestacao_padrao)
#    mostram a Taxa de Cobrança na ordem correta, usando só extras
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5. Memória de cálculo (tela) e PDF — ordem e valores")
print("=" * 70)
from app.ui.fechamento import _dre_rows_unit
from app.reporter import _prestacao_padrao

r_ekos = calcular_com_aliquota_cumul(CFG_BASE, "2027-01", faturamento=50000.0, saldo_override=0.0)

rows_tela = _dre_rows_unit(r_ekos)
labels_tela = [lbl for lbl, _ in rows_tela]


def _idx(labels, alvo_substr):
    for i, lbl in enumerate(labels):
        if alvo_substr in lbl:
            return i
    return None


i_imp = _idx(labels_tela, "Impostos")
i_taxa = _idx(labels_tela, "Taxa de Cobrança")
i_sub = _idx(labels_tela, "Subtotal")
i_pe = _idx(labels_tela, "Ponto de Equilíbrio")
checar("Memória da tela: Taxa de Cobrança aparece", i_taxa is not None)
checar("Memória da tela: ordem Impostos -> Taxa de Cobrança -> Subtotal -> PE",
       i_imp is not None and i_imp < i_taxa < i_sub < i_pe)
checar("Memória da tela: valor da Taxa de Cobrança é (R$ 750,00)",
       dict(rows_tela)[labels_tela[i_taxa]] == "(R$ 750,00)")
checar("Memória da tela: rótulo inclui percentual e base (mesmo texto do PDF)",
       "1.5%" in labels_tela[i_taxa] and "50.000,00" in labels_tela[i_taxa]
       or "1,5%" in labels_tela[i_taxa])  # tolera variação de locale na formatação do %

cfg_pdf = dict(CFG_BASE)
cfg_pdf["relatorio"] = {"linhas": ["faturamento", "aliquota", "pe", "resultado", "prejuizo"]}
prestacao = _prestacao_padrao(r_ekos, cfg_pdf)
labels_pdf = [l.descricao for l in prestacao.linhas]
i_imp_pdf = _idx(labels_pdf, "Impostos")
i_taxa_pdf = _idx(labels_pdf, "Taxa de Cobrança")
i_liq_pdf = _idx(labels_pdf, "Receita Líquida")
checar("PDF: Taxa de Cobrança aparece na prestação", i_taxa_pdf is not None)
checar("PDF: ordem Impostos -> Taxa de Cobrança -> Receita Líquida",
       i_imp_pdf is not None and i_imp_pdf < i_taxa_pdf < i_liq_pdf)
valor_taxa_pdf = next(l.valor for l in prestacao.linhas if "Taxa de Cobrança" in l.descricao)
checar("PDF: valor da Taxa de Cobrança = -750.0", valor_taxa_pdf == -750.0)

# --- Sem taxa_cobranca: linha não aparece em nenhum dos dois lugares ---
rows_sem_taxa = _dre_rows_unit(r_sem_taxa)
checar("Sem taxa_cobranca configurada, a linha não aparece na memória da tela",
       _idx([lbl for lbl, _ in rows_sem_taxa], "Taxa de Cobrança") is None)
prestacao_sem_taxa = _prestacao_padrao(r_sem_taxa, {"relatorio": {"linhas": ["faturamento", "resultado"]}})
checar("Sem taxa_cobranca configurada, a linha não aparece no PDF",
       not any("Taxa de Cobrança" in l.descricao for l in prestacao_sem_taxa.linhas))


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 6) PASSARAM ===")
