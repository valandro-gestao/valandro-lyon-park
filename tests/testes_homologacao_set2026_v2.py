"""
Cobertura permanente da 2ª rodada de homologação de set/2026 (Débora).
Dom Pedro e Viva Trindade/Outras Despesas já homologados na rodada
anterior — preservados, não tocados aqui. Três problemas nesta rodada:

  1. Viva Trindade — Investimentos vazava de um mês para os seguintes
     (aparecia como default em meses onde a operadora nunca digitou
     nada, "somando no prejuízo" indevidamente). Causa raiz: toda
     aprovação de Fechamento varria o valor digitado de volta para
     `parametros_vigentes` como uma vigência NOVA E ABERTA (sem fim) —
     correto para um parâmetro contratual (condomínio, percentual de
     aluguel), errado para um evento financeiro de UM mês específico.
     Corrigido em app.ui.fechamento: `_RUBRICAS_MENSAIS_NAO_VIGENCIA`
     exclui investimentos/outras_despesas do auto-save de vigência; o
     default do widget passa a vir do que já foi lançado NAQUELA
     competência (lancamentos.resultado_json.extras), nunca do vigente.

  2. EKOS/OKA (COM_FAIXAS) x Terreno OKA (COM_ALIQUOTA_REPASSE_DUPLO) —
     investigação exaustiva (schema, calculator, persistência via
     salvar_parametros, e simulação completa da tela de Administração via
     streamlit.testing.v1.AppTest) não encontrou NENHUMA diferença de
     comportamento entre os três: Taxa de Cobrança configura, persiste e
     calcula identicamente nos três, com ou sem YAML de origem. Nenhuma
     correção de código foi feita aqui — os testes abaixo são de
     REGRESSÃO, confirmando que o mecanismo (já correto) continua correto.

  3. FIERGS — linhas novas de despesa (custos_variaveis, mapa_rubricas)
     "desapareciam" depois de salvar duas vezes. Causa raiz: as keys dos
     widgets `st.data_editor`/checkbox/number_input do editor de listas
     compostas eram estáticas (só unidade+competência+campo) — depois de
     Salvar, salvar_parametros grava a lista nova e st.rerun() recarrega a
     tela com a MESMA key de antes, e o Streamlit tenta reconciliar o `df`
     recém-carregado (já com ids gerados) contra o estado interno ainda
     pendente do widget da rodada anterior (linhas novas com id em
     branco) — comportamento documentado do próprio Streamlit para
     `num_rows="dynamic"` quando a key não muda mas o dado muda por baixo.
     Corrigido: as keys agora incluem um fingerprint do valor vigente
     (`_fingerprint`) — muda sempre que o valor persistido muda, forçando
     o widget a nascer do zero a cada mudança real de dado.

  4. Teste transversal: Administração -> parametros_vigentes ->
     competência -> fechamento, cobrindo um escalar percentual, uma lista
     estruturada (faixas), um mapa_rubricas e uma rubrica mensal
     (investimentos) — salva, recarrega, resolve competências diferentes.

Execução: python3 tests/testes_homologacao_set2026_v2.py
"""
import hashlib
import json
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v2_")
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
# 1. Viva Trindade — Investimentos não vaza entre meses
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. Viva Trindade — Investimentos: propriedade de não-vazamento")
print("=" * 70)
from app.models import get_db, salvar_parametros, salvar_lancamento
from app.engine import get_unit_com_params, calcular
from app.ui.fechamento import (
    _coletar_params_usados, _e_rubrica_mensal_nao_vigente, _valor_ja_lancado,
    _RUBRICAS_MENSAIS_NAO_VIGENCIA,
)
from app.rubricas import normalizar_rubricas

UID_VIVA = "viva_trindade"


def _aprovar_viva(mes_ref, investimentos_digitado):
    u_cfg = get_unit_com_params(UID_VIVA, mes_ref)
    custos_extras = {}
    for item in normalizar_rubricas(u_cfg.get("custos_variaveis")):
        custos_extras[item.id] = investimentos_digitado if item.id == "investimentos" else item.valor
    r = calcular(UID_VIVA, mes_ref, 48674.03, custos_extras=custos_extras)
    r.status = "aprovado"
    salvar_lancamento(r)
    params = _coletar_params_usados(UID_VIVA, u_cfg, None, custos_extras)
    salvar_parametros(UID_VIVA, mes_ref, params, alterado_por="aprovacao")
    return r


def _default_widget_investimentos(mes_ref):
    u_cfg = get_unit_com_params(UID_VIVA, mes_ref)
    tc = u_cfg.get("tipo_calculo", "")
    if _e_rubrica_mensal_nao_vigente(tc, "investimentos"):
        v = _valor_ja_lancado(UID_VIVA, mes_ref, "investimentos")
        return 0.0 if v is None else v
    item = next(i for i in normalizar_rubricas(u_cfg.get("custos_variaveis")) if i.id == "investimentos")
    return item.valor


checar("investimentos/outras_despesas são reconhecidos como rubrica mensal não-vigência",
       _RUBRICAS_MENSAIS_NAO_VIGENCIA == frozenset({"investimentos", "outras_despesas"}))
checar("fundo_recomposicao (W Tower) NÃO está na lista — comportamento homologado intocado",
       "fundo_recomposicao" not in _RUBRICAS_MENSAIS_NAO_VIGENCIA)

with get_db() as conn:
    vigencia_inicial = conn.execute(
        "SELECT valor, competencia_inicio, competencia_fim FROM parametros_vigentes "
        "WHERE unidade_id=? AND parametro='custos_variaveis.investimentos'", (UID_VIVA,)
    ).fetchall()
checar("estado inicial: uma única vigência de investimentos (seed 2020-01, 0.0, aberta)",
       len(vigencia_inicial) == 1 and vigencia_inicial[0]["valor"] == "0.0"
       and vigencia_inicial[0]["competencia_fim"] is None)

print("--- sequência: julho (investimentos=5000) -> agosto (default?) -> agosto corrigido (0) -> "
      "volta julho -> reprocessa julho -> volta agosto ---")
_aprovar_viva("2026-07", 5000.0)
default_agosto_antes = _default_widget_investimentos("2026-08")
checar("agosto, antes de qualquer edição, NÃO herda o valor digitado em julho (default=0.0)",
       default_agosto_antes == 0.0)

_aprovar_viva("2026-08", 0.0)
default_julho_depois = _default_widget_investimentos("2026-07")
checar("julho, ao reabrir, mostra o que foi REALMENTE lançado naquele mês (5000.0), "
       "não o vigente (que não é mais tocado por esta correção)",
       default_julho_depois == 5000.0)

_aprovar_viva("2026-07", default_julho_depois)
default_agosto_final = _default_widget_investimentos("2026-08")
checar("reprocessar julho NÃO apaga/move o valor de agosto (continua 0.0)",
       default_agosto_final == 0.0)

with get_db() as conn:
    vigencia_final = conn.execute(
        "SELECT valor, competencia_inicio, competencia_fim FROM parametros_vigentes "
        "WHERE unidade_id=? AND parametro='custos_variaveis.investimentos'", (UID_VIVA,)
    ).fetchall()
checar("parametros_vigentes de investimentos NUNCA foi alterado por nenhuma aprovação "
       "(continua a única vigência-seed, 2020-01, 0.0, aberta)",
       len(vigencia_final) == 1 and vigencia_final[0]["valor"] == "0.0"
       and vigencia_final[0]["competencia_fim"] is None)

default_setembro = _default_widget_investimentos("2026-09")
checar("um mês totalmente novo (setembro, nunca tocado) mostra 0.0 — nunca herda de outro mês",
       default_setembro == 0.0)

# O valor realmente usado continua auditável no lançamento congelado.
with get_db() as conn:
    lanc_julho = conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia='2026-07'", (UID_VIVA,)
    ).fetchone()
extras_julho = json.loads(lanc_julho["resultado_json"]).get("extras", {})
checar("lancamentos de julho preserva investimentos=5000.0 em extras (auditoria)",
       extras_julho.get("investimentos") == 5000.0)

# ─── 1b. Sequência EXATA pedida pela operadora, isolada num par de meses
#     próprio (2027-01/2027-02) para não depender do estado acumulado acima:
#     julho investimentos=5000 -> agosto investimentos=0 -> reabrir julho
#     -> julho continua 5000 -> reabrir agosto -> agosto continua 0.
print("--- 1b. sequência exata: mês A investimentos=5000 -> mês B investimentos=0 -> "
      "reabrir A (continua 5000) -> reabrir B (continua 0) ---")
_MES_A, _MES_B = "2027-01", "2027-02"
_aprovar_viva(_MES_A, 5000.0)
_aprovar_viva(_MES_B, 0.0)
checar("1b. reabrir mês A (julho): investimentos continua 5000 (valor próprio da competência)",
       _default_widget_investimentos(_MES_A) == 5000.0)
checar("1b. reabrir mês B (agosto): investimentos continua 0 (não foi movido/apagado por A)",
       _default_widget_investimentos(_MES_B) == 0.0)
# Reabrir de novo, em qualquer ordem, continua estável (idempotente na leitura).
checar("1b. reabrir mês A de novo (ordem invertida): continua 5000",
       _default_widget_investimentos(_MES_A) == 5000.0)
checar("1b. reabrir mês B de novo: continua 0",
       _default_widget_investimentos(_MES_B) == 0.0)

# ─── 1c. Equivalente mínimo para Outras Despesas: mês C outras_despesas=2400
#     -> mês D (novo, sem lançamento próprio) abre com 0.
print("--- 1c. equivalente para Outras Despesas: mês C=2400 -> mês D novo abre com 0 ---")


def _aprovar_viva_outras_despesas(mes_ref, outras_despesas_digitado):
    u_cfg = get_unit_com_params(UID_VIVA, mes_ref)
    custos_extras = {}
    for item in normalizar_rubricas(u_cfg.get("custos_variaveis")):
        custos_extras[item.id] = outras_despesas_digitado if item.id == "outras_despesas" else item.valor
    r = calcular(UID_VIVA, mes_ref, 48674.03, custos_extras=custos_extras)
    r.status = "aprovado"
    salvar_lancamento(r)
    params = _coletar_params_usados(UID_VIVA, u_cfg, None, custos_extras)
    salvar_parametros(UID_VIVA, mes_ref, params, alterado_por="aprovacao")


def _default_widget_outras_despesas(mes_ref):
    u_cfg = get_unit_com_params(UID_VIVA, mes_ref)
    tc = u_cfg.get("tipo_calculo", "")
    if _e_rubrica_mensal_nao_vigente(tc, "outras_despesas"):
        v = _valor_ja_lancado(UID_VIVA, mes_ref, "outras_despesas")
        return 0.0 if v is None else v
    item = next(i for i in normalizar_rubricas(u_cfg.get("custos_variaveis")) if i.id == "outras_despesas")
    return item.valor


_MES_C, _MES_D = "2027-03", "2027-04"
_aprovar_viva_outras_despesas(_MES_C, 2400.0)
checar("1c. mês C (agosto): outras_despesas persiste 2400.0 no próprio lançamento",
       _default_widget_outras_despesas(_MES_C) == 2400.0)
checar("1c. mês D (setembro, sem lançamento próprio ainda): abre com 0 — não herda de C",
       _default_widget_outras_despesas(_MES_D) == 0.0)
with get_db() as conn:
    tem_lancamento_d = conn.execute(
        "SELECT 1 FROM lancamentos WHERE unidade_id=? AND mes_referencia=?", (UID_VIVA, _MES_D)
    ).fetchone()
checar("1c. mês D de fato não tem lançamento próprio ainda (pré-condição do teste)",
       tem_lancamento_d is None)

# Se o mês D JÁ tivesse lançamento próprio (com outras_despesas=0, explícito),
# reabri-lo deveria mostrar esse valor próprio — não é diferente de "abrir
# com 0": o ponto é que o 0 vem do PRÓPRIO lançamento/ausência dele, nunca
# herdado de C. Confirma explicitamente aprovando D com um valor diferente
# de zero e verificando que ISSO é o que volta ao reabrir (não 2400 nem 0
# por acaso) — fecha o caso "setembro já possuir lançamento próprio".
_aprovar_viva_outras_despesas(_MES_D, 900.0)
checar("1c. se mês D passar a ter lançamento próprio (900.0), reabri-lo mostra 900.0 "
       "(o próprio valor, não o de C nem um 0 arbitrário)",
       _default_widget_outras_despesas(_MES_D) == 900.0)
checar("1c. mês C permanece intocado (2400.0) depois de D ser aprovado",
       _default_widget_outras_despesas(_MES_C) == 2400.0)

# ─── 1d. Reabrir uma competência já lançada recupera seu PRÓPRIO valor —
#     confirmação explícita e conjunta para os dois campos.
print("--- 1d. reabrir competência já lançada recupera o próprio valor (Investimentos e Outras Despesas) ---")
checar("1d. Investimentos — reabrir mês A recupera 5000.0 (o que A realmente lançou)",
       _default_widget_investimentos(_MES_A) == 5000.0)
checar("1d. Outras Despesas — reabrir mês C recupera 2400.0 (o que C realmente lançou)",
       _default_widget_outras_despesas(_MES_C) == 2400.0)
with get_db() as conn:
    extras_a = json.loads(conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
        (UID_VIVA, _MES_A),
    ).fetchone()["resultado_json"]).get("extras", {})
    extras_c = json.loads(conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
        (UID_VIVA, _MES_C),
    ).fetchone()["resultado_json"]).get("extras", {})
checar("1d. o valor recuperado ao reabrir vem exatamente de extras.investimentos do lançamento (5000.0)",
       extras_a.get("investimentos") == 5000.0)
checar("1d. o valor recuperado ao reabrir vem exatamente de extras.outras_despesas do lançamento (2400.0)",
       extras_c.get("outras_despesas") == 2400.0)
print()


# ═══════════════════════════════════════════════════════════════════════
# 2. EKOS / OKA / Terreno OKA — Taxa de Cobrança (regressão, mecanismo já correto)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. EKOS/OKA/Terreno OKA — Taxa de Cobrança (regressão)")
print("=" * 70)
from app.models import seed_parametros_from_yaml
from app.engine import load_units
from app.calculadora_schema import SCHEMAS_POR_TIPO
from app.rubricas import para_persistencia

for uid in ("ekos", "oka", "terreno_oka"):
    seed_parametros_from_yaml(uid, load_units()[uid])
    u_cfg = get_unit_com_params(uid, "2026-08")
    tc = u_cfg["tipo_calculo"]
    campos = SCHEMAS_POR_TIPO[tc]["campos"]
    valores_editados = {}
    for campo in campos:
        chave, natureza = campo["chave"], campo.get("natureza", "escalar")
        if chave in ("tem_base_taxa_cobranca", "taxa_cobranca"):
            valores_editados[chave] = True if chave == "tem_base_taxa_cobranca" else 0.05
            continue
        if natureza == "mapa_rubricas":
            valores_editados[chave] = para_persistencia(normalizar_rubricas(u_cfg.get(chave)))
        elif natureza == "lista_estruturada":
            valores_editados[chave] = u_cfg.get(chave) or []
        else:
            partes = chave.split(".")
            v = u_cfg
            for p in partes:
                v = v.get(p) if isinstance(v, dict) else None
            valores_editados[chave] = v
    salvar_parametros(uid, "2026-08", valores_editados, alterado_por="administracao")

    u_depois = get_unit_com_params(uid, "2026-08")
    checar(f"{uid}: tem_base_taxa_cobranca persiste True após salvar via Administração",
           u_depois.get("tem_base_taxa_cobranca") is True)
    checar(f"{uid}: taxa_cobranca persiste 0.05 após salvar via Administração",
           u_depois.get("taxa_cobranca") == 0.05)

    r = calcular(uid, "2026-08", 50000.0, custos_extras={"base_calculo_taxa_cobranca": 50000.0})
    checar(f"{uid}: cálculo aplica a taxa de cobrança (2500.0 = 5% de 50000)",
           r.extras.get("taxa_cobranca_valor") == 2500.0)
print()


# ═══════════════════════════════════════════════════════════════════════
# 3. FIERGS — rubricas novas não desaparecem (key sensível ao conteúdo)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. FIERGS — rubricas novas em custos_variaveis persistem entre saves")
print("=" * 70)
import pandas as pd
from app.ui.administracao import (
    _linhas_para_dataframe, _dataframe_para_itens, _fingerprint,
)
from app.models import get_parametros_vigentes

UID_FIERGS = "fiergs"
seed_parametros_from_yaml(UID_FIERGS, load_units()[UID_FIERGS])

_colunas_rubrica = [
    {"chave": "nome", "label": "Rubrica", "tipo_dado": "texto", "obrigatorio": True},
    {"chave": "valor", "label": "Valor", "tipo_dado": "moeda", "obrigatorio": True, "minimo": 0.0},
]
_campo_id = "id"


def _cv_atual(mes_ref="2026-09"):
    return get_parametros_vigentes(UID_FIERGS, mes_ref).get("custos_variaveis")


valor_inicial = _cv_atual()
fp_inicial = _fingerprint(valor_inicial)
checar("estado inicial de custos_variaveis vem do YAML (sistema_perto)",
       normalizar_rubricas(valor_inicial)[0].id == "sistema_perto")

# Simula o operador adicionando 2 linhas novas na grade (mesmo shape que o
# data_editor devolveria — 2 linhas com id em branco).
valor_normalizado = para_persistencia(normalizar_rubricas(valor_inicial))
df = _linhas_para_dataframe(valor_normalizado, _colunas_rubrica, _campo_id)
novas = pd.DataFrame([
    {"Rubrica": "Nova Despesa 1", "Valor": 100.0, "id": None},
    {"Rubrica": "Nova Despesa 2", "Valor": 200.0, "id": None},
])
df_com_novas = pd.concat([df, novas], ignore_index=True)
itens_1a_rodada = _dataframe_para_itens(df_com_novas, _colunas_rubrica, _campo_id)
checar("1ª rodada: as 2 linhas novas ganham id gerado a partir do nome",
       {"nova_despesa_1", "nova_despesa_2"} <= {i["id"] for i in itens_1a_rodada})

salvar_parametros(UID_FIERGS, "2026-09", {"custos_variaveis": itens_1a_rodada}, alterado_por="administracao")

valor_apos_1a = _cv_atual()
fp_apos_1a = _fingerprint(valor_apos_1a)
checar("1º save: as 3 rubricas (1 original + 2 novas) persistem em parametros_vigentes",
       len(normalizar_rubricas(valor_apos_1a)) == 3)
checar("fingerprint da key MUDA depois do 1º save (força o data_editor a nascer do zero, "
       "sem herdar estado pendente da rodada anterior — a causa raiz do bug)",
       fp_inicial != fp_apos_1a)

# "Recarrega a Administração" — normaliza de novo o valor já persistido, tal
# como o editor faz a cada rerender.
valor_normalizado_2 = para_persistencia(normalizar_rubricas(valor_apos_1a))
checar("depois de recarregar, as 3 rubricas continuam com os MESMOS ids (nenhum foi trocado)",
       {i["id"] for i in valor_normalizado_2} == {"sistema_perto", "nova_despesa_1", "nova_despesa_2"})

# 2º save — reabre e salva de novo, SEM nenhuma edição adicional (o cenário
# exato relatado: "salvei duas vezes").
df_2a_rodada = _linhas_para_dataframe(valor_normalizado_2, _colunas_rubrica, _campo_id)
itens_2a_rodada = _dataframe_para_itens(df_2a_rodada, _colunas_rubrica, _campo_id)
if itens_2a_rodada != valor_normalizado_2:
    salvar_parametros(UID_FIERGS, "2026-09", {"custos_variaveis": itens_2a_rodada}, alterado_por="administracao")

valor_apos_2a = _cv_atual()
checar("2º save (sem edição): as 3 rubricas continuam TODAS presentes — não desaparecem",
       len(normalizar_rubricas(valor_apos_2a)) == 3)
checar("2º save: valores preservados corretamente (Nova Despesa 1 = 100.0, Nova Despesa 2 = 200.0)",
       {i.nome: i.valor for i in normalizar_rubricas(valor_apos_2a)}.get("Nova Despesa 1") == 100.0
       and {i.nome: i.valor for i in normalizar_rubricas(valor_apos_2a)}.get("Nova Despesa 2") == 200.0)

# Aparece corretamente no Fechamento (mesmo mecanismo de renderização).
u_fiergs = get_unit_com_params(UID_FIERGS, "2026-09")
ids_fechamento = {i.id for i in normalizar_rubricas(u_fiergs.get("custos_variaveis"))}
checar("as 2 rubricas novas aparecem no Fechamento (normalizar_rubricas via get_unit_com_params)",
       {"nova_despesa_1", "nova_despesa_2"} <= ids_fechamento)

# Editar/remover também se comporta corretamente (remove 1, edita outra).
itens_editados_remocao = [i for i in itens_2a_rodada if i["id"] != "nova_despesa_1"]
for i in itens_editados_remocao:
    if i["id"] == "nova_despesa_2":
        i["valor"] = 250.0
salvar_parametros(UID_FIERGS, "2026-10", {"custos_variaveis": itens_editados_remocao}, alterado_por="administracao")
valor_out = _cv_atual("2026-10")
ids_out = {i.id for i in normalizar_rubricas(valor_out)}
checar("remover uma rubrica (nova_despesa_1) e editar outra funciona e persiste (a partir de 2026-10)",
       "nova_despesa_1" not in ids_out and "nova_despesa_2" in ids_out)
checar("valor editado (Nova Despesa 2 = 250.0) persiste",
       next(i.valor for i in normalizar_rubricas(valor_out) if i.id == "nova_despesa_2") == 250.0)
# Vigência temporal: setembro continua com as 3 rubricas originais (a mudança só vale a partir de outubro).
valor_setembro_ainda = _cv_atual("2026-09")
checar("vigência temporal correta: setembro continua com as 3 rubricas (mudança só a partir de outubro)",
       len(normalizar_rubricas(valor_setembro_ainda)) == 3)
print()


# ═══════════════════════════════════════════════════════════════════════
# 4. Teste transversal — Administração -> parametros_vigentes -> competência -> fechamento
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Teste transversal de integração")
print("=" * 70)
UID_T = "viva_trindade"  # COM_ALIQUOTA_CUMUL: tem escalar percentual, mapa_rubricas
                          # (custos_mensais) e rubrica mensal (investimentos).
                          # 'faixas' (lista_estruturada) é testado via um
                          # segundo tipo (COM_FAIXAS) no mesmo bloco.

# 4a. Escalar percentual (percentual_aluguel) — muda a partir de nov/2026.
seed_parametros_from_yaml(UID_T, load_units()[UID_T])
salvar_parametros(UID_T, "2026-11", {"percentual_aluguel": 0.90}, alterado_por="administracao")
u_out = get_unit_com_params(UID_T, "2026-10")
u_nov = get_unit_com_params(UID_T, "2026-11")
checar("4a. escalar percentual: outubro NÃO mudou (vigência anterior preservada)",
       u_out.get("percentual_aluguel") != 0.90)
checar("4a. escalar percentual: novembro reflete o novo valor (0.90)",
       u_nov.get("percentual_aluguel") == 0.90)

# 4b. mapa_rubricas (custos_mensais) — adiciona uma rubrica nova a partir de nov/2026.
cm_atual = para_persistencia(normalizar_rubricas(u_out.get("custos_mensais")))
cm_novo = cm_atual + [{"id": None, "nome": "Nova Rubrica Mensal", "valor": 42.0}]
df_cm = _linhas_para_dataframe(cm_atual, _colunas_rubrica, _campo_id)
df_cm_com_nova = pd.concat([df_cm, pd.DataFrame([{"Rubrica": "Nova Rubrica Mensal", "Valor": 42.0, "id": None}])], ignore_index=True)
itens_cm = _dataframe_para_itens(df_cm_com_nova, _colunas_rubrica, _campo_id)
salvar_parametros(UID_T, "2026-11", {"custos_mensais": itens_cm}, alterado_por="administracao")
u_nov2 = get_unit_com_params(UID_T, "2026-11")
ids_cm_nov = {i.id for i in normalizar_rubricas(u_nov2.get("custos_mensais"))}
u_out2 = get_unit_com_params(UID_T, "2026-10")
ids_cm_out = {i.id for i in normalizar_rubricas(u_out2.get("custos_mensais"))}
checar("4b. mapa_rubricas: nova rubrica mensal aparece a partir de novembro",
       "nova_rubrica_mensal" in ids_cm_nov)
checar("4b. mapa_rubricas: outubro continua sem a rubrica nova (vigência temporal correta)",
       "nova_rubrica_mensal" not in ids_cm_out)

# 4c. lista_estruturada (faixas, unidade COM_FAIXAS) — altera a partir de dez/2026.
UID_FAIXAS = "ekos"
seed_parametros_from_yaml(UID_FAIXAS, load_units()[UID_FAIXAS])
salvar_parametros(UID_FAIXAS, "2026-12", {
    "faixas": [{"ate": 10000.0, "percentual": 0.5}, {"ate": None, "percentual": 0.9}],
}, alterado_por="administracao")
u_nov_faixas = get_unit_com_params(UID_FAIXAS, "2026-11")
u_dez_faixas = get_unit_com_params(UID_FAIXAS, "2026-12")
checar("4c. lista_estruturada: novembro continua com a faixa original (1 faixa, sem limite, 85%)",
       u_nov_faixas.get("faixas") == [{"ate": None, "percentual": 0.85}])
checar("4c. lista_estruturada: dezembro reflete as novas faixas (2 faixas)",
       len(u_dez_faixas.get("faixas")) == 2 and u_dez_faixas["faixas"][0]["percentual"] == 0.5)

# 4d. rubrica mensal (Investimentos) — mesma unidade da seção 1: confirma
# que abrir/recarregar/resolver competências diferentes continua isolado.
_aprovar_viva("2026-11", 777.0)
checar("4d. rubrica mensal: novembro mostra o valor lançado (777.0) ao reabrir",
       _default_widget_investimentos("2026-11") == 777.0)
checar("4d. rubrica mensal: dezembro (não tocado) continua em 0.0 — sem vazamento",
       _default_widget_investimentos("2026-12") == 0.0)
with get_db() as conn:
    vig_investimentos_final = conn.execute(
        "SELECT COUNT(*) c FROM parametros_vigentes WHERE unidade_id=? AND parametro='custos_variaveis.investimentos'",
        (UID_T,),
    ).fetchone()["c"]
checar("4d. rubrica mensal: parametros_vigentes de investimentos continua com 1 única linha "
       "(seed) — o teste transversal inteiro não criou vigência nenhuma para ela",
       vig_investimentos_final == 1)

print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 2) PASSARAM ===")
