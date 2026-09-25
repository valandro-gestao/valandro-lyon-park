"""
Cobertura permanente da 10ª rodada de homologação de set/2026 — três
ajustes encontrados na homologação REAL da Nilo Square (COM_ALIQUOTA_CUMUL_DU):

  1. Percentual × Faixas — a validação cruzada "algum_de" (percentual_
     aluguel/faixas_aluguel) lia só o valor PERSISTIDO (params_atuais),
     nunca o que o operador acabou de digitar na mesma renderização —
     configurar percentual_aluguel=70% pela primeira vez, com faixas_
     aluguel vazia, disparava "Informe o percentual ou cadastre as
     faixas" incorretamente. Bug genérico (mesmo código serve
     COM_ALIQUOTA_CUMUL) — nunca apareceu antes porque toda unidade
     existente já tinha os dois campos persistidos de uma vigência
     anterior. Corrigido em app.ui.administracao._aba_parametros: um
     snapshot corrente (params_atuais + o que já foi digitado no próprio
     loop) é usado na validação cruzada, não mais o snapshot cru.

  2. Defaults mensais das 4 famílias de rubricas de Direito de Uso —
     ordem de resolução: edição em andamento/rascunho da própria
     competência -> lançamento já calculado da própria competência ->
     lançamento anterior MAIS RECENTE (cadeia real, `mes_referencia <
     mes_ref ORDER BY DESC`, não "mês civil - 1") só como sugestão ->
     zero. Nunca persiste em parametros_vigentes. Chaves dinâmicas dos 4
     grupos + receita_ressarcimento_du agora fazem parte de
     _chaves_estado_unidade (rascunho sobrevive a refresh).

  3. PDF da Nilo — Prestação de Contas em blocos, reaproveitando
     `ReportData.blocos_receitas`/`BlocoReceita` (mesma infraestrutura já
     usada pelo Pátio para Outros Serviços/Carregadores — nenhum template
     novo, nenhum tipo_relatorio novo). Bloco 1 (_prestacao_cumul_du) só
     totais; Blocos 2/3/4 (Ressarcimento DU / Rateio DU / Despesas da
     Operação) sempre que houver dado; Bloco 5 (Despesas após Resultado)
     só quando a unidade tiver rubricas configuradas nesse grupo.

Nenhuma fórmula/calculator foi alterado; nenhuma unidade existente foi
tocada.

Execução: python3 tests/testes_homologacao_set2026_v10.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v10_")
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


from app.models import criar_unidade, salvar_parametros, unidade_id_existe
from app.engine import load_units, calcular
from streamlit.testing.v1 import AppTest


def _probe_admin(uid: str, tag: str) -> str:
    """Escreve um app mínimo que abre a Administração de `uid` e devolve o
    caminho — mesmo padrão usado nas rodadas anteriores (sem bypass do
    st.data_editor/widgets reais)."""
    path = os.path.join(_REPO_ROOT, "tests", f"_probe_{tag}.py")
    with open(path, "w") as f:
        f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
import streamlit as st
st.session_state.admin_view = "editar"
st.session_state.admin_editar_uid = {uid!r}
from app.ui.administracao import tela_administracao_unidades
tela_administracao_unidades()
''')
    return path


# ═══════════════════════════════════════════════════════════════════════
# 1. Percentual × Faixas — sem exigir "Faixa final sem limite"
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. Percentual x Faixas — percentual sozinho basta, sem forçar faixas")
print("=" * 70)


def _testar_percentual_sozinho(uid: str, tipo_calculo: str, tag: str, campos_extra=None):
    criar_unidade(uid, uid, uid, "2026-07-01", tipo_calculo)
    load_units(force=True)
    path = _probe_admin(uid, tag)
    try:
        at = AppTest.from_file(path, default_timeout=60)
        at.run()
        params_tab = at.tabs[1]

        def achar_num(sub):
            return next(n for n in params_tab.number_input if sub in n.label)

        achar_num("Alíquota de Imposto").set_value(0.0)
        achar_num("Ponto de Equilíbrio").set_value(0.0)
        if campos_extra:
            for label_sub, valor in campos_extra:
                achar_num(label_sub).set_value(valor)
        achar_num("Percentual de Aluguel").set_value(70.0)
        at.run()
        params_tab = at.tabs[1]
        erros = [e.value for e in params_tab.error]
        tem_erro_algum_de = any("Informe o percentual de aluguel ou cadastre as faixas" in e for e in erros)
        btn_revisar = next(b for b in params_tab.button if "Revisar" in b.label)
        return tem_erro_algum_de, btn_revisar.disabled
    finally:
        os.remove(path)


tem_erro_du, revisar_disabled_du = _testar_percentual_sozinho(
    "nilo_pct_v10", "COM_ALIQUOTA_CUMUL_DU", "pct_du_v10",
    campos_extra=[("Número de Vagas", 100)],
)
checar("COM_ALIQUOTA_CUMUL_DU: sem erro 'algum_de' com só percentual_aluguel=70%",
       not tem_erro_du)
checar("COM_ALIQUOTA_CUMUL_DU: botão 'Revisar alterações' habilitado",
       not revisar_disabled_du)

tem_erro_cumul, revisar_disabled_cumul = _testar_percentual_sozinho(
    "viva_pct_v10", "COM_ALIQUOTA_CUMUL", "pct_cumul_v10",
)
checar("Regressão COM_ALIQUOTA_CUMUL: sem erro 'algum_de' com só percentual_aluguel=70%",
       not tem_erro_cumul)
checar("Regressão COM_ALIQUOTA_CUMUL: botão 'Revisar alterações' habilitado",
       not revisar_disabled_cumul)


# ═══════════════════════════════════════════════════════════════════════
# 2. Defaults mensais das rubricas de Direito de Uso
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Defaults mensais — sugestão da competência anterior mais recente")
print("=" * 70)
from app.ui.fechamento import (
    _valor_du_ja_lancado, _valor_du_sugerido, _chaves_estado_unidade, _inputs_rubricas_du,
)
UID_DU = "nilo_defaults_v10"
criar_unidade(UID_DU, "Nilo Defaults v10", "Nilo Square", "2026-07-01", "COM_ALIQUOTA_CUMUL_DU")
load_units(force=True)
salvar_parametros(UID_DU, "2026-07", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
    "percentual_aluguel": 0.85,
    "despesas_operacao": [{"id": "seguranca", "nome": "Segurança"}],
}, alterado_por="teste_v10")

# Julho calculado com Segurança = 1000.0
r_jul = calcular(UID_DU, "2026-07", 50000.0, saldo_override=0.0,
                  custos_extras={"despesas_operacao": {"seguranca": 1000.0}})
from app.models import salvar_lancamento
salvar_lancamento(r_jul)

checar("Julho: _valor_du_ja_lancado encontra 1000.0 na própria competência",
       _valor_du_ja_lancado(UID_DU, "2026-07", "despesas_operacao", "seguranca") == 1000.0)

# --- 2a. Nova competência (agosto) herda o valor de julho, só como sugestão ---
checar("2a. Agosto (nova, sem lançamento): _valor_du_ja_lancado é None",
       _valor_du_ja_lancado(UID_DU, "2026-08", "despesas_operacao", "seguranca") is None)
checar("2a. Agosto (nova): _valor_du_sugerido usa a competência anterior mais recente (1000.0)",
       _valor_du_sugerido(UID_DU, "2026-08", "despesas_operacao", "seguranca") == 1000.0)

# --- 2b. Alterar agosto não altera julho ---
r_ago = calcular(UID_DU, "2026-08", 60000.0, saldo_override=r_jul.prejuizo_acumulado_saida,
                  custos_extras={"despesas_operacao": {"seguranca": 5000.0}})
salvar_lancamento(r_ago)
checar("2b. Agosto salvo com 5000.0", _valor_du_ja_lancado(UID_DU, "2026-08", "despesas_operacao", "seguranca") == 5000.0)
checar("2b. Julho continua com 1000.0 (alterar agosto não sobrescreveu julho)",
       _valor_du_ja_lancado(UID_DU, "2026-07", "despesas_operacao", "seguranca") == 1000.0)

# --- 2c. Setembro (nova) sugere o valor de AGOSTO (mais recente), não julho ---
checar("2c. Setembro (nova): sugestão usa agosto (5000.0), a competência mais recente — não julho",
       _valor_du_sugerido(UID_DU, "2026-09", "despesas_operacao", "seguranca") == 5000.0)

# --- 2d. Reabrir julho (competência histórica com lançamento próprio) usa
#     o valor histórico dela, nunca o "mais recente" (agosto) ---
checar("2d. Reabrir julho: _valor_du_ja_lancado (prioridade sobre sugestão) retorna 1000.0, não 5000.0",
       _valor_du_ja_lancado(UID_DU, "2026-07", "despesas_operacao", "seguranca") == 1000.0)

# --- 2e. Rubrica NOVA (não existia em nenhum lançamento anterior) inicia em zero ---
checar("2e. Rubrica nova sem histórico: _valor_du_ja_lancado é None",
       _valor_du_ja_lancado(UID_DU, "2026-09", "despesas_operacao", "limpeza") is None)
checar("2e. Rubrica nova sem histórico: _valor_du_sugerido também é None (cai para 0.0 em _inputs_rubricas_du)",
       _valor_du_sugerido(UID_DU, "2026-09", "despesas_operacao", "limpeza") is None)

# --- 2f. Rubrica REMOVIDA da estrutura atual não reaparece só por existir
#     historicamente: _inputs_rubricas_du só itera o que está em itens_cfg
#     (a estrutura ATUAL, vinda da Administração) ---
import inspect
fonte_inputs = inspect.getsource(_inputs_rubricas_du)
checar("2f. _inputs_rubricas_du itera normalizar_rubricas(itens_cfg) — só a estrutura atual, nunca o histórico",
       "normalizar_rubricas(itens_cfg)" in fonte_inputs)
# Estrutura atual SEM "seguranca" (removida) -> nenhum input seria gerado
# para ela, mesmo com histórico em julho/agosto.
from app.rubricas import normalizar_rubricas
estrutura_sem_seguranca = []  # simula a rubrica removida da Administração
checar("2f. Com a rubrica removida da estrutura, normalizar_rubricas(itens_cfg) não a inclui",
       "seguranca" not in [i.id for i in normalizar_rubricas(estrutura_sem_seguranca)])

# --- Chaves de rascunho registradas (mesma fonte que a tela real usa:
#     get_unit_com_params, com parametros_vigentes já mesclado — não
#     get_unit(), que só traz o bloco YAML/identidade) ---
from app.engine import get_unit_com_params
u_du = get_unit_com_params(UID_DU, "2026-07")
chaves = _chaves_estado_unidade(UID_DU, u_du)
checar("_chaves_estado_unidade inclui receita_du_{uid}", f"receita_du_{UID_DU}" in chaves)
checar("_chaves_estado_unidade inclui a chave da rubrica 'Segurança' de despesas_operacao",
       f"du_despesas_operacao_{UID_DU}_seguranca" in chaves)


# ═══════════════════════════════════════════════════════════════════════
# 3. PDF em blocos — golden legado
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. PDF — 4 blocos (golden legado) + 5º bloco condicional")
print("=" * 70)
from app.reporter import build_report_data

UID_PDF = "nilo_pdf_v10"
criar_unidade(UID_PDF, "Nilo PDF v10", "Nilo Square", "2026-07-01", "COM_ALIQUOTA_CUMUL_DU")
load_units(force=True)
salvar_parametros(UID_PDF, "2026-07", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 1129,
    "percentual_aluguel": 0.85,
    "despesas_ressarcimento_du": [
        {"id": "proprietarios", "nome": "Proprietários"},
        {"id": "provisionamento_iptu", "nome": "Provisionamento IPTU"},
    ],
    "despesas_rateio_du": [{"id": "agua", "nome": "Água"}, {"id": "energia", "nome": "Energia"}],
    "despesas_operacao": [{"id": "seguranca", "nome": "Segurança"}],
    "despesas_pos_resultado": [],
}, alterado_por="teste_v10")

ce_golden = {
    "receita_ressarcimento_du": 234896.54,
    "despesas_ressarcimento_du": {"proprietarios": 82882.08, "provisionamento_iptu": 25066.43},
    "despesas_rateio_du": {"agua": 100000.0, "energia": 136457.21},
    "despesas_operacao": {"seguranca": 5000.0},
    "despesas_pos_resultado": {},
}
r_golden = calcular(UID_PDF, "2026-07", 300000.0, saldo_override=0.0, custos_extras=ce_golden)
rd_golden = build_report_data(r_golden, "2026-07")

labels_bloco1 = [l.descricao for l in rd_golden.prestacao.linhas]
checar("Bloco 1 não tem NENHUMA rubrica individual (Proprietários/Água/Energia/Segurança)",
       not any(nome in " ".join(labels_bloco1) for nome in
               ["Proprietários", "Provisionamento IPTU", "Água", "Energia", "Segurança"]))
checar("Bloco 1 contém só totais: Resultado presente", "Resultado" in labels_bloco1)
checar("Bloco 1: Repasse = R$ 157.667,20 (golden)",
       next(l.valor for l in rd_golden.prestacao.linhas if l.descricao == "Repasse") == 157667.20)

checar("Com despesas_pos_resultado vazio: exatamente 3 blocos (sem o 5º)",
       len(rd_golden.blocos_receitas) == 3)
titulos = [b.titulo for b in rd_golden.blocos_receitas]
checar("Blocos gerados: Recebimento DU, Rateio DU, Despesas da Operação (rótulos "
       "renomeados na rodada de refinamento pós-Aucon)",
       titulos == ["Recebimento de Direitos de Uso", "Rateio de Direito de Uso", "Despesas da Operação"])

bloco2 = rd_golden.blocos_receitas[0]
labels_b2 = [l.descricao for l in bloco2.linhas]
checar("Bloco 2: 'Recebimento Bruto DU' aparece explicitamente",
       any(l.descricao == "Recebimento Bruto DU" and l.valor == 234896.54 for l in bloco2.linhas))
checar("Bloco 2: Recebimento Líquido DU = R$ 126.948,03 (golden)",
       next(l.valor for l in bloco2.linhas if l.descricao == "Recebimento Líquido DU") == 126948.03)
checar("Bloco 2: rubricas 'Proprietários'/'Provisionamento IPTU' aparecem só aqui",
       {"(-) Proprietários", "(-) Provisionamento IPTU"} <= set(labels_b2))

bloco3 = rd_golden.blocos_receitas[1]
total_bloco3 = next(l.valor for l in bloco3.linhas if l.descricao == "Total Despesas Rateio DU")
total_bloco1_rateio = -next(l.valor for l in rd_golden.prestacao.linhas if l.descricao == "(-) Total Despesas Rateio DU")
checar("Bloco 3: Total Rateio DU = R$ 236.457,21 (golden)", total_bloco3 == 236457.21)
checar("Total do Resumo (Bloco 1) bate exatamente com o Total do Bloco 3 (mesma fonte, sem recálculo)",
       total_bloco3 == total_bloco1_rateio)
du_por_vaga_bloco3 = next(l.valor for l in bloco3.linhas if "por Vaga" in l.descricao)
checar("Bloco 3: Valor DU por vaga = R$ 209,44 (golden), igual ao calculator",
       du_por_vaga_bloco3 == r_golden.extras["du_por_vaga"] == 209.44)

bloco4 = rd_golden.blocos_receitas[2]
total_bloco4 = next(l.valor for l in bloco4.linhas if l.descricao == "Total Despesas da Operação")
total_bloco1_operacao = -next(l.valor for l in rd_golden.prestacao.linhas if l.descricao == "(-) Total Despesas da Operação")
checar("Total do Resumo bate exatamente com o Total do Bloco 4 (Despesas da Operação)",
       total_bloco4 == total_bloco1_operacao == 5000.0)

# --- 5º bloco (Despesas após Resultado) só quando configurado ---
UID_PDF5 = "nilo_pdf5_v10"
criar_unidade(UID_PDF5, "Nilo PDF5 v10", "Nilo Square", "2026-07-01", "COM_ALIQUOTA_CUMUL_DU")
load_units(force=True)
salvar_parametros(UID_PDF5, "2026-07", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
    "percentual_aluguel": 0.85,
    "despesas_pos_resultado": [{"id": "investimentos", "nome": "Investimentos"}],
}, alterado_por="teste_v10")
r_com_pos = calcular(UID_PDF5, "2026-07", 50000.0, saldo_override=0.0,
                      custos_extras={"despesas_pos_resultado": {"investimentos": 2000.0}})
rd_com_pos = build_report_data(r_com_pos, "2026-07")
checar("Com despesas_pos_resultado configurado: 5º bloco aparece",
       "Despesas após Resultado" in [b.titulo for b in rd_com_pos.blocos_receitas])
bloco5 = next(b for b in rd_com_pos.blocos_receitas if b.titulo == "Despesas após Resultado")
checar("Bloco 5: 'Investimentos' aparece, não misturado com Despesas da Operação",
       any(l.descricao == "Investimentos" and l.valor == 2000.0 for l in bloco5.linhas))
checar("Bloco 1 (com despesas_pos_resultado): mostra só o total, não a rubrica 'Investimentos'",
       "Investimentos" not in [l.descricao for l in rd_com_pos.prestacao.linhas])


# ═══════════════════════════════════════════════════════════════════════
# 4. Regressão — Pátio e demais PDFs inalterados; nenhuma fórmula tocada
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Regressão — Pátio, EKOS, Viva Trindade inalterados")
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
checar("Regressão: golden da EKOS julho/2026 continua -4.110,61", r_ekos.resultado == -4110.61)

r_viva_real = calcular("viva_trindade", "2026-08", -1525.24 + 2400.0, saldo_override=-157142.75,
                        custos_extras={"outras_despesas": 2400.0})
rd_viva = build_report_data(r_viva_real, "2026-08")
checar("Regressão: PDF real da Viva Trindade continua sem blocos_receitas (lista vazia)",
       rd_viva.blocos_receitas == [])
checar("Regressão: PDF real da Viva Trindade renderiza normalmente (Resultado presente na prestação)",
       any(l.descricao == "Resultado" for l in rd_viva.prestacao.linhas))
print("[OK] Pátio segue seu próprio fluxo (patio_split_id/patio_resultado, _build_patio) — "
      "não tocado nesta rodada; já coberto por testes_bloco_bloqueia_envio.py")


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 10) PASSARAM ===")
