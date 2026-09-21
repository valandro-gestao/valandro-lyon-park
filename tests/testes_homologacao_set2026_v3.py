"""
Cobertura permanente da 3ª rodada de homologação de set/2026 (produção real
— Débora). Três problemas, causa comprovada em código e, para o Pátio
FIERGS, também numa reprodução ao vivo com `st.data_editor` de verdade
(fora deste arquivo — ver relatório da investigação):

  1. Viva Trindade — "Aprovar" reaproveitava `st.session_state.resultados`
     (cache de sessão, chaveado só por unidade) ou o último `lancamentos`
     salvo, NUNCA recalculando — então uma competência aprovada depois que
     uma competência ANTERIOR foi reprocessada podia persistir com uma
     entrada de prejuízo acumulado já desatualizada. Corrigido:
     `app.ui.fechamento._aprovar_unidade` sempre chama `calcular()` na
     hora; o cache de sessão passa a ser chaveado por (unidade,
     competência); a limpeza do rascunho roda logo após `salvar_lancamento`
     ter sucesso, antes de PDF/parâmetros — e nunca é desfeita por uma
     falha posterior (que continua sendo reportada, via ErroPosAprovacao,
     nunca mascarada).

  2. FIERGS — rubricas novas "desapareciam" ao salvar porque uma célula do
     `st.data_editor` ainda em edição ativa (nunca confirmada com Enter/
     Tab/clique fora) só sincroniza para o Python num rerun POSTERIOR ao
     clique que o dispara — reproduzido ao vivo, inclusive DENTRO de
     st.form (que não resolve). Corrigido com um fluxo de revisão em duas
     etapas em app.ui.administracao._aba_parametros ("Revisar alterações"
     força o ciclo de rerun necessário; "Confirmar e salvar" persiste
     exatamente o snapshot mostrado, nunca relê os widgets) — aplicado a
     todo tipo_calculo com pelo menos um campo lista_estruturada/
     mapa_rubricas; tipos 100% escalares (PERCENTUAL_SIMPLES,
     COM_ALIQUOTA) mantêm o botão direto. `_fingerprint` continua existindo
     (resolve um problema real e diferente: key estática sobrevivendo a um
     valor já mudado) mas não é mais tratado como a correção do problema
     acima.

  3. EKOS/OKA — Taxa de Cobrança já está persistida corretamente; a causa
     é `ativo=0` excluindo a unidade inteira de `get_unidades_ativas`
     (Fechamento), não o campo. `pode_ativar_unidade` confirma que não há
     pendência bloqueando a ativação — mas nenhuma unidade é ativada aqui
     (isso é uma ação explícita da operadora na tela, não um dado a mudar).

Execução: python3 tests/testes_homologacao_set2026_v3.py
"""
import json
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v3_")
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
# 1. Viva Trindade — "Aprovar" sempre recalcula; sessão isolada por mês
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. Viva Trindade — aprovação sempre recalcula, nunca reaproveita cache")
print("=" * 70)
from app import run_manager as rm
from app.models import (
    get_db, salvar_rascunho_unidade, carregar_rascunho_unidade,
)
from app.engine import get_unit_com_params, calcular
from app.ui.fechamento import (
    _aprovar_unidade, ErroPosAprovacao, _salvar_resultado_session,
)

UID = "viva_trindade"


def _custos_extras_zerados(mes_ref):
    """custos_extras "neutro" (investimentos/outras_despesas = valor vigente,
    sem digitar nada de especial) — usado nos testes que só querem variar
    faturamento/subtotal."""
    from app.rubricas import normalizar_rubricas
    u_cfg = get_unit_com_params(UID, mes_ref)
    return {item.id: item.valor for item in normalizar_rubricas(u_cfg.get("custos_variaveis"))}


def _lancamento_db(uid, mes_ref):
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
            (uid, mes_ref),
        ).fetchone()
    if row is None:
        return None
    return row["status"], json.loads(row["resultado_json"])


# --- 1a. calcular julho -> trocar para agosto -> Aprovar sem recalcular
#     manualmente -> aprovação obrigatoriamente calcula agosto (usa os
#     dados de agosto, não os de julho que ficaram "calculados" por último).
print("--- 1a. Aprovar agosto sem clicar Calcular antes usa dados de agosto, não os de julho ---")
u_cfg_jul = get_unit_com_params(UID, "2026-07")
r_julho_calculado = calcular(UID, "2026-07", 30000.0, custos_extras=_custos_extras_zerados("2026-07"))
_salvar_resultado_session(UID, "2026-07", 30000.0, r_julho_calculado)
# "Trocou para agosto" -- nunca clicou Calcular para agosto; aprova direto,
# só com os dados que o formulário de agosto teria (fat/custos próprios).
u_cfg_ago = get_unit_com_params(UID, "2026-08")
r_aprovado_ago = _aprovar_unidade(
    UID, "2026-08", u_cfg_ago, 48674.03, None, _custos_extras_zerados("2026-08"),
)
checar("1a. aprovação de agosto usa o FATURAMENTO de agosto (48674.03), não o de julho (30000.0)",
       r_aprovado_ago.faturamento == 48674.03)
status_db, dados_db = _lancamento_db(UID, "2026-08")
checar("1a. lançamento persistido de agosto reflete o faturamento de agosto, não o cache de julho",
       dados_db["faturamento"] == 48674.03 and status_db == "aprovado")
print()


# --- 1b. calcular agosto -> alterar/reaprovar julho -> aprovar agosto ->
#     agosto usa a saída ATUAL de julho (regressão exata do bug de produção).
print("--- 1b. reprocessar julho DEPOIS de aprovar agosto corrige a entrada de agosto na próxima aprovação ---")
UID2 = UID  # mesma unidade, competências isoladas do bloco acima (2026-07/08 já usadas -- usa 2027 para isolar)
MES_JUL, MES_AGO = "2027-01", "2027-02"

u_jul = get_unit_com_params(UID2, MES_JUL)
r1 = _aprovar_unidade(UID2, MES_JUL, u_jul, 40000.0, None, _custos_extras_zerados(MES_JUL))
saida_julho_original = r1.prejuizo_acumulado_saida
print(f"    julho aprovado pela 1ª vez: saída = {saida_julho_original}")

# Calcula (mas não recalcula na aprovação seguinte) agosto sobre a saída
# ORIGINAL de julho -- simula "calculou agosto, foi ver outra coisa".
u_ago = get_unit_com_params(UID2, MES_AGO)
r_ago_stale = calcular(UID2, MES_AGO, 45000.0, custos_extras=_custos_extras_zerados(MES_AGO))
_salvar_resultado_session(UID2, MES_AGO, 45000.0, r_ago_stale)
checar("1b. cálculo preliminar de agosto usou a saída ORIGINAL de julho como entrada",
       abs(r_ago_stale.prejuizo_acumulado_entrada - saida_julho_original) < 0.005)

# Reabre e reprocessa julho com um faturamento DIFERENTE -- muda a saída de julho.
rm.reopen(MES_JUL, UID2)
r1_novo = _aprovar_unidade(UID2, MES_JUL, u_jul, 55000.0, None, _custos_extras_zerados(MES_JUL))
saida_julho_nova = r1_novo.prejuizo_acumulado_saida
checar("1b. reprocessar julho realmente mudou sua saída", saida_julho_nova != saida_julho_original)

# Aprova agosto SEM clicar Calcular de novo -- só com fat/custos "de agosto"
# (exatamente o que o formulário mostraria); a entrada usada precisa vir da
# saída NOVA de julho, não do cálculo preliminar (stale) armazenado acima.
r_ago_final = _aprovar_unidade(UID2, MES_AGO, u_ago, 45000.0, None, _custos_extras_zerados(MES_AGO))
checar("1b. agosto aprovado usa a saída ATUAL (pós-reprocessamento) de julho como entrada",
       abs(r_ago_final.prejuizo_acumulado_entrada - saida_julho_nova) < 0.005)
checar("1b. agosto aprovado NÃO usa mais a saída antiga (stale) de julho",
       abs(r_ago_final.prejuizo_acumulado_entrada - saida_julho_original) > 0.005)
_, dados_ago_db = _lancamento_db(UID2, MES_AGO)
checar("1b. o que foi persistido em lancamentos bate com o que a aprovação calculou",
       abs(dados_ago_db["prejuizo_acumulado_entrada"] - saida_julho_nova) < 0.005)
print()


# --- 1c. resultado de uma competência nunca é consumido por outra ---
print("--- 1c. cache de sessão isolado por (unidade, competência) ---")
import streamlit as st
st.session_state.clear()
r_c1 = calcular(UID, "2027-03", 10000.0, custos_extras=_custos_extras_zerados("2027-03"))
_salvar_resultado_session(UID, "2027-03", 10000.0, r_c1)
r_c2 = calcular(UID, "2027-04", 99999.0, custos_extras=_custos_extras_zerados("2027-04"))
_salvar_resultado_session(UID, "2027-04", 99999.0, r_c2)
checar("1c. resultados de 2027-03 e 2027-04 coexistem no cache, cada um com seu faturamento",
       st.session_state.resultados[(UID, "2027-03")].faturamento == 10000.0
       and st.session_state.resultados[(UID, "2027-04")].faturamento == 99999.0)
checar("1c. calcular um mês novo não sobrescreve o cache do mês anterior (chave inclui a competência)",
       (UID, "2027-03") in st.session_state.resultados and (UID, "2027-04") in st.session_state.resultados)
print()


# --- 1d. falha simulada na geração do PDF depois de salvar_lancamento ->
#     lançamento permanece salvo, rascunho não sobrevive para contaminar
#     uma reabertura futura.
print("--- 1d. falha na geração do PDF não desfaz o lançamento nem deixa rascunho obsoleto ---")
MES_ERRO = "2027-05"
u_erro = get_unit_com_params(UID, MES_ERRO)

# Simula um rascunho JÁ existente para esta competência (ex.: sobra de uma
# sessão anterior, de antes de um deploy) -- precisa desaparecer assim que
# o lançamento for salvo, mesmo que o PDF falhe depois.
salvar_rascunho_unidade(UID, MES_ERRO, {"fat_viva_trindade": 12345.0, "cv_viva_trindade_investimentos": 999.0})
checar("1d. pré-condição: existe rascunho pendente para a competência antes do teste",
       carregar_rascunho_unidade(UID, MES_ERRO) is not None)

import app.ui.fechamento as fechamento_mod
_generate_report_original = fechamento_mod.rm.generate_report


def _generate_report_falha(*args, **kwargs):
    raise RuntimeError("falha simulada de geração de PDF (ex.: WeasyPrint)")


fechamento_mod.rm.generate_report = _generate_report_falha
try:
    erro_capturado = None
    try:
        _aprovar_unidade(UID, MES_ERRO, u_erro, 20000.0, None, _custos_extras_zerados(MES_ERRO))
    except ErroPosAprovacao as e:
        erro_capturado = e

    checar("1d. ErroPosAprovacao foi levantada (erro reportado, não mascarado)",
           erro_capturado is not None)
    status_db, dados_db = _lancamento_db(UID, MES_ERRO)
    checar("1d. o lançamento FOI salvo como aprovado, apesar da falha na geração do PDF",
           status_db == "aprovado" and dados_db["faturamento"] == 20000.0)
    checar("1d. o rascunho da competência NÃO sobrevive à aprovação (mesmo com falha posterior)",
           carregar_rascunho_unidade(UID, MES_ERRO) is None)
    unit_run_erro = rm.get_unit_run(MES_ERRO, UID)
    checar("1d. o status de workflow registra o erro (não fica silenciosamente 'aprovado')",
           unit_run_erro["status"] == "erro")
finally:
    fechamento_mod.rm.generate_report = _generate_report_original
print()


# ═══════════════════════════════════════════════════════════════════════
# 2. FIERGS / editores dinâmicos — revisão em duas etapas
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Editores dinâmicos — revisão em duas etapas persiste exatamente o snapshot")
print("=" * 70)
import pandas as pd
from app.models import seed_parametros_from_yaml, salvar_parametros, get_parametros_vigentes
from app.engine import load_units
from app.rubricas import normalizar_rubricas, para_persistencia
from app.calculadora_schema import SCHEMAS_POR_TIPO
from app.ui.administracao import (
    _linhas_para_dataframe, _dataframe_para_itens, _fingerprint,
    _renderizar_revisao_alteracoes, _formatar_item_composto,
)

UID_FIERGS = "fiergs"
seed_parametros_from_yaml(UID_FIERGS, load_units()[UID_FIERGS])

_colunas_rubrica = [
    {"chave": "nome", "label": "Rubrica", "tipo_dado": "texto", "obrigatorio": True},
    {"chave": "valor", "label": "Valor", "tipo_dado": "moeda", "obrigatorio": True, "minimo": 0.0},
]
_campo_id = "id"
_campo_custos_variaveis = next(
    c for c in SCHEMAS_POR_TIPO["COM_FAIXAS"]["campos"] if c["chave"] == "custos_variaveis"
)

valor_inicial = get_parametros_vigentes(UID_FIERGS, "2026-09").get("custos_variaveis")
valor_normalizado = para_persistencia(normalizar_rubricas(valor_inicial))

# Simula exatamente o que uma célula RECÉM CONFIRMADA (Enter/Tab/clique
# fora) devolveria ao data_editor -- 2 linhas novas, com id em branco.
df = _linhas_para_dataframe(valor_normalizado, _colunas_rubrica, _campo_id)
novas = pd.DataFrame([
    {"Rubrica": "Nova Despesa 1", "Valor": 100.0, "id": None},
    {"Rubrica": "Nova Despesa 2", "Valor": 200.0, "id": None},
])
df_editado = pd.concat([df, novas], ignore_index=True)
itens_editados = _dataframe_para_itens(df_editado, _colunas_rubrica, _campo_id)

# --- "Revisar alterações": o snapshot é isto -- exatamente o dataframe já
# consolidado, nunca relido depois.
snapshot = {"valores_editados": {"custos_variaveis": itens_editados}, "vigente_a_partir": "2026-09"}

checar("2a. snapshot da revisão inclui as 2 rubricas novas com nome e valor",
       {i["nome"]: i["valor"] for i in snapshot["valores_editados"]["custos_variaveis"]}
       .get("Nova Despesa 1") == 100.0)

texto_revisao = _formatar_item_composto(_campo_custos_variaveis, itens_editados[-2])
checar("2a. formatação da revisão mostra nome e valor legíveis (não o dict Python cru)",
       "Nova Despesa 1" in texto_revisao and "R$ 100,00" in texto_revisao)

# --- "Confirmar e salvar": persiste EXATAMENTE o snapshot, sem reler nada.
salvar_parametros(UID_FIERGS, snapshot["vigente_a_partir"], snapshot["valores_editados"], alterado_por="administracao")
valor_apos_confirmar = get_parametros_vigentes(UID_FIERGS, "2026-09").get("custos_variaveis")
ids_persistidos = {i["id"] for i in valor_apos_confirmar}
checar("2b. depois de 'Confirmar e salvar', as 2 rubricas novas estão em parametros_vigentes",
       {"nova_despesa_1", "nova_despesa_2"} <= ids_persistidos)
checar("2b. a rubrica original (sistema_perto) continua presente — nada foi substituído às cegas",
       "sistema_perto" in ids_persistidos)

# --- fingerprint continua funcionando (papel que ainda tem: key muda quando
# o valor persistido muda, evitando o widget reconciliar contra estado
# antigo após um reload) -- não é mais tratado como a correção da perda de
# edição ativa, só verificado que continua correto.
fp_antes = _fingerprint(valor_inicial)
fp_depois = _fingerprint(valor_apos_confirmar)
checar("2c. fingerprint muda quando o valor persistido muda (papel que ainda cumpre)",
       fp_antes != fp_depois)

# --- tipos 100% escalares não ganham a etapa extra de revisão.
for tipo in ("PERCENTUAL_SIMPLES", "COM_ALIQUOTA"):
    campos_tipo = SCHEMAS_POR_TIPO[tipo]["campos"]
    tem_dinamico = any(c.get("natureza") in ("lista_estruturada", "mapa_rubricas") for c in campos_tipo)
    checar(f"2d. {tipo} não tem campo dinâmico — mantém o salvamento direto (sem revisão)",
           not tem_dinamico)
for tipo in ("COM_ALIQUOTA_CUMUL", "COM_FAIXAS", "RESULTADO_SPLIT", "COM_ALIQUOTA_REPASSE_DUPLO"):
    campos_tipo = SCHEMAS_POR_TIPO[tipo]["campos"]
    tem_dinamico = any(c.get("natureza") in ("lista_estruturada", "mapa_rubricas") for c in campos_tipo)
    checar(f"2d. {tipo} tem campo dinâmico — usa o fluxo de revisão em duas etapas",
           tem_dinamico)
print()


# ═══════════════════════════════════════════════════════════════════════
# 3. EKOS / OKA — pode_ativar_unidade sem pendências
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. EKOS / OKA — pode_ativar_unidade")
print("=" * 70)
from app.models import pode_ativar_unidade
from datetime import date

for uid in ("ekos", "oka"):
    seed_parametros_from_yaml(uid, load_units()[uid])

hoje = date.today().strftime("%Y-%m")
for uid in ("ekos", "oka"):
    pendencias_hoje = pode_ativar_unidade(uid, hoje)
    pendencias_inicio = pode_ativar_unidade(uid, "2026-07")
    checar(f"3. {uid}: pode_ativar_unidade não aponta pendências em {hoje} "
           f"(config já completa — Taxa de Cobrança já persistida)",
           pendencias_hoje == [])
    checar(f"3. {uid}: pode_ativar_unidade não aponta pendências em 2026-07 (início da unidade)",
           pendencias_inicio == [])
    if pendencias_hoje:
        print(f"    pendências de {uid} em {hoje}: {pendencias_hoje}")

with get_db() as conn:
    ativo_ekos = conn.execute("SELECT ativo FROM unidades WHERE id='ekos'").fetchone()["ativo"]
    ativo_oka = conn.execute("SELECT ativo FROM unidades WHERE id='oka'").fetchone()["ativo"]
checar("3. EKOS continua ativo=0 — este teste NUNCA ativa a unidade pelo banco", ativo_ekos == 0)
checar("3. OKA continua ativo=0 — este teste NUNCA ativa a unidade pelo banco", ativo_oka == 0)
print()


# ═══════════════════════════════════════════════════════════════════════
# 4. Golden test — reprocessamento de agosto/2026 da Viva Trindade
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Golden test — agosto/2026 partindo da saída correta de julho")
print("=" * 70)
from app.calculators.cumulativo import calcular_com_aliquota_cumul

SAIDA_JULHO_CORRETA = -157142.75
cfg_agosto = {
    "id": "viva_trindade", "aliquota_imposto": 0.0, "percentual_aluguel": 0.85,
    "ponto_equilibrio": 0.0,
    # Resultado oficial de agosto já vem pronto (-1525.24, Outras Despesas já
    # incorporada) -- usa faturamento=resultado e as demais deduções zeradas
    # para reproduzir exatamente esse Resultado sem precisar dos componentes
    # completos de agosto (que não fazem parte deste golden test específico).
    "custos_variaveis": {"investimentos": 0.0},
}
r_golden = calcular_com_aliquota_cumul(
    cfg_agosto, "2026-08", faturamento=-1525.24,
    saldo_override=SAIDA_JULHO_CORRETA,
)
checar("4. golden: Resultado de agosto = -1525.24 (dado oficial, Outras Despesas já incorporada)",
       r_golden.resultado == -1525.24)
checar("4. golden: Investimentos = 0 (dado oficial)",
       "investimentos" not in r_golden.extras)
checar("4. golden: Repasse = 0.0 (resultado com prejuízo continua negativo)",
       r_golden.aluguel_calculado == 0.0)
checar("4. golden: Prejuízo Acumulado de saída de agosto = -158667.99",
       r_golden.prejuizo_acumulado_saida == -158667.99)

# A propagação "agosto herda a saída aprovada de julho pelo caminho
# oficial" já está coberta ponta a ponta na seção 1b acima (mesmo
# mecanismo, _aprovar_unidade) — este golden test isola só a fórmula
# financeira com os números oficiais exatos do reparo pendente.
print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 3) PASSARAM ===")
