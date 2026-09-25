"""
Cobertura permanente da integração Aucon/eCloud V1 (busca automática de
faturamento) — homologação de agosto/2026.

Regra validada em produção real (9 unidades reconciliadas ao centavo:
Dom Pedro, Axis, Vasco da Gama, Viva Trindade, Anitta Mall, FK, IN 1183,
MW Tristeza, W Tower Caxias): soma dos seis métodos que a Aucon indicou
para compor faturamento, no mês completo, excluindo MeioPagamento=
"CANCELADO" — sem filtro de DataCompetencia/Competencia. A integração
preenche exclusivamente o campo-base `Faturamento (R$)`; nenhum campo
específico de calculadora (ex. Faturamento Carregadores) é tocado.

Nenhuma chamada real à API Aucon é feita neste arquivo — todos os testes
usam `app.integrations.aucon_client` com a camada HTTP (`_buscar_endpoint`)
ou a função de alto nível (`buscar_faturamento_aucon`) substituídas por
funções fake, controladas pelo próprio teste.

Cobre explicitamente:
  1. importa X -> aprova X -> resultado.extras["origem_faturamento"] existe
     e contém a metadata correta.
  2. importa X -> operador altera para Y -> aprova Y -> NÃO existe marca
     falsa de origem Aucon.
  3. atualização Aucon preserva todos os demais campos do rascunho (nos
     dois sentidos: import não apaga campo pré-existente; abrir a tela da
     unidade depois de um import não apaga _aucon_meta).
  4. falha em qualquer um dos seis endpoints não altera o faturamento
     existente (golden real da Viva Trindade + falha isolada).
  5. lote continua processando as demais unidades quando uma unidade falha.
  6. unidade sem aucon_codigo_filial permanece totalmente intocada.
  7. lote e atualização individual usam a mesma regra/service
     (_importar_faturamento_aucon).
  8. CANCELADO é excluído corretamente (golden real de Viva Trindade,
     agosto/2026: bruto 48.802,03 - cancelados 128,00 = 48.674,03).
  9. regressão dos comportamentos atuais de draft/DU (sugestão do mês
     anterior, edição deliberada, zero) e de "nunca registrar origem Aucon
     falsa quando nunca houve importação".

Execução: python3 tests/testes_homologacao_aucon_v1.py
"""
import os, sys, json, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_aucon_v1_")
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


import streamlit as st
from app.models import (
    criar_unidade, salvar_parametros, definir_aucon_codigo_filial,
    carregar_rascunho_unidade, salvar_rascunho_unidade, get_lancamentos_mes,
    get_db,
)
from app.engine import load_units, get_unit
import app.ui.fechamento as fech
from app.integrations import aucon_client
from app.integrations.aucon_client import AuconResultado, AuconAuthError, AuconRespostaIncompletaError

# Guardado ANTES de qualquer monkeypatch — usado para restaurar a função
# real de alto nível quando o teste precisa dela de verdade (golden real
# de Viva Trindade, seção 4/8), já que outras seções substituem
# aucon_client.buscar_faturamento_aucon por funções fake.
_buscar_faturamento_aucon_original = aucon_client.buscar_faturamento_aucon


def _reset_estado_unidade(uid: str, mes_ref: str):
    """Limpa session_state e rascunho antes de cada cenário — testes
    isolados uns dos outros."""
    for k in list(st.session_state.keys()):
        if k == f"fat_{uid}" or k.startswith(f"_aucon_"):
            del st.session_state[k]
    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM rascunhos_unidade WHERE unidade_id=? AND mes_referencia=?",
                (uid, mes_ref),
            )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# Setup — três unidades PERCENTUAL_SIMPLES (schema mínimo): A e C com
# aucon_codigo_filial configurado, B sem integração nenhuma.
# ═══════════════════════════════════════════════════════════════════════
MES = "2026-08"
UID_A = "aucon_v1_unidade_a"
UID_B = "aucon_v1_unidade_b_sem_integracao"
UID_C = "aucon_v1_unidade_c"

for uid, nome in [(UID_A, "Aucon V1 Unidade A"), (UID_B, "Aucon V1 Unidade B"),
                   (UID_C, "Aucon V1 Unidade C")]:
    criar_unidade(uid, nome, "Contratante Teste", "2020-01-01", "PERCENTUAL_SIMPLES")
    salvar_parametros(uid, MES, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                      alterado_por="teste_aucon_v1")
definir_aucon_codigo_filial(UID_A, 101)
definir_aucon_codigo_filial(UID_C, 103)
# UID_B nunca recebe aucon_codigo_filial — permanece NULL.
load_units(force=True)

U_A = get_unit(UID_A)
U_B = get_unit(UID_B)
U_C = get_unit(UID_C)


# ═══════════════════════════════════════════════════════════════════════
# 1 e 2. Importa -> aprova -> origem_faturamento correto / ausente quando
#         o valor foi alterado manualmente depois da importação
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1 e 2 — origem_faturamento: presente quando valor bate, ausente quando foi editado")
print("=" * 70)
_reset_estado_unidade(UID_A, MES)

aucon_client.buscar_faturamento_aucon = lambda codigo_filial, mes_ref: AuconResultado(
    codigo_filial=codigo_filial, valor=11363.35, bruto=11363.35, cancelados=0.0,
    importado_em="2026-09-24 14:32:00",
)
status, detalhe = fech._importar_faturamento_aucon(UID_A, MES, U_A)
checar("1a. Importação aplicada com sucesso (status ok)", status == "ok")
# O serviço nunca escreve em st.session_state[f"fat_{uid}"] diretamente
# (ver docstring de _importar_faturamento_aucon — widget pode já existir
# no mesmo rerun); a garantia é a persistência no rascunho (banco), que
# _restaurar_rascunho aplica ao widget no próximo render (provado no
# teste 10, com clique de botão de verdade via AppTest).
checar("1b. Valor persistido no rascunho (banco)",
       carregar_rascunho_unidade(UID_A, MES).get(f"fat_{UID_A}") == 11363.35)

r1 = fech._aprovar_unidade(UID_A, MES, U_A, fat=11363.35, pe_override=0.0, custos_extras={})
origem1 = r1.extras.get("origem_faturamento")
checar("1c. resultado.extras['origem_faturamento'] existe após aprovar com o MESMO valor importado",
       origem1 is not None)
checar("1d. origem_faturamento.fonte == 'aucon'", origem1 and origem1.get("fonte") == "aucon")
checar("1e. origem_faturamento.codigo_filial == 101", origem1 and origem1.get("codigo_filial") == 101)
checar("1f. origem_faturamento.valor_importado == 11363.35",
       origem1 and origem1.get("valor_importado") == 11363.35)
checar("1g. origem_faturamento.bruto/cancelados presentes",
       origem1 and "bruto" in origem1 and "cancelados" in origem1)

# Confere que sobrevive de fato dentro de lancamentos.resultado_json (não só
# no objeto em memória) — golden real do mecanismo de persistência.
linhas = [l for l in get_lancamentos_mes(MES) if l["unidade_id"] == UID_A]
checar("1h. Lançamento aprovado persistido no banco", len(linhas) == 1)
resultado_json = json.loads(linhas[0]["resultado_json"])
checar("1i. origem_faturamento sobrevive dentro de lancamentos.resultado_json",
       resultado_json.get("extras", {}).get("origem_faturamento", {}).get("fonte") == "aucon")

# Cenário 2: nova competência, importa, opera altera manualmente, aprova
# com o valor ALTERADO — nunca marcar como Aucon.
MES2 = "2026-09"
salvar_parametros(UID_A, MES2, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                  alterado_por="teste_aucon_v1")
_reset_estado_unidade(UID_A, MES2)
aucon_client.buscar_faturamento_aucon = lambda codigo_filial, mes_ref: AuconResultado(
    codigo_filial=codigo_filial, valor=5000.0, bruto=5000.0, cancelados=0.0,
    importado_em="2026-09-24 15:00:00",
)
status, detalhe = fech._importar_faturamento_aucon(UID_A, MES2, U_A)
checar("2a. Segunda importação aplicada (status ok)", status == "ok")
# Operador altera manualmente o campo depois da importação.
st.session_state[f"fat_{UID_A}"] = 7777.77
r2 = fech._aprovar_unidade(UID_A, MES2, U_A, fat=7777.77, pe_override=0.0, custos_extras={})
checar("2b. resultado.extras NÃO contém origem_faturamento quando o valor aprovado difere do importado",
       not (r2.extras and "origem_faturamento" in r2.extras))


# ═══════════════════════════════════════════════════════════════════════
# 3. Preservação de campos do rascunho (nos dois sentidos)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3 — read-modify-write preserva integralmente os demais campos do rascunho")
print("=" * 70)
MES3 = "2026-08"
_reset_estado_unidade(UID_C, MES3)

# 3a: já existe rascunho com um campo não relacionado -> import Aucon não o apaga.
salvar_rascunho_unidade(UID_C, MES3, {"algum_outro_campo_do_rascunho": 42, f"fat_{UID_C}": 999.0})
aucon_client.buscar_faturamento_aucon = lambda codigo_filial, mes_ref: AuconResultado(
    codigo_filial=codigo_filial, valor=8000.0, bruto=8000.0, cancelados=0.0,
    importado_em="2026-09-24 16:00:00",
)
status, detalhe = fech._importar_faturamento_aucon(UID_C, MES3, U_C)
draft_pos_import = carregar_rascunho_unidade(UID_C, MES3)
checar("3a. Import Aucon preserva campo pré-existente não relacionado do rascunho",
       draft_pos_import.get("algum_outro_campo_do_rascunho") == 42)
checar("3b. Import Aucon atualiza fat_{uid} corretamente", draft_pos_import.get(f"fat_{UID_C}") == 8000.0)
checar("3c. Import Aucon grava _aucon_meta", "_aucon_meta" in draft_pos_import)

# 3d: abrir a tela da unidade DEPOIS do import (isto é, rodar _salvar_rascunho,
# como _inputs_parametros faz ao final de toda renderização) não deve apagar
# _aucon_meta, mesmo escrevendo só as chaves de widget.
chaves_widget = fech._chaves_estado_unidade(UID_C, U_C)
for k in chaves_widget:
    if k not in st.session_state:
        st.session_state[k] = draft_pos_import.get(k, 0.0)
fech._salvar_rascunho(UID_C, MES3, chaves_widget)
draft_pos_salvar = carregar_rascunho_unidade(UID_C, MES3)
checar("3d. _salvar_rascunho (chamado ao renderizar a unidade) PRESERVA _aucon_meta",
       "_aucon_meta" in draft_pos_salvar)
checar("3e. _salvar_rascunho continua sem ressuscitar campo de widget stale "
       "('algum_outro_campo_do_rascunho' não é chave de widget desta unidade)",
       "algum_outro_campo_do_rascunho" not in draft_pos_salvar)


# ═══════════════════════════════════════════════════════════════════════
# 4 e 8. Golden real (Viva Trindade, agosto/2026) — CANCELADO excluído
#         corretamente; falha em qualquer endpoint não altera faturamento
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4 e 8 — golden real Viva Trindade: CANCELADO excluído; falha não altera faturamento")
print("=" * 70)

_PASTA_GOLDEN = os.path.join(
    _REPO_ROOT, "data", "runs", "diagnostico_aucon", "2026-08_mes_completo_viva_trindade",
)
_ARQ_POR_PATH = {
    "/wsaucon/mensalidades": "mensalidades_codigofilial_33.json",
    "/wsaucon/entradascaixa": "entradascaixa_codigofilial_33.json",
    "/wsaucon/pagamentos": "pagamentos_codigofilial_33.json",
    "/wsaucon/recebimento_credito": "recebimento_credito_codigofilial_33.json",
    "/wsaucon/recebimento_conveniados": "recebimento_conveniados_codigofilial_33.json",
    "/wsaucon/recebimento_correspondentes": "recebimento_correspondentes_codigofilial_33.json",
}


def _fake_buscar_endpoint_golden(token, path, codigo_filial, data_inicial, data_final):
    with open(os.path.join(_PASTA_GOLDEN, _ARQ_POR_PATH[path]), encoding="utf-8") as f:
        return json.load(f)


_buscar_endpoint_original = aucon_client._buscar_endpoint
_obter_token_original = aucon_client._obter_token
aucon_client._buscar_endpoint = _fake_buscar_endpoint_golden
aucon_client._obter_token = lambda: "token-fake-teste"
# Seções 1/2/3 substituíram buscar_faturamento_aucon por lambdas — aqui
# precisamos da função real (só com a camada HTTP mockada) para provar o
# golden de verdade.
aucon_client.buscar_faturamento_aucon = _buscar_faturamento_aucon_original

resultado_golden = aucon_client.buscar_faturamento_aucon(33, "2026-08")
checar("8a. Golden Viva Trindade — bruto == 48.802,03", resultado_golden.bruto == 48802.03)
checar("8b. Golden Viva Trindade — cancelados == 128,00", resultado_golden.cancelados == 128.00)
checar("8c. Golden Viva Trindade — valor (faturamento-base) == 48.674,03 (= faturamento aprovado real)",
       resultado_golden.valor == 48674.03)

# 4: agora simula falha isolada em UM dos seis endpoints (pagamentos) —
# nunca deve retornar soma parcial, e o faturamento já existente na
# unidade não pode ser alterado.
def _fake_buscar_endpoint_falha_pagamentos(token, path, codigo_filial, data_inicial, data_final):
    if path == "/wsaucon/pagamentos":
        raise AuconRespostaIncompletaError("timeout simulado em pagamentos")
    return _fake_buscar_endpoint_golden(token, path, codigo_filial, data_inicial, data_final)


aucon_client._buscar_endpoint = _fake_buscar_endpoint_falha_pagamentos
excecao_levantada = False
try:
    aucon_client.buscar_faturamento_aucon(33, "2026-08")
except AuconRespostaIncompletaError:
    excecao_levantada = True
checar("4a. Falha em UM dos seis endpoints levanta AuconRespostaIncompletaError "
       "(nunca soma parcial)", excecao_levantada)

# Via _importar_faturamento_aucon: unidade já tinha um faturamento (da
# importação golden do teste 8); a falha não deve alterá-lo.
_reset_estado_unidade(UID_C, "2026-08")
salvar_rascunho_unidade(UID_C, "2026-08", {f"fat_{UID_C}": 12345.67})
st.session_state[f"fat_{UID_C}"] = 12345.67


def _buscar_faturamento_aucon_falha(codigo_filial, mes_ref):
    raise AuconRespostaIncompletaError("timeout simulado")


aucon_client.buscar_faturamento_aucon = _buscar_faturamento_aucon_falha
status, detalhe = fech._importar_faturamento_aucon(UID_C, "2026-08", U_C)
checar("4b. _importar_faturamento_aucon retorna status 'erro' em falha de endpoint", status == "erro")
checar("4c. Faturamento existente (fat_uid) NÃO foi alterado após a falha",
       st.session_state[f"fat_{UID_C}"] == 12345.67)
draft_apos_falha = carregar_rascunho_unidade(UID_C, "2026-08")
checar("4d. Rascunho existente (fat_uid) NÃO foi alterado após a falha",
       draft_apos_falha.get(f"fat_{UID_C}") == 12345.67)

aucon_client._buscar_endpoint = _buscar_endpoint_original
aucon_client._obter_token = _obter_token_original


# ═══════════════════════════════════════════════════════════════════════
# 5 e 6. Lote: falha isolada não impede as demais; unidade sem
#         aucon_codigo_filial permanece intocada
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5 e 6 — lote continua processando as demais unidades; unidade sem integração intocada")
print("=" * 70)
MES5 = "2026-08"
for uid in (UID_A, UID_B, UID_C):
    salvar_parametros(uid, MES5, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                      alterado_por="teste_aucon_v1")
    _reset_estado_unidade(uid, MES5)

# Faturamento pré-existente da unidade B (sem integração) — deve continuar
# exatamente assim depois do lote.
st.session_state[f"fat_{UID_B}"] = 55555.55
salvar_rascunho_unidade(UID_B, MES5, {f"fat_{UID_B}": 55555.55})


def _buscar_faturamento_aucon_lote(codigo_filial, mes_ref):
    if codigo_filial == 101:  # UID_A
        return AuconResultado(codigo_filial=101, valor=1000.0, bruto=1000.0,
                               cancelados=0.0, importado_em="2026-09-24 17:00:00")
    if codigo_filial == 103:  # UID_C
        raise AuconRespostaIncompletaError("timeout simulado no lote")
    raise AssertionError(f"CodigoFilial inesperado no lote: {codigo_filial}")


aucon_client.buscar_faturamento_aucon = _buscar_faturamento_aucon_lote
unidades_lote = [get_unit(UID_A), get_unit(UID_B), get_unit(UID_C)]
fech._buscar_faturamentos_aucon_lote(MES5, unidades_lote)
resumo = st.session_state["aucon_ultimo_lote"]

checar("5a. Lote processou UID_A com sucesso mesmo com UID_C falhando",
       any(o["uid"] == UID_A for o in resumo["ok"]))
checar("5b. Lote registrou UID_C como erro, sem abortar o processamento das demais",
       any(e["uid"] == UID_C for e in resumo["erros"]))
checar("5c. Nenhuma menção a UID_B no lote (não tem aucon_codigo_filial — sequer é tentada)",
       not any(o["uid"] == UID_B for o in resumo["ok"] + resumo["conflitos"] + resumo["erros"]))
checar("6a. Unidade sem aucon_codigo_filial permanece com o faturamento original em session_state",
       st.session_state[f"fat_{UID_B}"] == 55555.55)
draft_b = carregar_rascunho_unidade(UID_B, MES5)
checar("6b. Unidade sem aucon_codigo_filial permanece com o rascunho original no banco",
       draft_b.get(f"fat_{UID_B}") == 55555.55)
checar("6c. Unidade A foi de fato atualizada pelo lote (persistida no rascunho)",
       carregar_rascunho_unidade(UID_A, MES5).get(f"fat_{UID_A}") == 1000.0)


# ═══════════════════════════════════════════════════════════════════════
# 7. Lote e atualização individual usam a mesma regra/service
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("7 — lote e atualização individual produzem resultado idêntico para a mesma resposta")
print("=" * 70)
_reset_estado_unidade(UID_A, "2026-08")
aucon_client.buscar_faturamento_aucon = lambda codigo_filial, mes_ref: AuconResultado(
    codigo_filial=codigo_filial, valor=9999.99, bruto=9999.99, cancelados=0.0,
    importado_em="2026-09-24 18:00:00",
)
status_individual, detalhe_individual = fech._importar_faturamento_aucon(UID_A, "2026-08", U_A)
valor_via_individual = carregar_rascunho_unidade(UID_A, "2026-08").get(f"fat_{UID_A}")

_reset_estado_unidade(UID_A, "2026-08")
fech._buscar_faturamentos_aucon_lote("2026-08", [get_unit(UID_A)])
valor_via_lote = carregar_rascunho_unidade(UID_A, "2026-08").get(f"fat_{UID_A}")

checar("7a. Atualização individual aplica o valor retornado pelo service", valor_via_individual == 9999.99)
checar("7b. Lote aplica o MESMO valor, para a mesma resposta mockada (mesma função, "
       "_importar_faturamento_aucon, usada nos dois pontos de entrada)",
       valor_via_lote == valor_via_individual == 9999.99)
import inspect
_src_lote = inspect.getsource(fech._buscar_faturamentos_aucon_lote)
checar("7c. Confirmação estrutural: _buscar_faturamentos_aucon_lote chama "
       "_importar_faturamento_aucon (não duplica a lógica)",
       "_importar_faturamento_aucon(" in _src_lote)


# ═══════════════════════════════════════════════════════════════════════
# 9. Regressão — draft/DU (sugestão do mês anterior, edição deliberada,
#    zero) e "nunca marcar origem Aucon quando nunca houve importação"
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("9 — regressão de draft/DU e ausência de marca Aucon sem importação")
print("=" * 70)
from streamlit.testing.v1 import AppTest

_PROBE_COUNTER = [0]
_PROBE_PATHS: list[str] = []
atexit.register(lambda: [os.remove(p) for p in _PROBE_PATHS if os.path.exists(p)])


def _escrever_probe(uid: str, mes_ref: str) -> str:
    _PROBE_COUNTER[0] += 1
    path = os.path.join(_REPO_ROOT, "tests", f"_probe_aucon_v1_{_PROBE_COUNTER[0]}.py")
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


def _abrir_fechamento(uid: str, mes_ref: str) -> AppTest:
    path = _escrever_probe(uid, mes_ref)
    at = AppTest.from_file(path, default_timeout=60)
    at.run()
    return at


def _valor(at: AppTest, label_sub: str) -> float:
    return next(n.value for n in at.number_input if label_sub in n.label)


# 9a-9d: exatamente o cenário já validado em v11 (sugestão do mês anterior +
# zero deliberado sobrevive a refresh) — reproduzido aqui, numa unidade SEM
# aucon_codigo_filial, para provar que a mudança em _salvar_rascunho (agora
# preservando "_aucon_meta" quando presente) não altera em nada o
# comportamento de unidades que nunca usaram a integração.
from app.models import criar_unidade as _criar_unidade_du

UID_DU = "aucon_v1_du_regressao"
_criar_unidade_du(UID_DU, "Aucon V1 DU Regressão", "Nilo Square", "2026-10-01",
                   "COM_ALIQUOTA_CUMUL_DU")
load_units(force=True)
salvar_parametros(UID_DU, "2026-10", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
    "percentual_aluguel": 0.85,
    "despesas_operacao": [{"id": "folha", "nome": "Folha"}],
}, alterado_por="teste_aucon_v1")

at_nov_antes = _abrir_fechamento(UID_DU, "2026-11")
checar("9a. Novembro (antes de outubro existir): Folha = 0,00 — regressão intacta",
       _valor(at_nov_antes, "Folha") == 0.0)

at_out = _abrir_fechamento(UID_DU, "2026-10")
next(n for n in at_out.number_input if "Faturamento" in n.label).set_value(50000.0)
at_out.run()
next(n for n in at_out.number_input if "Folha" in n.label).set_value(9230.0)
at_out.run()
next(b for b in at_out.button if b.label == "Calcular").click()
at_out.run()
next(b for b in at_out.button if b.label == "Aprovar").click()
at_out.run()
checar("9b. Outubro aprovado sem exceção", len(at_out.exception) == 0)

at_nov_depois = _abrir_fechamento(UID_DU, "2026-11")
checar("9c. Novembro (depois de outubro aprovado): Folha = 9.230,00 — sugestão do mês "
       "anterior continua funcionando", _valor(at_nov_depois, "Folha") == 9230.0)

next(n for n in at_nov_depois.number_input if "Folha" in n.label).set_value(0.0)
at_nov_depois.run()
at_nov_depois2 = _abrir_fechamento(UID_DU, "2026-11")
checar("9d. Zero deliberado sobrevive a nova sessão/refresh — regressão intacta",
       _valor(at_nov_depois2, "Folha") == 0.0)

# 9e: unidade COM aucon_codigo_filial, mas o operador nunca clicou em
# "Atualizar faturamento" (fluxo manual comum) — aprovar não deve, em
# hipótese alguma, gravar uma origem_faturamento Aucon.
_reset_estado_unidade(UID_A, "2026-08")
r9 = fech._aprovar_unidade(UID_A, "2026-08", U_A, fat=4321.0, pe_override=0.0, custos_extras={})
checar("9e. Aprovar faturamento manual (nunca houve importação Aucon) NÃO grava "
       "origem_faturamento", not (r9.extras and "origem_faturamento" in r9.extras))


# ═══════════════════════════════════════════════════════════════════════
# 10. Regressão real de homologação (Dom Pedro, set/2026): clicar em
#     "Atualizar faturamento" com o widget fat_{uid} JÁ instanciado no
#     mesmo rerun não pode levantar StreamlitAPIException. Reproduzido
#     com clique de botão de verdade via AppTest — nunca chamando a
#     função de serviço diretamente, porque o bug só existe no ciclo
#     real de execução do Streamlit (widget instanciado -> botão clicado
#     no MESMO run), que uma chamada direta de função não reproduz.
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("10 — regressão real: clique em 'Atualizar faturamento' com widget já instanciado")
print("=" * 70)
MES10 = "2026-10"
salvar_parametros(UID_A, MES10, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                  alterado_por="teste_aucon_v1")
_reset_estado_unidade(UID_A, MES10)

aucon_client.buscar_faturamento_aucon = lambda codigo_filial, mes_ref: AuconResultado(
    codigo_filial=codigo_filial, valor=22222.22, bruto=22222.22, cancelados=0.0,
    importado_em="2026-09-24 19:00:00",
)

at10 = _abrir_fechamento(UID_A, MES10)
checar("10a. Tela abre sem exceção, com o widget Faturamento já instanciado",
       len(at10.exception) == 0 and any("Faturamento" in n.label for n in at10.number_input))

btn_atualizar = next((b for b in at10.button if b.label == "Atualizar faturamento"), None)
checar("10b. Botão 'Atualizar faturamento' está presente (unidade com aucon_codigo_filial)",
       btn_atualizar is not None)

btn_atualizar.click()
at10.run()  # widget fat_{uid} já instanciado ANTES deste clique ser processado —
            # é exatamente o cenário real que gerou o StreamlitAPIException.
checar("10c. Clicar em 'Atualizar faturamento' com o widget já instanciado NÃO "
       "levanta StreamlitAPIException (nem nenhuma outra exceção)",
       len(at10.exception) == 0)
checar("10d. Campo Faturamento (R$) reflete o novo valor após o clique",
       _valor(at10, "Faturamento") == 22222.22)

draft10 = carregar_rascunho_unidade(UID_A, MES10)
checar("10e. Valor e _aucon_meta persistidos no rascunho (banco), não só em memória",
       draft10 is not None and draft10.get(f"fat_{UID_A}") == 22222.22
       and "_aucon_meta" in draft10)


# ═══════════════════════════════════════════════════════════════════════
# 11. Atomicidade fat_{uid}/_aucon_meta — nunca persistir um sem o outro
#     em sincronia. Investigação de um caso real de homologação: depois
#     do StreamlitAPIException corrigido na seção 10, uma tela ainda
#     mostrava metadata apontando 9.666,18 com o campo em 0,00, como se
#     a importação tivesse sido parcial. A causa raiz era a versão ANTIGA
#     (pré-correção) travar DEPOIS de persistir fat_{uid}+_aucon_meta
#     corretamente juntos — o rascunho no banco já estava correto, só o
#     widget ao vivo (session_state) é que nunca foi ressincronizado,
#     porque o crash impedia o rerun. Este teste prova que, no código
#     atual, essa dupla nunca é gravada de forma dividida.
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("11 — atomicidade: fat_{uid} e _aucon_meta.valor_importado nunca divergem no rascunho")
print("=" * 70)

import inspect as _inspect

_src_persistir = _inspect.getsource(fech._persistir_valor_aucon_no_rascunho)
checar("11a. Confirmação estrutural: existe exatamente UMA chamada a "
       "salvar_rascunho_unidade dentro de _persistir_valor_aucon_no_rascunho "
       "(uma única escrita, nunca duas separadas)",
       _src_persistir.count("salvar_rascunho_unidade(") == 1)
_pos_fat = _src_persistir.find(f'draft[f"fat_{{uid}}"]')
_pos_meta = _src_persistir.find('draft["_aucon_meta"]')
_pos_save = _src_persistir.find("salvar_rascunho_unidade(")
checar("11b. Confirmação estrutural: fat_{uid} e _aucon_meta são setados no MESMO "
       "dict ANTES da única chamada de gravação (não depois, não em chamadas separadas)",
       -1 < _pos_fat < _pos_save and -1 < _pos_meta < _pos_save)

MES11 = "2026-11"
UID11 = UID_C
salvar_parametros(UID11, MES11, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0},
                  alterado_por="teste_aucon_v1")
_reset_estado_unidade(UID11, MES11)

# Várias importações em sequência (valores diferentes) — a cada uma, o par
# tem que ficar e permanecer consistente no rascunho persistido.
consistente_em_todas = True
for valor_teste in (1111.11, 2222.22, 3333.33):
    meta_teste = {
        "valor_importado": valor_teste, "importado_em": "2026-09-24 20:00:00",
        "codigo_filial_usado": 103, "bruto": valor_teste, "cancelados": 0.0,
    }
    fech._persistir_valor_aucon_no_rascunho(UID11, MES11, valor_teste, meta_teste)
    draft_check = carregar_rascunho_unidade(UID11, MES11)
    fat_persistido = draft_check.get(f"fat_{UID11}")
    meta_persistida = draft_check.get("_aucon_meta", {}).get("valor_importado")
    if fat_persistido != valor_teste or meta_persistida != valor_teste:
        consistente_em_todas = False
checar("11c. Depois de cada importação sucessiva, fat_{uid} == _aucon_meta.valor_importado "
       "no rascunho persistido (nunca um valor 'ficou para trás')", consistente_em_todas)

# Simula o pior caso do bug antigo: uma exceção acontecendo IMEDIATAMENTE
# depois de _persistir_valor_aucon_no_rascunho retornar (equivalente ao
# StreamlitAPIException que a versão antiga levantava na linha seguinte).
# Mesmo assim, o que já foi gravado no banco tem que estar consistente —
# só a sincronização do widget ao vivo poderia ficar pendente (isso é
# resolvido pelo rerun/marcador, não por esta função).
try:
    fech._persistir_valor_aucon_no_rascunho(
        UID11, MES11, 4444.44,
        {"valor_importado": 4444.44, "importado_em": "2026-09-24 21:00:00",
         "codigo_filial_usado": 103, "bruto": 4444.44, "cancelados": 0.0},
    )
    raise RuntimeError("falha simulada IMEDIATAMENTE apos persistir, como o bug antigo")
except RuntimeError as e:
    if "falha simulada" not in str(e):
        raise

draft_apos_crash_simulado = carregar_rascunho_unidade(UID11, MES11)
checar("11d. Mesmo com uma exceção IMEDIATAMENTE após a persistência (simulando o "
       "StreamlitAPIException do bug antigo), o par já gravado no banco continua "
       "consistente — fat_{uid} == _aucon_meta.valor_importado",
       draft_apos_crash_simulado.get(f"fat_{UID11}") == 4444.44
       and draft_apos_crash_simulado.get("_aucon_meta", {}).get("valor_importado") == 4444.44)


# ═══════════════════════════════════════════════════════════════════════
# 12. Bug real de homologação (Dom Pedro, set/2026): importa X via Aucon
#     -> abre a unidade -> altera manualmente para Y -> Calcular -> sai
#     (Voltar à lista) -> volta a entrar -> campo continua Y (não reverte
#     para X). Causa raiz: o Streamlit remove de session_state a chave de
#     um widget assim que ele para de ser instanciado (ex.: navegar para
#     a lista) — o marcador _draft_ctx_{uid} sobrevivia a isso, então
#     _restaurar_rascunho pulava o recarregamento do banco ao reabrir a
#     unidade, e o campo caía no fallback antigo (faturamentos[uid]/
#     fat_importado), que nunca reflete a edição manual. Tudo isso
#     acontece dentro da MESMA sessão (mesmo objeto AppTest/mesma conexão
#     — não é um caso de "nova sessão").
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("12 — E2E real: importa X -> edita para Y -> Calcular -> sai -> volta -> campo continua Y")
print("=" * 70)

UID12 = "aucon_v1_e2e_edicao_manual"
MES12 = "2026-08"
criar_unidade(UID12, "Aucon V1 E2E Edição Manual", "Contratante Teste", "2020-01-01",
              "COM_ALIQUOTA_CUMUL")
salvar_parametros(UID12, MES12, {
    "aliquota_imposto": 0.0, "percentual_aluguel": 0.85, "ponto_equilibrio": 0.0,
}, alterado_por="teste_aucon_v1")
definir_aucon_codigo_filial(UID12, 112)
load_units(force=True)

VALOR_X = 11363.35
VALOR_Y = 10000.00

aucon_client.buscar_faturamento_aucon = lambda codigo_filial, mes_ref: AuconResultado(
    codigo_filial=codigo_filial, valor=VALOR_X, bruto=VALOR_X, cancelados=0.0,
    importado_em="2026-09-25 10:00:00",
)
fech._buscar_faturamentos_aucon_lote(MES12, [get_unit(UID12)])
checar("12a. Lote importou X corretamente no rascunho",
       carregar_rascunho_unidade(UID12, MES12).get(f"fat_{UID12}") == VALOR_X)

# Probe SEM selected_unit fixo — controlado externamente pelo teste, para
# poder alternar lista <-> detalhe no MESMO objeto AppTest (mesma sessão).
_probe_e2e_path = os.path.join(_REPO_ROOT, "tests", "_probe_aucon_v1_e2e.py")
with open(_probe_e2e_path, "w") as f:
    f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
from app.ui.fechamento import tela_fechamento
tela_fechamento({MES12!r})
''')
_PROBE_PATHS.append(_probe_e2e_path)

at12 = AppTest.from_file(_probe_e2e_path, default_timeout=60)
at12.session_state["selected_unit"] = UID12
at12.run()
checar("12b. Tela abre com o valor X importado", _valor(at12, "Faturamento") == VALOR_X)

campo12 = next(n for n in at12.number_input if "Faturamento" in n.label)
campo12.set_value(VALOR_Y)
at12.run()
checar("12c. Campo reflete Y logo após a edição manual", _valor(at12, "Faturamento") == VALOR_Y)

next(b for b in at12.button if b.label == "Calcular").click()
at12.run()
checar("12d. Calcular roda sem exceção com o valor Y editado", len(at12.exception) == 0)
checar("12e. Campo continua Y logo após Calcular", _valor(at12, "Faturamento") == VALOR_Y)

btn_voltar12 = next(b for b in at12.button if "Voltar" in (b.label or ""))
btn_voltar12.click()
at12.run()
checar("12f. Navegou para a lista (selected_unit == None)",
       at12.session_state["selected_unit"] is None)

at12.session_state["selected_unit"] = UID12
at12.run()
checar("12g. CAMPO CONTINUA Y ao reentrar na MESMA sessão (bug real corrigido)",
       _valor(at12, "Faturamento") == VALOR_Y)

draft12 = carregar_rascunho_unidade(UID12, MES12)
checar("12h. Rascunho no banco confirma fat_{uid} == Y", draft12.get(f"fat_{UID12}") == VALOR_Y)
checar("12i. _aucon_meta.valor_importado CONTINUA X (não foi sobrescrita pela edição manual)",
       draft12.get("_aucon_meta", {}).get("valor_importado") == VALOR_X)

# Nova atualização Aucon retorna X de novo -> deve detectar conflito
# (Y != X, X == meta anterior) e NÃO sobrescrever automaticamente.
status12, detalhe12 = fech._importar_faturamento_aucon(
    UID12, MES12, get_unit(UID12),
)
checar("12j. Nova busca Aucon com o mesmo X detecta conflito (não aplica sozinha)",
       status12 == "conflito")
checar("12k. Detalhe do conflito reporta valor_atual=Y e valor_importado_anterior=X",
       detalhe12.get("valor_atual") == VALOR_Y
       and detalhe12.get("valor_importado_anterior") == VALOR_X)
draft12_pos_conflito = carregar_rascunho_unidade(UID12, MES12)
checar("12l. Rascunho permanece em Y após a tentativa de reimportação (nada sobrescrito)",
       draft12_pos_conflito.get(f"fat_{UID12}") == VALOR_Y)

# ── Mesmo fluxo, agora com Y = 0 (zero deliberado) ───────────────────────
print("-" * 70)
print("12m-12r — mesmo fluxo com Y = 0 (zero deliberado, já foi fonte de bugs antes)")
print("-" * 70)
UID12B = "aucon_v1_e2e_edicao_zero"
criar_unidade(UID12B, "Aucon V1 E2E Zero", "Contratante Teste", "2020-01-01",
              "COM_ALIQUOTA_CUMUL")
salvar_parametros(UID12B, MES12, {
    "aliquota_imposto": 0.0, "percentual_aluguel": 0.85, "ponto_equilibrio": 0.0,
}, alterado_por="teste_aucon_v1")
definir_aucon_codigo_filial(UID12B, 113)
load_units(force=True)

fech._buscar_faturamentos_aucon_lote(MES12, [get_unit(UID12B)])
checar("12m. Lote importou X no rascunho da segunda unidade",
       carregar_rascunho_unidade(UID12B, MES12).get(f"fat_{UID12B}") == VALOR_X)

_probe_e2e_path_b = os.path.join(_REPO_ROOT, "tests", "_probe_aucon_v1_e2e_b.py")
with open(_probe_e2e_path_b, "w") as f:
    f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
from app.ui.fechamento import tela_fechamento
tela_fechamento({MES12!r})
''')
_PROBE_PATHS.append(_probe_e2e_path_b)

at12b = AppTest.from_file(_probe_e2e_path_b, default_timeout=60)
at12b.session_state["selected_unit"] = UID12B
at12b.run()
checar("12n. Tela abre com X importado (segunda unidade)", _valor(at12b, "Faturamento") == VALOR_X)

campo12b = next(n for n in at12b.number_input if "Faturamento" in n.label)
campo12b.set_value(0.0)
at12b.run()
next(b for b in at12b.button if b.label == "Calcular").click()
at12b.run()
# _acao_calcular bloqueia calculo com fat<=0 (validacao pre-existente, nao
# relacionada ao Aucon) — o que importa aqui e que digitar 0 e clicar em
# Calcular nao lanca excecao, e o campo continua mostrando 0.
checar("12o. Calcular com Y=0 roda sem exceção (validação de fat<=0 já existente, não "
       "relacionada ao Aucon)", len(at12b.exception) == 0)

btn_voltar12b = next(b for b in at12b.button if "Voltar" in (b.label or ""))
btn_voltar12b.click()
at12b.run()
at12b.session_state["selected_unit"] = UID12B
at12b.run()
checar("12p. Zero deliberado CONTINUA 0,00 ao sair e voltar (mesma sessão)",
       _valor(at12b, "Faturamento") == 0.0)

draft12b = carregar_rascunho_unidade(UID12B, MES12)
checar("12q. Rascunho confirma fat_{uid} == 0.0 persistido", draft12b.get(f"fat_{UID12B}") == 0.0)
checar("12r. _aucon_meta.valor_importado da segunda unidade continua X (histórico preservado)",
       draft12b.get("_aucon_meta", {}).get("valor_importado") == VALOR_X)


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA INTEGRAÇÃO AUCON V1 PASSARAM ===")
