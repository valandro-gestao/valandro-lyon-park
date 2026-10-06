"""
Cobertura permanente da homologação set/2026 — 4ª rodada (fechamento de
Setembro/2026).

Dois defeitos técnicos confirmados + um ajuste de feedback operacional:

  1. Rubricas mensais (Viva Trindade — outras_despesas / investimentos):
     um 0.0 informado na competência é ZERO, nunca "buscar fallback em
     parametros_vigentes". Antes, `== 0.0` era tratado como "não
     informado" e uma vigência legada (outras_despesas = 2.400 / 2026-08 /
     aberta / alterado_por='aprovacao', criada por aprovações anteriores a
     a7ab174) contaminava Setembro mesmo com o campo zerado na tela.
     + migration 0018 neutraliza o dado legado sem tocar `lancamentos`.
  2. `aucon_codigo_filial` é configuração ESTRUTURAL — única fonte de
     verdade: `unidades.aucon_codigo_filial`. Não é semeado/copiado para
     parametros_vigentes; lote e botão individual leem a mesma coluna; um
     código antigo em parametros_vigentes nunca tem precedência.
  3. Sem código de filial, a tela da unidade mostra um aviso discreto
     (caption — nunca warning/error), sem botão "Atualizar faturamento" e
     sem impedir o preenchimento manual; isso nunca se confunde com
     "Aucon consultado e retornou R$ 0,00".

  4. (fechamento da rodada) Contrato ÚNICO para rubricas mensais — também em
     COM_ALIQUOTA (FK/In 1183): ausente ou 0.0 = zero, nunca herda vigência.
     Administração não edita mais o VALOR de Investimentos/Outras Despesas
     por vigência: só liga/desliga o campo (`tem_investimentos`/
     `tem_outras_despesas`); registros históricos ficam preservados.

Nenhuma chamada real à API Aucon — a camada de busca é substituída por
funções fake controladas pelo teste.

Execução: python3 tests/testes_homologacao_set2026_v12.py
"""
import os, sys, json, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v12_")
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
    get_aucon_codigo_filial, get_parametros_vigentes, carregar_rascunho_unidade,
    salvar_lancamento, get_db, _extrair_editaveis,
)
from app.engine import calcular, load_units, get_unit, get_unit_com_params
import app.ui.fechamento as fech
from app.integrations import aucon_client
from app.integrations.aucon_client import AuconResultado
from streamlit.testing.v1 import AppTest


def _linhas_param(uid, parametro):
    with get_db() as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT valor, competencia_inicio, competencia_fim, alterado_por "
            "FROM parametros_vigentes WHERE unidade_id=? AND parametro=? "
            "ORDER BY competencia_inicio, id", (uid, parametro))]


def _snapshot(tabela):
    with get_db() as conn:
        return [tuple(r) for r in conn.execute(f"SELECT * FROM {tabela} ORDER BY 1, 2")]


OD = "custos_variaveis.outras_despesas"
INV = "custos_variaveis.investimentos"
VT = "viva_trindade"

# ═══════════════════════════════════════════════════════════════════════
# 1. Rubricas mensais — 0.0 explícito é zero; não-zero continua valendo;
#    ausente também é zero; agosto histórico intocado
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1 — rubricas mensais (outras_despesas / investimentos): zero explícito é zero")
print("=" * 70)

# Agosto histórico da Viva, aprovado COM 2.400 de outras despesas — exatamente
# o que a operadora fechou em produção.
r_ago = calcular(VT, "2026-08", 48674.03, custos_extras={"outras_despesas": 2400.0, "investimentos": 0.0})
r_ago.status = "aprovado"
salvar_lancamento(r_ago)

# Referência LIMPA de Setembro (sem nenhuma vigência legada).
CE_ZERO = {"outras_despesas": 0.0, "investimentos": 0.0}
r_set_limpo = calcular(VT, "2026-09", 50000.0, custos_extras=dict(CE_ZERO))
checar("1a. Referência: Setembro limpo (campo 0) não tem outras_despesas em extras",
       "outras_despesas" not in (r_set_limpo.extras or {}))

# Reproduz o dado legado de produção: aprovar Agosto, antes de a7ab174,
# varria o valor digitado para uma vigência nova e ABERTA.
salvar_parametros(VT, "2026-08", {"custos_variaveis": {"outras_despesas": 2400.0}}, alterado_por="aprovacao")
checar("1b. Dado legado reproduzido: vigência outras_despesas=2400 / 2026-08 / aberta / aprovacao",
       ("2400.0", "2026-08", None, "aprovacao") in _linhas_param(VT, OD))
checar("1c. ...e ela de fato vaza para Setembro em get_parametros_vigentes (a contaminação existe no dado)",
       get_parametros_vigentes(VT, "2026-09")["custos_variaveis"]["outras_despesas"] == 2400.0)

r_set = calcular(VT, "2026-09", 50000.0, custos_extras=dict(CE_ZERO))
checar("1d. outras_despesas=0 EXPLÍCITO permanece zero mesmo com vigência antiga de 2.400 "
       "(resultado de Setembro idêntico ao limpo)",
       r_set.resultado == r_set_limpo.resultado and "outras_despesas" not in (r_set.extras or {}))
checar("1e. ...e o repasse/prejuízo de Setembro também idênticos ao limpo",
       r_set.aluguel_calculado == r_set_limpo.aluguel_calculado
       and r_set.prejuizo_acumulado_saida == r_set_limpo.prejuizo_acumulado_saida)

r_set_1500 = calcular(VT, "2026-09", 50000.0, custos_extras={"outras_despesas": 1500.0, "investimentos": 0.0})
checar("1f. Valor mensal diferente de zero continua funcionando (1.500 reduz o resultado em 1.500)",
       r_set_1500.extras.get("outras_despesas") == 1500.0
       and round(r_set_limpo.resultado - r_set_1500.resultado, 2) == 1500.0)

r_set_sem_chave = calcular(VT, "2026-09", 50000.0, custos_extras={"investimentos": 0.0})
checar("1g. Chave ausente em custos_extras também vale 0 (nunca herda a vigência legada)",
       r_set_sem_chave.resultado == r_set_limpo.resultado)

# investimentos — mesma semântica (COM_ALIQUOTA_CUMUL)
# vigência legada de investimentos (mesma classe de vazamento)
salvar_parametros(VT, "2026-08", {"custos_variaveis": {"investimentos": 5000.0}}, alterado_por="aprovacao")
r_inv0 = calcular(VT, "2026-09", 50000.0, custos_extras=dict(CE_ZERO))
checar("1h. investimentos=0 explícito permanece zero mesmo com vigência antiga de 5.000 (CUMUL)",
       r_inv0.resultado == r_set_limpo.resultado
       and r_inv0.aluguel_calculado == r_set_limpo.aluguel_calculado
       and "investimentos" not in (r_inv0.extras or {}))
r_inv3 = calcular(VT, "2026-09", 50000.0, custos_extras={"outras_despesas": 0.0, "investimentos": 3000.0})
# (a Viva tem prejuízo acumulado alto: o aluguel é 0 nos dois casos — o
# investimento aparece como aumento do prejuízo de saída, regra v1.2.0)
checar("1i. investimentos não-zero continua funcionando (CUMUL): 3.000 a mais de prejuízo de saída",
       r_inv3.extras.get("investimentos") == 3000.0
       and round(r_set_limpo.prejuizo_acumulado_saida - r_inv3.prejuizo_acumulado_saida, 2) == 3000.0)

# COM_ALIQUOTA (base.py — FK / In 1183): mesmo fallback "== 0.0" corrigido.
FK = "in_1183"
salvar_parametros(FK, "2026-08", {"custos_variaveis": {"investimentos": 3000.0}}, alterado_por="aprovacao")
fk_zero = calcular(FK, "2026-09", 80000.0, custos_extras={"investimentos": 0.0})
checar("1j. COM_ALIQUOTA: investimentos=0 explícito não herda vigência de 3.000 (sem saldo_a_pagar)",
       "investimentos" not in (fk_zero.extras or {}) and "saldo_a_pagar" not in (fk_zero.extras or {}))
fk_ausente = calcular(FK, "2026-09", 80000.0, custos_extras={})
checar("1l. COM_ALIQUOTA: chave ausente também vale 0 (contrato único: nunca herda a vigência de 3.000)",
       "investimentos" not in (fk_ausente.extras or {}) and "saldo_a_pagar" not in (fk_ausente.extras or {}))
fk_inv = calcular(FK, "2026-09", 80000.0, custos_extras={"investimentos": 1200.0})
checar("1k. COM_ALIQUOTA: investimentos não-zero continua gerando saldo_a_pagar",
       fk_inv.extras.get("investimentos") == 1200.0
       and fk_inv.extras.get("saldo_a_pagar") == round(fk_inv.aluguel_calculado - 1200.0, 2))

# ═══════════════════════════════════════════════════════════════════════
# 2. Migration 0018 — neutraliza a vigência legada, sem tocar lançamentos
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2 — migration 0018: vigência legada neutralizada, agosto histórico intacto")
print("=" * 70)

# Cenários extras de dado legado, para provar o critério e a idempotência.
# (a) leak com fim > início (2026-10 → 2026-12) em unidade COM_ALIQUOTA
salvar_parametros(FK, "2026-10", {"custos_variaveis": {"investimentos": 800.0}}, alterado_por="aprovacao")
salvar_parametros(FK, "2027-01", {"custos_variaveis": {"investimentos": 0.0}}, alterado_por="aprovacao")
# (b) unidade RESULTADO_SPLIT (custos_variaveis é mapa de rubricas — NÃO é tocada)
VOM = "viva_open_mall"
salvar_parametros(VOM, "2026-08", {"custos_variaveis": {"investimentos": 500.0}}, alterado_por="aprovacao")
# (c) vigência não-zero de outra origem (Administração) — só reportada
salvar_parametros("anitta_mall", "2026-08", {"custos_variaveis": {"outras_despesas": 700.0}}, alterado_por="usuario_admin")

# zera o registro de aplicação para o runner de verdade aplicar a 0018 sobre
# este estado (fluxo real de deploy: scripts/migrate.py).
_lanc_antes = _snapshot("lancamentos")
with get_db() as conn:
    conn.execute("DELETE FROM schema_migrations WHERE id LIKE '0018_%'")
_antes_vom = _linhas_param(VOM, INV)
_antes_anitta = _linhas_param("anitta_mall", OD)
aplicadas = runner.run_all(verbose=False)
checar("2a. runner descobre e aplica a 0018 normalmente", any(a.startswith("0018_") for a in aplicadas))

checar("2b. Viva: a vigência de Agosto foi limitada ao próprio mês (2400 / 2026-08 → 2026-08)",
       ("2400.0", "2026-08", "2026-08", "aprovacao") in _linhas_param(VT, OD))
checar("2c. Viva: Setembro em diante passa a 0.0 (linha migration_0018, aberta)",
       ("0.0", "2026-09", None, "migration_0018") in _linhas_param(VT, OD))
v_set = get_parametros_vigentes(VT, "2026-09")["custos_variaveis"]
checar("2d. Viva: a chave outras_despesas continua EXISTINDO em Setembro (o campo do Fechamento depende disso) e vale 0",
       v_set.get("outras_despesas") == 0.0 and v_set.get("investimentos") == 0.0)
checar("2e. Viva: Agosto continua vigente com 2.400 (valor auditável na competência em que foi digitado)",
       get_parametros_vigentes(VT, "2026-08")["custos_variaveis"]["outras_despesas"] == 2400.0)
checar("2f. Viva: nenhuma competência futura (2026-09 até 2030-12) herda mais um valor não-zero de outras_despesas/investimentos",
       all(get_parametros_vigentes(VT, f"{a}-{m:02d}")["custos_variaveis"].get("outras_despesas", 0.0) == 0.0
           and get_parametros_vigentes(VT, f"{a}-{m:02d}")["custos_variaveis"].get("investimentos", 0.0) == 0.0
           for a in range(2026, 2031) for m in range(1, 13) if f"{a}-{m:02d}" >= "2026-09"))

checar("2g. Agosto histórico NÃO é alterado: `lancamentos` idêntico byte-a-byte antes/depois",
       _snapshot("lancamentos") == _lanc_antes)
ago = json.loads(next(r for r in _lanc_antes if r[1] == VT and r[2] == "2026-08")[4])
checar("2h. ...e o Agosto da Viva segue com extras.outras_despesas = 2.400",
       ago["extras"]["outras_despesas"] == 2400.0)
checar("2i. A migration recupera o valor de Agosto para o widget de reabertura (_valor_ja_lancado = 2.400)",
       fech._valor_ja_lancado(VT, "2026-08", "outras_despesas") == 2400.0)

# (a) fim > início: limita ao mês e cobre o resto do período original com 0.0
checar("2j. COM_ALIQUOTA: leak 800 de 2026-10 (fim original 2026-12) limitado a 2026-10",
       ("800.0", "2026-10", "2026-10", "aprovacao") in _linhas_param(FK, INV))
checar("2k. ...e 2026-11→2026-12 (resto do período original) fica 0.0",
       ("0.0", "2026-11", "2026-12", "migration_0018") in _linhas_param(FK, INV))
# (b)/(c) fora do critério: intocadas
checar("2l. Unidade de outro tipo (RESULTADO_SPLIT, custos_variaveis = mapa de rubricas) NÃO é tocada",
       _linhas_param(VOM, INV) == _antes_vom)
checar("2m. Vigência não-zero de outra origem (Administração) NÃO é tocada (só reportada)",
       _linhas_param("anitta_mall", OD) == _antes_anitta)

# idempotência: segunda execução não muda nada
_params_antes = _snapshot("parametros_vigentes")
with get_db() as conn:
    conn.execute("DELETE FROM schema_migrations WHERE id LIKE '0018_%'")
runner.run_all(verbose=False)
checar("2n. Idempotente: reaplicar a 0018 não altera parametros_vigentes",
       _snapshot("parametros_vigentes") == _params_antes)
checar("2o. ...nem lancamentos", _snapshot("lancamentos") == _lanc_antes)

# ═══════════════════════════════════════════════════════════════════════
# 3. Fluxo real Setembro da Viva (Fechamento, AppTest): campo zerado → 0
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3 — Fechamento de Setembro da Viva (AppTest): campo 0,00 não deduz 2.400")
print("=" * 70)

_PROBE_COUNTER = [0]
_PROBE_PATHS: list[str] = []
atexit.register(lambda: [os.remove(p) for p in _PROBE_PATHS if os.path.exists(p)])


def _abrir_fechamento(uid: str, mes_ref: str) -> AppTest:
    _PROBE_COUNTER[0] += 1
    path = os.path.join(_REPO_ROOT, "tests", f"_probe_v12_{_PROBE_COUNTER[0]}.py")
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
    at = AppTest.from_file(path, default_timeout=90)
    at.run()
    return at


def _valor(at, label_sub):
    return next(n.value for n in at.number_input if label_sub in n.label)


def _legendas(at):
    return [c.value for c in at.caption]


# Estado legado de volta (como estava em produção ANTES da migration) para
# provar que, mesmo sem a migration aplicada, o cálculo já não é contaminado.
with get_db() as conn:
    conn.execute("UPDATE parametros_vigentes SET competencia_fim=NULL WHERE unidade_id=? AND parametro=? "
                 "AND alterado_por='aprovacao'", (VT, OD))
    conn.execute("DELETE FROM parametros_vigentes WHERE unidade_id=? AND parametro=? AND alterado_por='migration_0018'",
                 (VT, OD))
checar("3a. Estado legado restaurado: vigência 2400 aberta de novo",
       get_parametros_vigentes(VT, "2026-09")["custos_variaveis"]["outras_despesas"] == 2400.0)

at = _abrir_fechamento(VT, "2026-09")
checar("3b. Tela de Setembro: Outras Despesas (R$) = 0,00 (default vem do lançamento da competência, não da vigência)",
       _valor(at, "Outras Despesas") == 0.0)
next(n for n in at.number_input if "Faturamento" in n.label).set_value(50000.0)
at.run()
next(b for b in at.button if b.label == "Calcular").click()
at.run()
next(b for b in at.button if b.label == "Aprovar").click()
at.run()
checar("3c. Setembro aprovado sem exceção", len(at.exception) == 0)
with get_db() as conn:
    row = conn.execute("SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia='2026-09'",
                       (VT,)).fetchone()
set_json = json.loads(row["resultado_json"])
esperado = calcular(VT, "2026-09", 50000.0, custos_extras=dict(CE_ZERO))
checar("3d. Lançamento de Setembro NÃO deduz os 2.400 (sem extras.outras_despesas; resultado = referência limpa)",
       "outras_despesas" not in (set_json.get("extras") or {}) and set_json["resultado"] == esperado.resultado)

# ═══════════════════════════════════════════════════════════════════════
# 4. aucon_codigo_filial — fonte única (unidades.aucon_codigo_filial)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4 — aucon_codigo_filial: fonte única, sem cópia em parametros_vigentes")
print("=" * 70)

MES = "2026-09"
UID_A = "v12_aucon_a"       # com código
UID_B = "v12_aucon_b"       # sem código
UID_Z = "v12_aucon_zero"    # com código, API devolve R$ 0,00
for uid, nome in [(UID_A, "V12 A"), (UID_B, "V12 B"), (UID_Z, "V12 Zero")]:
    criar_unidade(uid, nome, "Contratante Teste", "2020-01-01", "PERCENTUAL_SIMPLES")
    salvar_parametros(uid, MES, {"percentual_aluguel": 0.10, "ponto_equilibrio": 0.0}, alterado_por="teste_v12")
definir_aucon_codigo_filial(UID_A, 25)
definir_aucon_codigo_filial(UID_Z, 77)
load_units(force=True)

checar("4a. _extrair_editaveis não captura aucon_codigo_filial (é estrutural)",
       "aucon_codigo_filial" not in (lambda d: (_extrair_editaveis({"aucon_codigo_filial": 25, "ponto_equilibrio": 1.0}, d), d)[1])({}))

u_a = get_unit_com_params(UID_A, MES)   # abre a unidade — antes, isto semeava o código em parametros_vigentes
checar("4b. Abrir a unidade NÃO semeia aucon_codigo_filial em parametros_vigentes",
       _linhas_param(UID_A, "aucon_codigo_filial") == [])
checar("4c. A aprovação (varredura de parâmetros usados) NÃO grava aucon_codigo_filial",
       "aucon_codigo_filial" not in fech._coletar_params_usados(UID_A, u_a, None, {}))
checar("4d. O código da tela da unidade vem da coluna `unidades` (25)", u_a["aucon_codigo_filial"] == 25)

# Código ANTIGO legado em parametros_vigentes (cópia semeada por versões anteriores)
with get_db() as conn:
    conn.execute("INSERT INTO parametros_vigentes (unidade_id, parametro, valor, competencia_inicio, alterado_por) "
                 "VALUES (?, 'aucon_codigo_filial', '24', '2026-01', 'seed_yaml')", (UID_A,))   # vigência MAIS RECENTE que a semeada: venceria na mescla
u_stale = get_unit_com_params(UID_A, MES)
checar("4e. Código antigo em parametros_vigentes (24) NÃO tem precedência sobre a coluna (25)",
       u_stale["aucon_codigo_filial"] == 25)

# lote e individual consultam EXATAMENTE a mesma coluna
_chamadas: list = []


def _fake_busca(codigo_filial, mes_ref):
    _chamadas.append(codigo_filial)
    return AuconResultado(codigo_filial=codigo_filial, valor=1234.56, bruto=1234.56,
                          cancelados=0.0, importado_em="2026-10-06 10:00:00")


def _reset(uid):
    for k in list(st.session_state.keys()):
        if k == f"fat_{uid}" or k.startswith("_aucon_"):
            del st.session_state[k]
    with get_db() as conn:
        conn.execute("DELETE FROM rascunhos_unidade WHERE unidade_id=? AND mes_referencia=?", (uid, MES))


_orig_busca = aucon_client.buscar_faturamento_aucon
aucon_client.buscar_faturamento_aucon = _fake_busca
try:
    # `u` deliberadamente com um código desatualizado (24) — o serviço não pode usá-lo.
    _reset(UID_A); _chamadas.clear()
    st_ind, _ = fech._importar_faturamento_aucon(UID_A, MES, {"id": UID_A, "aucon_codigo_filial": 24})
    codigo_individual = list(_chamadas)
    _reset(UID_A); _chamadas.clear()
    fech._buscar_faturamentos_aucon_lote(MES, [{"id": UID_A, "aucon_codigo_filial": 24}])
    codigo_lote = list(_chamadas)
    checar("4f. Individual e lote consultam o MESMO código — o da coluna (25), não o de `u`/parametros_vigentes (24)",
           codigo_individual == [25] and codigo_lote == [25] and st_ind == "ok")

    # alteração no Admin vale imediatamente para ambos (sem reiniciar/recarregar cache)
    definir_aucon_codigo_filial(UID_A, 26)
    _reset(UID_A); _chamadas.clear()
    fech._importar_faturamento_aucon(UID_A, MES, get_unit(UID_A))          # get_unit() ainda cacheado com 25
    cod_ind_2 = list(_chamadas)
    _reset(UID_A); _chamadas.clear()
    fech._buscar_faturamentos_aucon_lote(MES, [get_unit(UID_A)])
    cod_lote_2 = list(_chamadas)
    checar("4g. Alterar o código na coluna (Admin) vale imediatamente para lote E individual (26)",
           cod_ind_2 == [26] and cod_lote_2 == [26])
    definir_aucon_codigo_filial(UID_A, 25)

    # ausência de código: fora da integração
    _reset(UID_B); _chamadas.clear()
    st_b, det_b = fech._importar_faturamento_aucon(UID_B, MES, get_unit(UID_B))
    fech._buscar_faturamentos_aucon_lote(MES, [get_unit(UID_B)])
    checar("4h. Sem código: individual retorna erro e NENHUMA chamada à Aucon; lote ignora a unidade",
           st_b == "erro" and _chamadas == [] and carregar_rascunho_unidade(UID_B, MES) is None)
    checar("4i. get_aucon_codigo_filial: sem código = None; limpar o código (None) também tira a unidade da integração",
           get_aucon_codigo_filial(UID_B) is None)
    definir_aucon_codigo_filial(UID_A, None)
    _reset(UID_A); _chamadas.clear()
    fech._buscar_faturamentos_aucon_lote(MES, [get_unit(UID_A)])
    checar("4j. Desvincular (None) na Admin remove a unidade do lote imediatamente",
           _chamadas == [] and get_aucon_codigo_filial(UID_A) is None)
    definir_aucon_codigo_filial(UID_A, 25)
finally:
    aucon_client.buscar_faturamento_aucon = _orig_busca

# ═══════════════════════════════════════════════════════════════════════
# 5. Feedback na tela da unidade: com código / sem código / código + zero
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5 — tela da unidade: sem código, com código, código + retorno R$ 0,00")
print("=" * 70)
MSG_SEM_CODIGO = "ⓘ Aucon não configurado — código da filial não cadastrado."

# 5.1 SEM código
_reset(UID_B)
at_b = _abrir_fechamento(UID_B, MES)
checar("5a. Sem código: mostra o aviso discreto, como caption",
       MSG_SEM_CODIGO in _legendas(at_b))
checar("5b. Sem código: o aviso NÃO é warning/error",
       all(MSG_SEM_CODIGO not in w.value for w in list(at_b.warning) + list(at_b.error)))
checar("5c. Sem código: NÃO oferece o botão 'Atualizar faturamento'",
       not any(b.label == "Atualizar faturamento" for b in at_b.button))
checar("5d. Sem código: não aparece nenhuma legenda de importação Aucon",
       not any("via Aucon" in c or "importado via Aucon" in c for c in _legendas(at_b)))
next(n for n in at_b.number_input if "Faturamento" in n.label).set_value(4321.0)
at_b.run()
checar("5e. Sem código: o preenchimento manual do faturamento NÃO é impedido",
       _valor(at_b, "Faturamento") == 4321.0 and len(at_b.exception) == 0)
checar("5f. Sem código: o rascunho guarda o valor manual e nenhuma metadata Aucon",
       (carregar_rascunho_unidade(UID_B, MES) or {}).get(f"fat_{UID_B}") == 4321.0
       and "_aucon_meta" not in (carregar_rascunho_unidade(UID_B, MES) or {}))

# 5.2 COM código (ainda nunca importado) — comportamento atual preservado
_reset(UID_A)
at_a = _abrir_fechamento(UID_A, MES)
checar("5g. Com código: NÃO mostra o aviso de 'não configurado'", MSG_SEM_CODIGO not in _legendas(at_a))
checar("5h. Com código: oferece 'Atualizar faturamento'", any(b.label == "Atualizar faturamento" for b in at_a.button))
checar("5i. Com código: legenda atual preservada ('Ainda não importado via Aucon.')",
       "Ainda não importado via Aucon." in _legendas(at_a))

# 5.3 COM código + Aucon consultado e retornou R$ 0,00 — NÃO é "sem código"
def _fake_zero(codigo_filial, mes_ref):
    return AuconResultado(codigo_filial=codigo_filial, valor=0.0, bruto=0.0, cancelados=0.0,
                          importado_em="2026-10-06 11:00:00")


aucon_client.buscar_faturamento_aucon = _fake_zero
try:
    _reset(UID_Z)
    at_z = _abrir_fechamento(UID_Z, MES)
    next(b for b in at_z.button if b.label == "Atualizar faturamento").click()
    at_z.run()
finally:
    aucon_client.buscar_faturamento_aucon = _orig_busca
draft_z = carregar_rascunho_unidade(UID_Z, MES) or {}
checar("5j. Código + retorno zero: a consulta aconteceu e ficou registrada (meta com valor_importado = 0,00 e filial 77)",
       draft_z.get("_aucon_meta", {}).get("valor_importado") == 0.0
       and draft_z.get("_aucon_meta", {}).get("codigo_filial_usado") == 77
       and draft_z.get(f"fat_{UID_Z}") == 0.0)
checar("5k. Código + retorno zero: NÃO mostra o aviso 'Aucon não configurado'",
       MSG_SEM_CODIGO not in _legendas(at_z))
checar("5l. Código + retorno zero: o botão 'Atualizar faturamento' continua disponível",
       any(b.label == "Atualizar faturamento" for b in at_z.button))
checar("5m. Código + retorno zero: mostra a legenda de consulta ('Atualizado via Aucon em ...'), distinta do aviso de ausência",
       any(c.startswith("Atualizado via Aucon em") for c in _legendas(at_z)))
checar("5n. Sem exceções em nenhum dos três cenários",
       len(at_a.exception) == 0 and len(at_b.exception) == 0 and len(at_z.exception) == 0)


# ═══════════════════════════════════════════════════════════════════════
# 6. Administração: rubricas mensais deixam de ser parâmetros por vigência;
#    o campo no Fechamento é decidido pelas chaves tem_* (não por linha antiga)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("6 — Administração e visibilidade do campo (tem_investimentos / tem_outras_despesas)")
print("=" * 70)
from app.calculadora_schema import campos_do_tipo, rubricas_mensais_ativas

for tipo, tem_chaves in (("COM_ALIQUOTA", {"tem_investimentos"}),
                         ("COM_ALIQUOTA_CUMUL", {"tem_investimentos", "tem_outras_despesas"})):
    chaves = {c["chave"] for c in campos_do_tipo(tipo)}
    checar(f"6a. {tipo}: a Administração NÃO edita mais o valor de investimentos/outras_despesas por vigência",
           not ({"custos_variaveis.investimentos", "custos_variaveis.outras_despesas"} & chaves))
    checar(f"6b. {tipo}: a Administração liga/desliga o campo ({sorted(tem_chaves)})",
           tem_chaves <= chaves)
checar("6c. fundo_recomposicao (W Tower) segue editável por vigência em COM_ALIQUOTA_CUMUL",
       "custos_variaveis.fundo_recomposicao" in {c["chave"] for c in campos_do_tipo("COM_ALIQUOTA_CUMUL")})

# Registros históricos preservados (nada foi apagado por 0018/0019)
with get_db() as conn:
    n_hist_vt = conn.execute("SELECT COUNT(*) c FROM parametros_vigentes WHERE unidade_id=? "
                             "AND parametro IN (?,?)", (VT, OD, INV)).fetchone()["c"]
checar("6d. Registros históricos de outras_despesas/investimentos da Viva continuam no banco (auditoria)",
       n_hist_vt >= 4)

# Viva e FK: campos ligados (YAML + migration) — widgets presentes, valor 0,00 por padrão
u_vt = get_unit_com_params(VT, "2026-10")
checar("6e. Viva Trindade: ambas as rubricas ligadas (tem_outras_despesas e tem_investimentos)",
       rubricas_mensais_ativas("COM_ALIQUOTA_CUMUL", u_vt) == ["outras_despesas", "investimentos"])
at_vt = _abrir_fechamento(VT, "2026-10")
rot_vt = [n.label for n in at_vt.number_input]
checar("6f. Fechamento da Viva mostra Outras Despesas e Investimentos, ambos 0,00",
       any("Outras Despesas" in r for r in rot_vt) and any("Investimentos" in r for r in rot_vt)
       and _valor(at_vt, "Outras Despesas") == 0.0 and _valor(at_vt, "Investimentos") == 0.0)
at_fk = _abrir_fechamento("fk", "2026-10")
checar("6g. COM_ALIQUOTA (FK): mostra Investimentos (tem_investimentos) e NÃO mostra Outras Despesas",
       any("Investimentos" in n.label for n in at_fk.number_input)
       and not any("Outras Despesas" in n.label for n in at_fk.number_input))

# Unidade CUMUL sem as chaves, MESMO com linha histórica no banco: campo oculto
# (a presença de uma linha antiga deixou de decidir qualquer coisa).
UID_S = "a_schneider"
with get_db() as conn:
    conn.execute("INSERT INTO parametros_vigentes (unidade_id, parametro, valor, competencia_inicio, alterado_por) "
                 "VALUES (?, 'custos_variaveis.investimentos', '0.0', '2020-01', 'legado')", (UID_S,))
checar("6h. Pré-condição: a_schneider tem linha histórica de investimentos mas NÃO tem tem_investimentos",
       get_unit_com_params(UID_S, "2026-10").get("tem_investimentos") is not True)
at_s = _abrir_fechamento(UID_S, "2026-10")
checar("6i. ...e o Fechamento NÃO mostra Investimentos nem Outras Despesas (linha antiga não decide)",
       not any(("Investimentos" in n.label or "Outras Despesas" in n.label) for n in at_s.number_input)
       and len(at_s.exception) == 0)

# Ligar pela Administração (chave tem_investimentos) faz o campo aparecer, e o valor da competência vale
salvar_parametros(UID_S, "2026-10", {"tem_investimentos": True}, alterado_por="admin_teste")
at_s2 = _abrir_fechamento(UID_S, "2026-10")
checar("6j. Ligar tem_investimentos na Administração faz o campo aparecer no Fechamento (0,00)",
       any("Investimentos" in n.label for n in at_s2.number_input) and _valor(at_s2, "Investimentos") == 0.0)
next(n for n in at_s2.number_input if "Faturamento" in n.label).set_value(30000.0)
at_s2.run()
next(n for n in at_s2.number_input if "Investimentos" in n.label).set_value(1000.0)
at_s2.run()
next(b for b in at_s2.button if b.label == "Calcular").click()
at_s2.run()
next(b for b in at_s2.button if b.label == "Aprovar").click()
at_s2.run()
with get_db() as conn:
    j_s = json.loads(conn.execute("SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia='2026-10'",
                                  (UID_S,)).fetchone()["resultado_json"])
checar("6k. Valor mensal digitado (1.000) é aplicado e fica congelado no lançamento da competência",
       j_s["extras"].get("investimentos") == 1000.0 and len(at_s2.exception) == 0)
with get_db() as conn:
    n_sweep = conn.execute("SELECT COUNT(*) c FROM parametros_vigentes WHERE unidade_id=? AND parametro=? "
                           "AND alterado_por='aprovacao'", (UID_S, INV)).fetchone()["c"]
checar("6l. Aprovar NÃO varre o valor mensal de volta para parametros_vigentes", n_sweep == 0)

# ═══════════════════════════════════════════════════════════════════════
# 7. Migration 0019 — preserva a visibilidade atual (linha histórica -> tem_*)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("7 — migration 0019: unidades que já exibem o campo continuam exibindo")
print("=" * 70)
UID_M = "v12_mig19_cumul"       # CUMUL criada só pela Administração, com linhas históricas
UID_N = "v12_mig19_off"         # CUMUL com tem_investimentos EXPLICITAMENTE false (não pode ser religada)
UID_O = "v12_mig19_outro_tipo"  # RESULTADO_SPLIT (custos_variaveis = mapa de rubricas): fora de escopo
for uid, tipo in ((UID_M, "COM_ALIQUOTA_CUMUL"), (UID_N, "COM_ALIQUOTA_CUMUL"), (UID_O, "RESULTADO_SPLIT")):
    criar_unidade(uid, uid, "Contratante Teste", "2020-01-01", tipo)
salvar_parametros(UID_M, "2026-01", {"custos_variaveis": {"investimentos": 0.0, "outras_despesas": 0.0}}, alterado_por="admin_teste")
salvar_parametros(UID_N, "2026-01", {"custos_variaveis": {"investimentos": 0.0}, "tem_investimentos": False}, alterado_por="admin_teste")
salvar_parametros(UID_O, "2026-01", {"custos_variaveis": {"investimentos": 100.0}}, alterado_por="admin_teste")
load_units(force=True)
_lanc_19 = _snapshot("lancamentos")
_hist_antes = {(u, p): _linhas_param(u, p) for u in (UID_M, UID_N, UID_O) for p in (OD, INV)}
with get_db() as conn:
    conn.execute("DELETE FROM schema_migrations WHERE id LIKE '0019_%'")
aplicadas19 = runner.run_all(verbose=False)
checar("7a. runner descobre e aplica a 0019", any(a.startswith("0019_") for a in aplicadas19))
checar("7b. CUMUL com linhas históricas ganha tem_investimentos e tem_outras_despesas = true",
       get_unit_com_params(UID_M, "2026-10").get("tem_investimentos") is True
       and get_unit_com_params(UID_M, "2026-10").get("tem_outras_despesas") is True)
checar("7c. Escolha explícita (tem_investimentos=false) NÃO é sobrescrita",
       get_unit_com_params(UID_N, "2026-10").get("tem_investimentos") is False)
checar("7d. Outro tipo de cálculo (mapa de rubricas) NÃO é tocado",
       not _linhas_param(UID_O, "tem_investimentos"))
checar("7e. Nenhum registro histórico de outras_despesas/investimentos foi alterado ou apagado",
       all(_linhas_param(u, p) == _hist_antes[(u, p)] for (u, p) in _hist_antes))
checar("7f. lancamentos intacto", _snapshot("lancamentos") == _lanc_19)
_params_19 = _snapshot("parametros_vigentes")
with get_db() as conn:
    conn.execute("DELETE FROM schema_migrations WHERE id LIKE '0019_%'")
runner.run_all(verbose=False)
checar("7g. Idempotente: reaplicar a 0019 não altera parametros_vigentes", _snapshot("parametros_vigentes") == _params_19)


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 12) PASSARAM ===")
