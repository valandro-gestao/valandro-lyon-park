"""
Cobertura permanente da 11ª rodada de homologação de set/2026 — dois bugs
de fluxo encontrados na homologação REAL da Nilo Square (COM_ALIQUOTA_CUMUL_DU),
já com o PDF aprovado e enviado para validação do sócio.

  1. Valores mensais de Direito de Uso não eram sugeridos na competência
     seguinte. Causa raiz: `_salvar_rascunho` persistia incondicionalmente,
     a cada renderização, o valor MOSTRADO em cada campo mensal de DU —
     inclusive quando esse valor era só o default (lançamento anterior
     sugerido, ou zero), nunca uma edição genuína do operador. Bastava
     abrir uma competência nova (mesmo sem editar nada) para gravar um
     rascunho "fantasma" que, a partir daí, tinha prioridade permanente
     sobre a sugestão da competência anterior — mesmo depois de a
     competência anterior ser aprovada com valores reais.

     Corrigido na ORIGEM (Opção B, precisa — não heurística sobre 0,00):
     cada input mensal de DU (`_input_du_mensal`) marca explicitamente,
     via `on_change` (`_marcar_du_editado`), quando o OPERADOR de fato
     altera o valor — nunca quando o widget só mostra um default.
     `_salvar_rascunho` só persiste o valor de um campo de DU quando essa
     marca existe (`_e_chave_valor_du`); a marca em si também é persistida
     e restaurada junto do valor (`_chaves_estado_unidade`), garantindo que
     "isto foi editado" sobreviva a uma nova sessão/refresh — não é uma
     flag só em memória. Um 0,00 deliberadamente informado continua sendo
     respeitado e persistido, exatamente como qualquer outro valor.

     De quebra, a receita_ressarcimento_du (citada no relato real) nunca
     tinha o fallback de sugestão da competência anterior — só as 4
     rubricas tinham. Corrigido junto (`_valor_escalar_du_sugerido`).

  2. Administração avaliava "configuração completa/incompleta" sempre na
     competência de HOJE, ignorando o início operacional da unidade — uma
     unidade nova, com início no futuro, era avaliada (e mostrada como
     incompleta) num mês em que ela sequer existia. Corrigido com
     `competencia_avaliacao = max(competência atual, início da operação)`
     (`_competencia_avaliacao_padrao`), aplicado ao default do seletor da
     aba Parâmetros, ao chip da lista de unidades e à aba Dados da
     Unidade. Seletor não é bloqueado — se o operador navegar manualmente
     para antes do início, mostra um aviso informativo em vez de listar
     pendências que não fazem sentido. `pode_ativar_unidade` não foi
     tocada.

Nenhuma alteração em calculator, reporter/PDF, fórmula ou Square legado.

Execução: python3 tests/testes_homologacao_set2026_v11.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v11_")
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


from app.models import criar_unidade, salvar_parametros, unidade_id_existe, atualizar_unidade
from app.engine import load_units, calcular
from streamlit.testing.v1 import AppTest

_PROBE_COUNTER = [0]
_PROBE_PATHS: list[str] = []
atexit.register(lambda: [os.remove(p) for p in _PROBE_PATHS if os.path.exists(p)])


def _escrever_probe(uid: str, mes_ref: str) -> str:
    # AppTest relê o arquivo do script a cada .run() (inclusive depois da
    # primeira chamada) — o probe precisa continuar existindo em disco
    # enquanto o objeto AppTest ainda for usado; por isso o cleanup é só no
    # fim do arquivo de teste (atexit), nunca logo após a primeira _run.
    _PROBE_COUNTER[0] += 1
    path = os.path.join(_REPO_ROOT, "tests", f"_probe_v11_{_PROBE_COUNTER[0]}.py")
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


# ═══════════════════════════════════════════════════════════════════════
# 1. Bug 1 — fluxo completo real: abrir novembro ANTES de outubro estar
#    aprovado, não editar, aprovar outubro, voltar a novembro
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. Fluxo completo — abrir novembro antes -> aprovar outubro -> reabrir novembro")
print("=" * 70)
UID1 = "nilo_v11_fluxo1"
criar_unidade(UID1, "Nilo v11 Fluxo 1", "Nilo Square", "2026-10-01", "COM_ALIQUOTA_CUMUL_DU")
load_units(force=True)
salvar_parametros(UID1, "2026-10", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
    "percentual_aluguel": 0.85,
    "despesas_operacao": [{"id": "folha", "nome": "Folha"}],
}, alterado_por="teste_v11")

# Passo 1: abrir novembro ANTES de outubro ter qualquer valor/aprovação,
# sem editar nada.
at_nov_antes = _abrir_fechamento(UID1, "2026-11")
checar("1a. Novembro (antes de outubro existir): Folha = 0,00 (nada para sugerir ainda)",
       _valor(at_nov_antes, "Folha") == 0.0)

from app.models import carregar_rascunho_unidade
draft_nov_antes = carregar_rascunho_unidade(UID1, "2026-11")
chave_folha = f"du_despesas_operacao_{UID1}_folha"
checar("1b. Só abrir novembro NÃO grava rascunho para a rubrica de DU (correção na origem)",
       draft_nov_antes is None or chave_folha not in draft_nov_antes)

# Passo 2: preencher e aprovar outubro (fluxo real, botões de verdade).
at_out = _abrir_fechamento(UID1, "2026-10")
next(n for n in at_out.number_input if "Faturamento" in n.label).set_value(50000.0)
at_out.run()
next(n for n in at_out.number_input if "Folha" in n.label).set_value(9230.0)
at_out.run()
next(b for b in at_out.button if b.label == "Calcular").click()
at_out.run()
next(b for b in at_out.button if b.label == "Aprovar").click()
at_out.run()
checar("1c. Outubro aprovado sem exceção", len(at_out.exception) == 0)

# Passo 3: voltar a novembro (sessão nova) — deve sugerir outubro agora.
at_nov_depois = _abrir_fechamento(UID1, "2026-11")
checar("1d. Novembro (depois de outubro aprovado): Folha = 9.230,00 (sugestão funcionou)",
       _valor(at_nov_depois, "Folha") == 9230.0)


# ═══════════════════════════════════════════════════════════════════════
# 2. Bug 1 — zero deliberado sobrevive a refresh/nova sessão
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Novembro herda 9.230 -> operador zera deliberadamente -> nova sessão -> continua 0")
print("=" * 70)
UID2 = "nilo_v11_zero"
criar_unidade(UID2, "Nilo v11 Zero", "Nilo Square", "2026-10-01", "COM_ALIQUOTA_CUMUL_DU")
load_units(force=True)
salvar_parametros(UID2, "2026-10", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
    "percentual_aluguel": 0.85,
    "despesas_operacao": [{"id": "folha", "nome": "Folha"}],
}, alterado_por="teste_v11")

at_out2 = _abrir_fechamento(UID2, "2026-10")
next(n for n in at_out2.number_input if "Faturamento" in n.label).set_value(50000.0)
at_out2.run()
next(n for n in at_out2.number_input if "Folha" in n.label).set_value(9230.0)
at_out2.run()
next(b for b in at_out2.button if b.label == "Calcular").click()
at_out2.run()
next(b for b in at_out2.button if b.label == "Aprovar").click()
at_out2.run()

at_nov = _abrir_fechamento(UID2, "2026-11")
checar("2a. Novembro herda 9.230,00 de outubro", _valor(at_nov, "Folha") == 9230.0)
next(n for n in at_nov.number_input if "Folha" in n.label).set_value(0.0)
at_nov.run()
checar("2b. Mesma sessão, após zerar: valor mostrado é 0,00", _valor(at_nov, "Folha") == 0.0)

at_nov_refresh = _abrir_fechamento(UID2, "2026-11")
checar("2c. Nova sessão (refresh) em novembro: continua 0,00 (zero deliberado respeitado)",
       _valor(at_nov_refresh, "Folha") == 0.0)

draft_nov_zero = carregar_rascunho_unidade(UID2, "2026-11")
chave_folha2 = f"du_despesas_operacao_{UID2}_folha"
checar("2d. Rascunho de novembro grava o valor E a marca de edição",
       draft_nov_zero is not None and draft_nov_zero.get(chave_folha2) == 0.0
       and draft_nov_zero.get(f"{chave_folha2}__editado") is True)


# ═══════════════════════════════════════════════════════════════════════
# 3. Bug 1 — receita_ressarcimento_du também ganha sugestão da competência
#    anterior (gap adicional encontrado no relato real)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. receita_ressarcimento_du também sugere a competência anterior")
print("=" * 70)
UID3 = "nilo_v11_receita"
criar_unidade(UID3, "Nilo v11 Receita", "Nilo Square", "2026-10-01", "COM_ALIQUOTA_CUMUL_DU")
load_units(force=True)
salvar_parametros(UID3, "2026-10", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
    "percentual_aluguel": 0.85,
}, alterado_por="teste_v11")

at_out3 = _abrir_fechamento(UID3, "2026-10")
next(n for n in at_out3.number_input if "Faturamento" in n.label).set_value(50000.0)
at_out3.run()
next(n for n in at_out3.number_input if "Ressarcimento de Direito de Uso" in n.label).set_value(40994.0)
at_out3.run()
next(b for b in at_out3.button if b.label == "Calcular").click()
at_out3.run()
next(b for b in at_out3.button if b.label == "Aprovar").click()
at_out3.run()

at_nov3 = _abrir_fechamento(UID3, "2026-11")
checar("3a. Novembro sugere Receita Ressarcimento DU = 40.994,00 de outubro",
       _valor(at_nov3, "Ressarcimento de Direito de Uso") == 40994.0)

draft_nov3_antes = carregar_rascunho_unidade(UID3, "2026-11")  # nenhuma edição ainda nesta chamada
# (checagem já coberta pelo padrão 1b/4 — aqui só a sugestão em si)


# ═══════════════════════════════════════════════════════════════════════
# 4. Bug 1 — testes unitários dos helpers (sem depender de AppTest)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Helpers — _e_chave_valor_du / _salvar_rascunho filtram corretamente")
print("=" * 70)
from app.ui.fechamento import _e_chave_valor_du

checar("_e_chave_valor_du reconhece chave de rubrica DU",
       _e_chave_valor_du("du_despesas_operacao_nilo_folha") is True)
checar("_e_chave_valor_du reconhece receita_du_{uid}",
       _e_chave_valor_du("receita_du_nilo") is True)
checar("_e_chave_valor_du NÃO trata a própria flag '__editado' como valor",
       _e_chave_valor_du("du_despesas_operacao_nilo_folha__editado") is False)
checar("_e_chave_valor_du é False para chaves de outros campos (ex.: Faturamento)",
       _e_chave_valor_du("fat_nilo") is False)


# ═══════════════════════════════════════════════════════════════════════
# 5. Bug 2 — competência de avaliação nunca antes do início
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5. Administração — competencia_avaliacao = max(hoje, início)")
print("=" * 70)
from app.ui.administracao import _competencia_avaliacao_padrao
from datetime import date

UID5 = "nilo_v11_inicio"
criar_unidade(UID5, "Nilo v11 Início", "Nilo Square", "2026-10-01", "COM_ALIQUOTA_CUMUL_DU")
load_units(force=True)
salvar_parametros(UID5, "2026-10", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
    "percentual_aluguel": 0.85,
}, alterado_por="teste_v11")
atualizar_unidade(UID5, ativo=True)
load_units(force=True)

from app.models import get_unidade
u5 = get_unidade(UID5)
hoje_aaaa_mm = date.today().strftime("%Y-%m")
checar(f"5a. Hoje ({hoje_aaaa_mm}) é anterior ao início (2026-10) — cenário real da Nilo",
       hoje_aaaa_mm < "2026-10")
checar("5b. _competencia_avaliacao_padrao(u) = 2026-10 (início), não hoje",
       _competencia_avaliacao_padrao(u5) == "2026-10")

# Regressão: unidade com início no PASSADO continua avaliada em "hoje".
u_viva = get_unidade("viva_trindade")
checar("5c. Regressão: unidade com início no passado (Viva Trindade) continua avaliada em 'hoje'",
       _competencia_avaliacao_padrao(u_viva) == hoje_aaaa_mm)

_PROBE_ADMIN = os.path.join(_REPO_ROOT, "tests", "_probe_v11_admin.py")
with open(_PROBE_ADMIN, "w") as f:
    f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
import streamlit as st
st.session_state.admin_view = "editar"
st.session_state.admin_editar_uid = {UID5!r}
from app.ui.administracao import tela_administracao_unidades
tela_administracao_unidades()
''')
try:
    at_admin = AppTest.from_file(_PROBE_ADMIN, default_timeout=60)
    at_admin.run()
    checar("5d. Tela de Administração renderiza sem exceção", len(at_admin.exception) == 0)

    tab_dados = at_admin.tabs[0]
    checar("5e. Aba Dados da Unidade: 'Configuração avaliada em: 10/2026' (não 09/2026)",
           any("avaliada em: 10/2026" in c.value for c in tab_dados.caption))
    checar("5f. Aba Dados da Unidade: 'Configuração completa' (não 'incompleta')",
           any("completa" in s.value for s in tab_dados.success))

    tab_params = at_admin.tabs[1]
    mes_sel = next(sb for sb in tab_params.selectbox if sb.label == "Mês")
    checar("5g. Aba Parâmetros: seletor de competência já abre em Outubro (mês 10)",
           mes_sel.value == 10)
    checar("5h. Aba Parâmetros: 'Configuração completa em 10/2026'",
           any("completa em 10/2026" in s.value for s in tab_params.success))

    # --- 6. Seleção manual de competência ANTERIOR ao início ---
    print("=" * 70)
    print("6. Seleção manual de setembro (antes do início) -> aviso informativo")
    print("=" * 70)
    mes_sel.set_value(9)
    at_admin.run()
    tab_params = at_admin.tabs[1]
    checar("6a. Aviso informativo aparece ('ainda não estava em operação')",
           any("ainda não estava em operação" in i.value for i in tab_params.info))
    checar("6b. Nenhuma pendência (Alíquota/PE/Vagas) é listada para setembro",
           not any("Informe" in e.value for e in tab_params.error))
    checar("6c. Seletor NÃO foi bloqueado — setembro foi selecionado normalmente",
           mes_sel.value == 9)
finally:
    os.remove(_PROBE_ADMIN)


# ═══════════════════════════════════════════════════════════════════════
# 7. Bug 2 — chip da lista de unidades usa a mesma regra
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("7. Lista de unidades — chip usa max(hoje, início)")
print("=" * 70)
from app.models import status_configuracao
checar("7a. status_configuracao(u5, competencia_avaliacao_padrao) = 'completa'",
       status_configuracao(u5, _competencia_avaliacao_padrao(u5)) == "completa")
checar("7b. Regressão: status_configuracao ainda funciona normalmente para unidade antiga",
       status_configuracao(u_viva, _competencia_avaliacao_padrao(u_viva)) in ("completa", "incompleta"))


# ═══════════════════════════════════════════════════════════════════════
# 8. Regressão — pode_ativar_unidade intocada; goldens de calculator/PDF
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("8. Regressão — pode_ativar_unidade, goldens de calculator e PDF")
print("=" * 70)
from app.models import pode_ativar_unidade
checar("8a. pode_ativar_unidade(Nilo, início) == [] (função não tocada, comportamento igual)",
       pode_ativar_unidade(UID5, "2026-10") == [])
checar("8b. pode_ativar_unidade(Nilo, ANTES do início) ainda bloqueia (função não tocada)",
       len(pode_ativar_unidade(UID5, "2026-09")) > 0)

from app.calculators.cumulativo import calcular_com_aliquota_cumul
CFG_VIVA = {"id": "viva_trindade", "aliquota_imposto": 0.0, "percentual_aluguel": 0.85,
            "ponto_equilibrio": 0.0}
r_viva = calcular_com_aliquota_cumul(CFG_VIVA, "2026-08", faturamento=-1525.24 + 2400.0,
                                      saldo_override=-157142.75,
                                      custos_extras={"outras_despesas": 2400.0})
checar("8c. Regressão: golden da Viva Trindade continua -158.667,99",
       r_viva.prejuizo_acumulado_saida == -158667.99)

from app.calculators.cumul_du import calcular_com_aliquota_cumul_du
CFG_NILO_GOLDEN = {
    "id": "nilo_golden", "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0,
    "numero_vagas": 1129, "percentual_aluguel": 0.85,
    "despesas_ressarcimento_du": [
        {"id": "proprietarios", "nome": "Proprietários"},
        {"id": "provisionamento_iptu", "nome": "Provisionamento IPTU"},
    ],
    "despesas_rateio_du": [{"id": "agua", "nome": "Água"}, {"id": "energia", "nome": "Energia"}],
}
r_golden = calcular_com_aliquota_cumul_du(
    CFG_NILO_GOLDEN, "2026-07", faturamento=300000.0, saldo_override=0.0,
    custos_extras={
        "receita_ressarcimento_du": 234896.54,
        "despesas_ressarcimento_du": {"proprietarios": 82882.08, "provisionamento_iptu": 25066.43},
        "despesas_rateio_du": {"agua": 100000.0, "energia": 136457.21},
    },
)
checar("8d. Regressão: golden da Nilo (Ressarcimento Líquido DU) continua 126.948,03",
       r_golden.extras["ressarcimento_liquido_du"] == 126948.03)
checar("8e. Regressão: golden da Nilo (DU por vaga) continua 209,44",
       r_golden.extras["du_por_vaga"] == 209.44)


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 11) PASSARAM ===")
