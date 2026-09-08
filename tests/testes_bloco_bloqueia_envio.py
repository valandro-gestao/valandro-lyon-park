"""
Cobertura permanente do bloco "bloqueia envio" (retorno da operadora após o
reprocessamento — pontos que não dependem de dado adicional):

  1. Migration 0011 — reconstrução determinística da cadeia de prejuízo
     acumulado legado (< 2026-06) de Dom Pedro e MW Tristeza, ancorada nos
     valores oficiais de saída de maio/2026. Viva Trindade e W Tower NUNCA
     são tocados por esta migração (Viva Trindade já está correta; W Tower
     não tem âncora oficial nem dados de fundo_recomposicao histórico).
  2. COM_ALIQUOTA_CUMUL — investimentos agora reduz o resultado ANTES do
     prejuízo/repasse (era uma dedução pós-repasse, "saldo_a_pagar").
     fundo_recomposicao (W Tower) continua exatamente no comportamento
     antigo — não foi tocado.
  3. PATIO_MANUTENCAO — a linha/coluna "Repasse" (redundante com Resultado,
     já que aluguel_calculado é só um valor técnico nessa calculadora) some
     de: Comparativo Mensal do PDF, Histórico Anual do PDF, Card "Valor do
     Repasse" do PDF, e "Competências anteriores" na tela — sem alterar a
     estrutura compartilhada dessas tabelas com as demais unidades (mesmo
     padrão já usado pelo template: valor None vira "—").

Seção 1 roda contra um espelho real de data/seed.db (só leitura da fonte,
gravação só no espelho temporário — scripts/migrate.py) porque data/seed.db
já contém o histórico legado real de Dom Pedro/MW Tristeza/Viva
Trindade/W Tower (com a mesma lacuna real de 2021-03 em Dom Pedro) — é o
mesmo padrão já usado pelas outras suítes desta etapa para cenários que
precisam de unidades reais.

Execução: python3 tests/testes_bloco_bloqueia_envio.py
"""
import os, sys, tempfile, shutil, atexit, json, importlib.util, subprocess

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_bloqueia_envio_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from app.models import init_db, get_db, ResultadoUnidade
from app.calculators.cumulativo import calcular_com_aliquota_cumul
from app.reporter import _prestacao_padrao, _comparativo_12m, _historico_anual

_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


_spec = importlib.util.spec_from_file_location(
    "migration_0011_teste",
    os.path.join(_REPO_ROOT, "migrations", "0011_reconstruir_historico_dom_pedro_mw_tristeza.py"),
)
_mod_0011 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod_0011)


import sqlite3


def _mirror(nome: str) -> str:
    """Sobe um espelho isolado de data/seed.db + todas as migrations
    rastreadas (inclusive a 0011) num DATA_DIR temporário próprio (processo
    filho — scripts/migrate.py). Nunca grava em data/seed.db nem em
    data/db.sqlite. Devolve o caminho do DATA_DIR do espelho."""
    tmp = tempfile.mkdtemp(prefix=f"lyon_testes_0011_{nome}_")
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    subprocess.run(
        [sys.executable, os.path.join(_REPO_ROOT, "scripts", "migrate.py")],
        env={**os.environ, "DATA_DIR": tmp}, check=True, capture_output=True,
    )
    return tmp


def _raw_conn(data_dir: str) -> sqlite3.Connection:
    """Conexão direta ao sqlite do espelho, por caminho — nunca via
    app.models.get_db()/app.paths.DATA_DIR, que são resolvidos uma única
    vez na importação do processo (mudar os.environ["DATA_DIR"] depois não
    teria efeito nenhum aqui)."""
    conn = sqlite3.connect(os.path.join(data_dir, "db.sqlite"))
    conn.row_factory = sqlite3.Row
    return conn


def _lancamento(uid, mes, data_dir):
    with _raw_conn(data_dir) as conn:
        row = conn.execute(
            "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
            (uid, mes),
        ).fetchone()
    return json.loads(row["resultado_json"]) if row else None


def _todos_lancamentos(uid, data_dir):
    with _raw_conn(data_dir) as conn:
        rows = conn.execute(
            "SELECT resultado_json FROM lancamentos WHERE unidade_id=? ORDER BY mes_referencia", (uid,)
        ).fetchall()
    return [r["resultado_json"] for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# 1. Migration 0011 — reconstrução histórica Dom Pedro / MW Tristeza
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. Migration 0011 — reconstrução histórica Dom Pedro / MW Tristeza")
print("=" * 70)

DIR_A = _mirror("principal")  # scripts/migrate.py já roda 0001..0011 em ordem

dp_jul23 = _lancamento("dom_pedro", "2023-07", DIR_A)
mw_set24 = _lancamento("mw_tristeza", "2024-09", DIR_A)
checar("Dom Pedro 2023-07 (antes positivo=734.86): aluguel_calculado agora é 0.0",
       dp_jul23["aluguel_calculado"] == 0.0)
checar("Dom Pedro 2023-07: resultado (979.81) preservado, intocado",
       dp_jul23["resultado"] == 979.81)
checar("MW Tristeza 2024-09 (antes positivo=458.13): aluguel_calculado agora é 0.0",
       mw_set24["aluguel_calculado"] == 0.0)

dp_mai26 = _lancamento("dom_pedro", "2026-05", DIR_A)
mw_mai26 = _lancamento("mw_tristeza", "2026-05", DIR_A)
checar("Dom Pedro: saída reconstruída de 2026-05 bate com a âncora oficial (-171239.32)",
       abs(dp_mai26["prejuizo_acumulado_saida"] - (-171239.32)) < 0.005)
checar("MW Tristeza: saída reconstruída de 2026-05 bate com a âncora oficial (-632029.12)",
       abs(mw_mai26["prejuizo_acumulado_saida"] - (-632029.12)) < 0.005)

checar("Dom Pedro: março/2021 continua ausente (lacuna real preservada, nada foi criado)",
       _lancamento("dom_pedro", "2021-03", DIR_A) is None)
dp_fev21 = _lancamento("dom_pedro", "2021-02", DIR_A)
dp_abr21 = _lancamento("dom_pedro", "2021-04", DIR_A)
checar("Dom Pedro: cadeia salta corretamente fev/2021 -> abr/2021 (sem mar/2021)",
       abs(dp_fev21["prejuizo_acumulado_saida"] - dp_abr21["prejuizo_acumulado_entrada"]) < 0.005)

todos_dp = [json.loads(j) for j in _todos_lancamentos("dom_pedro", DIR_A) ]
legados_dp = [d for d in todos_dp if d["mes_referencia"] < "2026-06"]
checar("Dom Pedro: nenhum mês legado tem aluguel_calculado > 0",
       all(d["aluguel_calculado"] == 0.0 for d in legados_dp))
todos_mw = [json.loads(j) for j in _todos_lancamentos("mw_tristeza", DIR_A)]
legados_mw = [d for d in todos_mw if d["mes_referencia"] < "2026-06"]
checar("MW Tristeza: nenhum mês legado tem aluguel_calculado > 0",
       all(d["aluguel_calculado"] == 0.0 for d in legados_mw))

# Viva Trindade / W Tower — intocados
viva_mai25 = _lancamento("viva_trindade", "2025-05", DIR_A)
wtower_mar22 = _lancamento("w_tower_caxias", "2022-03", DIR_A)
checar("Viva Trindade: NÃO foi tocado (fora do escopo desta migração)",
       viva_mai25 is not None and viva_mai25["aluguel_calculado"] == 0.0)
checar("W Tower: NÃO foi tocado — 2022-03 continua com o repasse legado antigo (535.56)",
       wtower_mar22["aluguel_calculado"] == 535.56)

with _raw_conn(DIR_A) as conn:
    hist_dp = conn.execute(
        "SELECT ano, dados_json FROM historico_anual WHERE unidade_id='dom_pedro' ORDER BY ano"
    ).fetchall()
dados_2023_dp = json.loads(next(r["dados_json"] for r in hist_dp if r["ano"] == 2023))
checar("historico_anual Dom Pedro 2023: repasse agregado do ano é 0.0 (todos os meses corrigidos)",
       dados_2023_dp["aluguel_calculado"] == 0.0)

# --- Preservação de campos: compara TODO mês legado contra a fonte original
#     (migrations/data/historico_lancamentos*.json — a extração real da
#     planilha, nunca tocada por esta migração) — não só um antes/depois,
#     mas a origem raiz de faturamento/resultado, e o formato hardcoded de
#     custos/extras/subtotal/PE que a migration 0002 sempre gravou.
_origem = json.load(open(os.path.join(_REPO_ROOT, "migrations", "data", "historico_lancamentos.json")))
_origem_maio = json.load(open(os.path.join(_REPO_ROOT, "migrations", "data", "historico_lancamentos_2026_05.json")))
_falhas_preservacao = []
for uid in ("dom_pedro", "mw_tristeza"):
    fonte = {r["mes_referencia"]: r for r in _origem.get(uid, [])}
    fonte[_origem_maio[uid][0]["mes_referencia"]] = _origem_maio[uid][0]
    for mes, r_fonte in fonte.items():
        atual = _lancamento(uid, mes, DIR_A)
        if atual is None:
            _falhas_preservacao.append(f"{uid}/{mes}: lançamento sumiu")
            continue
        if atual["faturamento"] != r_fonte["faturamento"]:
            _falhas_preservacao.append(f"{uid}/{mes}: faturamento mudou")
        if atual["resultado"] != (r_fonte.get("resultado") if r_fonte.get("resultado") is not None else 0.0):
            _falhas_preservacao.append(f"{uid}/{mes}: resultado mudou")
        if atual["custos"] != {}:
            _falhas_preservacao.append(f"{uid}/{mes}: custos mudou (era {{}}, agora {atual['custos']})")
        if (atual.get("extras") or {}) != {}:
            _falhas_preservacao.append(f"{uid}/{mes}: extras mudou (era {{}}, agora {atual['extras']})")
        if atual["subtotal"] != 0.0 or atual["ponto_equilibrio"] != 0.0 or atual["aliquota_imposto"] != 0.0:
            _falhas_preservacao.append(f"{uid}/{mes}: subtotal/PE/aliquota mudou")
        if atual["status"] != "aprovado":
            _falhas_preservacao.append(f"{uid}/{mes}: status mudou")
checar(f"faturamento/resultado/custos/extras/subtotal/PE/status preservados em "
       f"{len(fonte) * 2} meses legados de Dom Pedro + MW Tristeza (comparado contra a fonte original)",
       not _falhas_preservacao)
if _falhas_preservacao:
    print("    divergências:", _falhas_preservacao[:10])

# --- Lançamentos reais (>= 2026-06) nunca são alterados, mesmo coexistindo
#     na mesma unidade que tem histórico legado corrigido ao lado ----------
_SENTINELA = {"prejuizo_acumulado_entrada": -999999.0, "prejuizo_acumulado_saida": -888888.0,
              "aluguel_calculado": 12345.0, "resultado": 111.0, "faturamento": 222.0}
with _raw_conn(DIR_A) as conn:
    for uid in ("dom_pedro", "mw_tristeza"):
        dados_sentinela = {"unidade_id": uid, "mes_referencia": "2026-06", **_SENTINELA,
                            "custos": {}, "extras": {}, "status": "aprovado"}
        conn.execute(
            "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
            "VALUES (?, '2026-06', ?, ?, 'aprovado')",
            (uid, _SENTINELA["faturamento"], json.dumps(dados_sentinela)),
        )

# --- Snapshots para as confirmações de escopo, tiradas ANTES da segunda
#     chamada a apply() (idempotência) e comparadas depois -----------------
with _raw_conn(DIR_A) as conn:
    params_antes = conn.execute(
        "SELECT id, unidade_id, parametro, valor, competencia_inicio, competencia_fim "
        "FROM parametros_vigentes ORDER BY id"
    ).fetchall()
    params_antes = [tuple(r) for r in params_antes]
    hist_outras_antes = conn.execute(
        "SELECT unidade_id, ano, dados_json FROM historico_anual "
        "WHERE unidade_id IN ('viva_trindade','w_tower_caxias') ORDER BY unidade_id, ano"
    ).fetchall()
    hist_outras_antes = [tuple(r) for r in hist_outras_antes]

# --- Idempotência: chamar apply() de novo (fora do runner) não altera nada -
with _raw_conn(DIR_A) as conn:
    antes = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id IN ('dom_pedro','mw_tristeza')"
        " ORDER BY id"
    ).fetchall()
    estado_antes = [(r["id"], r["resultado_json"]) for r in antes]
    _mod_0011.apply(conn)
    depois = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id IN ('dom_pedro','mw_tristeza')"
        " ORDER BY id"
    ).fetchall()
    estado_depois = [(r["id"], r["resultado_json"]) for r in depois]
checar("idempotência: chamar apply() de novo não altera nenhuma linha", estado_antes == estado_depois)

dp_sentinela_depois = _lancamento("dom_pedro", "2026-06", DIR_A)
mw_sentinela_depois = _lancamento("mw_tristeza", "2026-06", DIR_A)
checar("Dom Pedro 2026-06 (real, sentinela) permanece exatamente como inserido — nunca tocado",
       dp_sentinela_depois["prejuizo_acumulado_entrada"] == -999999.0
       and dp_sentinela_depois["prejuizo_acumulado_saida"] == -888888.0
       and dp_sentinela_depois["aluguel_calculado"] == 12345.0)
checar("MW Tristeza 2026-06 (real, sentinela) permanece exatamente como inserido — nunca tocado",
       mw_sentinela_depois["prejuizo_acumulado_entrada"] == -999999.0
       and mw_sentinela_depois["prejuizo_acumulado_saida"] == -888888.0
       and mw_sentinela_depois["aluguel_calculado"] == 12345.0)

with _raw_conn(DIR_A) as conn:
    params_depois = conn.execute(
        "SELECT id, unidade_id, parametro, valor, competencia_inicio, competencia_fim "
        "FROM parametros_vigentes ORDER BY id"
    ).fetchall()
    params_depois = [tuple(r) for r in params_depois]
    hist_outras_depois = conn.execute(
        "SELECT unidade_id, ano, dados_json FROM historico_anual "
        "WHERE unidade_id IN ('viva_trindade','w_tower_caxias') ORDER BY unidade_id, ano"
    ).fetchall()
    hist_outras_depois = [tuple(r) for r in hist_outras_depois]
checar("parametros_vigentes: nenhuma linha alterada por apply() (âncoras da migration 0008 intocadas)",
       params_antes == params_depois)
checar("historico_anual de Viva Trindade/W Tower: nenhuma linha alterada por apply()",
       hist_outras_antes == hist_outras_depois)

# --- Validações de segurança: cada uma aborta SEM gravar nada -------------
DIR_B = _mirror("abort")
with _raw_conn(DIR_B) as conn:
    # Dom Pedro: remove 2026-05 -> "último mês legado" deixa de ser o
    # esperado -> deve abortar para esta unidade.
    conn.execute("DELETE FROM lancamentos WHERE unidade_id='dom_pedro' AND mes_referencia='2026-05'")
    # MW Tristeza: corrompe um resultado legado para forçar a cadeia
    # reconstruída a cruzar zero em algum mês -> deve abortar para esta
    # unidade (implicaria um repasse real que a operadora nega ter ocorrido).
    linha_mw = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id='mw_tristeza' AND mes_referencia='2021-06'"
    ).fetchone()
    dados_mw_corrompidos = json.loads(linha_mw["resultado_json"])
    # entrada[mês] = saída[mês] - resultado[mês]: um resultado (prejuízo)
    # absurdamente negativo força a entrada RECONSTRUÍDA do mês anterior a
    # virar positiva — exatamente o "implicaria repasse real" que a
    # validação precisa recusar a gravar.
    dados_mw_corrompidos["resultado"] = -900000.0
    conn.execute("UPDATE lancamentos SET resultado_json=? WHERE id=?",
                 (json.dumps(dados_mw_corrompidos), linha_mw["id"]))

    dp_antes = conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id='dom_pedro' ORDER BY mes_referencia"
    ).fetchall()
    mw_antes = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id='mw_tristeza' AND id != ? ORDER BY mes_referencia",
        (linha_mw["id"],)
    ).fetchall()

    _mod_0011.apply(conn)

    dp_depois = conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id='dom_pedro' ORDER BY mes_referencia"
    ).fetchall()
    mw_depois = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id='mw_tristeza' AND id != ? ORDER BY mes_referencia",
        (linha_mw["id"],)
    ).fetchall()

checar("abort (último mês legado inesperado): nenhuma linha de Dom Pedro foi alterada",
       [r["resultado_json"] for r in dp_antes] == [r["resultado_json"] for r in dp_depois])
checar("abort (cadeia implicaria repasse real): nenhuma OUTRA linha de MW Tristeza foi alterada",
       [(r["id"], r["resultado_json"]) for r in mw_antes] == [(r["id"], r["resultado_json"]) for r in mw_depois])
print()


# ═══════════════════════════════════════════════════════════════════════
# 2. COM_ALIQUOTA_CUMUL — Investimentos antes do prejuízo/repasse
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Investimentos — netado antes do prejuízo/repasse (Viva Trindade)")
print("=" * 70)

cfg_viva = {
    "id": "viva_trindade_like", "aliquota_imposto": 0.0, "percentual_aluguel": 0.85,
    "custos_variaveis": {"investimentos": 2000.0},
}

r1 = calcular_com_aliquota_cumul(cfg_viva, "2026-08", faturamento=10000.0, saldo_override=0.0)
checar("2a. resultado (bruto) permanece igual ao faturamento (sem custos/PE)", r1.resultado == 10000.0)
checar("2a. repasse calculado sobre resultado JÁ líquido de investimento (6800.0)",
       r1.aluguel_calculado == 6800.0)
checar("2a. prejuízo de saída = 0 (resultado líquido positivo)", r1.prejuizo_acumulado_saida == 0.0)
checar("2a. extras['investimentos'] = 2000.0", r1.extras.get("investimentos") == 2000.0)
checar("2a. extras NÃO tem mais 'saldo_a_pagar' (dedução pós-repasse removida)",
       "saldo_a_pagar" not in r1.extras)

r2 = calcular_com_aliquota_cumul(cfg_viva, "2026-08", faturamento=1000.0, saldo_override=0.0)
checar("2b. Resultado < Investimentos: aluguel = 0 (sem repasse)", r2.aluguel_calculado == 0.0)
checar("2b. Resultado < Investimentos: prejuízo acumulado de SAÍDA fica negativo (-1000.0)",
       r2.prejuizo_acumulado_saida == -1000.0)
checar("2b. Resultado (bruto, exibido) continua sendo o valor cheio (1000.0), não o líquido",
       r2.resultado == 1000.0)

r3 = calcular_com_aliquota_cumul(cfg_viva, "2026-08", faturamento=1500.0, saldo_override=-500.0)
checar("2c. investimento aumenta o prejuízo acumulado que já existia (-1000.0)",
       r3.prejuizo_acumulado_saida == -1000.0)

cfg_sem_invest = {"id": "sem_invest", "aliquota_imposto": 0.0, "percentual_aluguel": 0.85}
r4 = calcular_com_aliquota_cumul(cfg_sem_invest, "2026-08", faturamento=10000.0, saldo_override=0.0)
checar("2d. sem investimentos configurado: repasse sobre o resultado cheio (8500.0)",
       r4.aluguel_calculado == 8500.0)
checar("2d. sem investimentos: extras não tem a chave 'investimentos'",
       "investimentos" not in r4.extras)

print("--- 2e-2f: fundo_recomposicao (W Tower) — comportamento ANTIGO inalterado ---")
cfg_wtower = {
    "id": "w_tower_like", "aliquota_imposto": 0.0, "percentual_aluguel": 0.80,
    "custos_variaveis": {"fundo_recomposicao": 1000.0},
}
r5 = calcular_com_aliquota_cumul(cfg_wtower, "2026-08", faturamento=10000.0, saldo_override=0.0)
checar("2e. fundo_recomposicao NÃO reduz o resultado antes do repasse (aluguel = 8000.0, valor cheio)",
       r5.aluguel_calculado == 8000.0)
checar("2e. fundo_recomposicao continua gerando saldo_a_pagar (dedução pós-repasse, antiga)",
       r5.extras.get("saldo_a_pagar") == 7000.0)
checar("2e. extras['fundo_recomposicao'] presente", r5.extras.get("fundo_recomposicao") == 1000.0)

cfg_ambos = {
    "id": "ambos_like", "aliquota_imposto": 0.0, "percentual_aluguel": 0.80,
    "custos_variaveis": {"investimentos": 1000.0, "fundo_recomposicao": 500.0},
}
r6 = calcular_com_aliquota_cumul(cfg_ambos, "2026-08", faturamento=10000.0, saldo_override=0.0)
checar("2f. investimentos e fundo_recomposicao simultâneos: aluguel líquido de investimento (7200.0)",
       r6.aluguel_calculado == 7200.0)
checar("2f. investimentos e fundo_recomposicao simultâneos: saldo_a_pagar líquido de fundo (6700.0)",
       r6.extras.get("saldo_a_pagar") == 6700.0)
print()

print("--- 2g: PDF — ordem correta (Resultado -> Investimentos -> Prejuízo -> Repasse) ---")
cfg_pdf_viva = {"relatorio": {"linhas": ["resultado", "prejuizo", "aluguel"]}}
r_pdf_viva = ResultadoUnidade(
    unidade_id="viva_trindade", mes_referencia="2026-08", faturamento=10000.0,
    resultado=10000.0, prejuizo_acumulado_entrada=0.0, prejuizo_acumulado_saida=0.0,
    aluguel_calculado=6800.0, extras={"investimentos": 2000.0},
)
prestacao_viva = _prestacao_padrao(r_pdf_viva, cfg_pdf_viva)
labels_viva = [l.descricao for l in prestacao_viva.linhas]
idx_resultado = labels_viva.index("Resultado")
idx_investimentos = labels_viva.index("(-) Investimentos")
idx_prejuizo = labels_viva.index("(+/-) Prejuízo Acumulado")
idx_repasse = labels_viva.index("Repasse")
checar("2g. ordem no PDF: Resultado -> Investimentos -> Prejuízo -> Repasse",
       idx_resultado < idx_investimentos < idx_prejuizo < idx_repasse)
checar("2g. PDF NÃO mostra mais 'Saldo a Pagar' para Viva Trindade", "Saldo a Pagar" not in labels_viva)

print("--- 2h: PDF — FK/COM_ALIQUOTA (sem 'prejuizo') continua no formato ANTIGO ---")
cfg_pdf_fk = {"relatorio": {"linhas": ["resultado", "aluguel"]}}  # sem "prejuizo" — não é CUMUL
r_pdf_fk = ResultadoUnidade(
    unidade_id="fk", mes_referencia="2026-08", faturamento=10000.0,
    resultado=10000.0, aluguel_calculado=8000.0,
    extras={"investimentos": 1000.0, "saldo_a_pagar": 7000.0},
)
prestacao_fk = _prestacao_padrao(r_pdf_fk, cfg_pdf_fk)
labels_fk = [l.descricao for l in prestacao_fk.linhas]
checar("2h. FK: 'Repasse' aparece ANTES de '(-) Investimentos' (formato antigo preservado)",
       labels_fk.index("Repasse") < labels_fk.index("(-) Investimentos"))
checar("2h. FK: 'Saldo a Pagar' continua aparecendo", "Saldo a Pagar" in labels_fk)
print()


# ═══════════════════════════════════════════════════════════════════════
# 3. Pátio Manutenções — Repasse removido de Comparativo/Histórico/Tela/Card
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Pátio Manutenções — 'Repasse' removido dos componentes genéricos")
print("=" * 70)

init_db()  # DATA_DIR = _SCRATCH — patio_manutencao não tem nenhuma linha
           # real no seed.db (unidade sem histórico legado, confirmado na
           # investigação anterior), então é seguro usar o id literal aqui.

lancamentos_comp_patio = [{"mes": "2026-06", "unidade_id": "patio_manutencao",
                            "faturamento": 5000.0, "resultado": 4000.0,
                            "aluguel_calculado": 4000.0, "extras": {}}]
lancamentos_comp_outra = [{"mes": "2026-06", "unidade_id": "unidade_controle_comparativo",
                            "faturamento": 12000.0, "resultado": -400.0,
                            "aluguel_calculado": 0.0, "extras": {}}]
comp_patio = _comparativo_12m(lancamentos_comp_patio)
comp_outra = _comparativo_12m(lancamentos_comp_outra)
checar("3a. Pátio Manutenções: repasse do comparativo mensal é None", comp_patio[0].repasse is None)
checar("3a. outra unidade: repasse do comparativo mensal continua numérico (sem regressão)",
       comp_outra[0].repasse == 0.0)

with get_db() as conn:
    conn.execute(
        "INSERT INTO historico_anual (unidade_id, ano, dados_json) VALUES (?, ?, ?)",
        ("patio_manutencao", 2026, json.dumps({
            "faturamento": 5000.0, "resultado": 4000.0, "aluguel_calculado": 4000.0,
            "quantidade_meses": 1,
        })),
    )
    conn.execute(
        "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("patio_manutencao", "2026-06", 5000.0, json.dumps({
            "unidade_id": "patio_manutencao", "mes_referencia": "2026-06",
            "faturamento": 5000.0, "resultado": 4000.0, "aluguel_calculado": 4000.0,
            "extras": {},
        }), "aprovado"),
    )
r_patio_hist = ResultadoUnidade(
    unidade_id="patio_manutencao", mes_referencia="2026-07", faturamento=5200.0,
    resultado=4100.0, aluguel_calculado=4100.0,
)
historico_patio = _historico_anual("patio_manutencao", "2026-07", r_patio_hist)
linha_2026 = next(l for l in historico_patio.linhas if l.ano == 2026)
checar("3b. Histórico Anual Pátio Manutenções: coluna 'Repasse' é None",
       linha_2026.valores["Repasse"] is None)
checar("3b. Histórico Anual Pátio Manutenções: 'Faturamento'/'Resultado' continuam numéricos",
       linha_2026.valores["Faturamento"] is not None and linha_2026.valores["Resultado"] is not None)
checar("3b. Histórico Anual Pátio Manutenções: coluna 'Repasse' continua na estrutura (não removida)",
       "Repasse" in historico_patio.colunas)

with get_db() as conn:
    conn.execute(
        "INSERT INTO historico_anual (unidade_id, ano, dados_json) VALUES (?, ?, ?)",
        ("unidade_controle_historico", 2021, json.dumps({
            "faturamento": 2000.0, "resultado": -80.0, "aluguel_calculado": 15.0,
            "quantidade_meses": 2,
        })),
    )
r_controle_hist = ResultadoUnidade(unidade_id="unidade_controle_historico", mes_referencia="2021-01", faturamento=0.0)
historico_controle = _historico_anual("unidade_controle_historico", "2021-01", r_controle_hist)
linha_controle_2021 = next(l for l in historico_controle.linhas if l.ano == 2021)
checar("3b (controle). Histórico Anual de outra unidade continua com 'Repasse' numérico",
       linha_controle_2021.valores["Repasse"] == 15.0)

subprocess.run(
    [sys.executable, os.path.join(_REPO_ROOT, "scripts", "migrate.py")],
    env={**os.environ}, check=True, capture_output=True,
)
from app.reporter import build_report_data
r_patio_real = ResultadoUnidade(
    unidade_id="patio_manutencao", mes_referencia="2026-08", faturamento=5481.26,
    aliquota_imposto=0.05, subtotal=5207.20, resultado=4690.52,
    prejuizo_acumulado_entrada=0.0, prejuizo_acumulado_saida=4690.52,
    aluguel_calculado=4690.52, extras={"retencao_iss": 274.06, "saldo_acumulado": 4690.52},
)
report_patio = build_report_data(r_patio_real, "2026-08")
checar("3c. Card 'Valor do Repasse' do PDF é None para Pátio Manutenções",
       report_patio.cards.repasse is None)
checar("3c. Cards de faturamento/resultado continuam numéricos",
       report_patio.cards.faturamento == 5481.26 and report_patio.cards.resultado == 4690.52)
print()

import app.ui.fechamento as fechamento

_capturado = {}


def _fake_dataframe(df, *a, **kw):
    # _secao_historico_unificada monta o DataFrame com .set_index("Indicador")
    # antes de chamar st.dataframe — os rótulos ficam no índice, não na
    # primeira coluna (que já é o valor do mês mais recente).
    _capturado["labels"] = list(df.index)


_dataframe_original = fechamento.st.dataframe
fechamento.st.dataframe = _fake_dataframe

unit_run_vazio = {"last_generated_at": None, "last_reviewed_at": None,
                   "last_approved_at": None, "versions": []}

fechamento._secao_historico_unificada("patio_manutencao", unit_run_vazio)
labels_patio_tela = _capturado.get("labels", [])
checar("3d. Tela 'Competências anteriores' Pátio Manutenções: 'Aluguel/Repasse' NÃO aparece",
       "Aluguel/Repasse" not in labels_patio_tela)
checar("3d. Tela 'Competências anteriores' Pátio Manutenções: 'Resultado' continua aparecendo",
       "Resultado" in labels_patio_tela)

with get_db() as conn:
    conn.execute(
        "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("unidade_controle_tela", "2026-06", 1000.0, json.dumps({
            "unidade_id": "unidade_controle_tela", "mes_referencia": "2026-06",
            "faturamento": 1000.0, "resultado": 50.0, "aluguel_calculado": 40.0,
            "extras": {},
        }), "aprovado"),
    )
fechamento._secao_historico_unificada("unidade_controle_tela", unit_run_vazio)
labels_controle_tela = _capturado.get("labels", [])
checar("3d (controle). Tela de outra unidade continua mostrando 'Aluguel/Repasse' (sem regressão)",
       "Aluguel/Repasse" in labels_controle_tela)

fechamento.st.dataframe = _dataframe_original
print()


print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DO BLOCO 'BLOQUEIA ENVIO' PASSARAM ===")
