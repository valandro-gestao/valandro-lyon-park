"""
Cobertura permanente da correção do histórico legado de W Tower Caxias
(migration 0013), a partir de migrations/data/historico_wtower.json —
extraído de "Lyon - Dados para Relatórios.xlsx" (aba "W-Tower Caxias") por
scripts/extrair_wtower.py.

Cobre:
  1. Estado pré-existente (migrations 0001-0012) reproduz os valores
     conhecidos como errados (repasse indevido em prejuízo, virada sem
     desconto do excedente, Fundo de Recomposição nunca descontado).
  2. Depois de 0013: dezembro/2023 (ainda em prejuízo), janeiro/2024
     (virada, repasse parcial sobre o excedente), fevereiro/2024 (já
     correto, sem mudança), junho/2024 (primeiro mês com Fundo), março/2025
     (último mês com Fundo), abril/2025 (sem Fundo) — todos com os valores
     exatos confirmados pela operadora.
  3. Exatamente 10 competências têm Fundo de Recomposição.
  4. aluguel_calculado preservado como valor BRUTO nos meses com Fundo;
     saldo_a_pagar = aluguel_calculado - fundo_recomposicao.
  5. Nenhum lançamento de 2021 é alterado.
  6. Nenhum lançamento >= 2026-06 é alterado (sentinela).
  7. Idempotência: segunda execução não altera nada.
  8. historico_anual reconstruído considerando o Fundo (repasse líquido).
  9. Validação defensiva: se `resultado` de um lançamento não bater com o
     JSON de origem, a migração inteira aborta sem gravar nada.
  10. Campos preservados (faturamento, subtotal, custos, observações,
      status) em todos os lançamentos tocados.

Não lê o Excel original — usa apenas o JSON já extraído e versionado, e as
migrations 0001-0012 (via migrations.runner) para reconstruir o estado
pré-existente realista, exatamente como o sistema real chega a esse ponto.

Execução: python3 tests/testes_correcao_wtower.py
"""
import os, sys, tempfile, shutil, atexit, json, importlib.util

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_correcao_wtower_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from app.models import init_db, get_db
from migrations import runner

_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


def _carregar_modulo(migration_id):
    caminho = os.path.join(_REPO_ROOT, "migrations", f"{migration_id}.py")
    spec = importlib.util.spec_from_file_location(f"{migration_id}_teste", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIGRATION_0013_ID = "0013_corrigir_historico_wtower"
_mod_0013 = _carregar_modulo(MIGRATION_0013_ID)

UID = "w_tower_caxias"


def _lancamento(mes):
    with get_db() as conn:
        row = conn.execute(
            "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
            (UID, mes),
        ).fetchone()
    return json.loads(row["resultado_json"]) if row else None


def _todos(mes_min="2022-01", mes_max="2026-05"):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT mes_referencia, resultado_json FROM lancamentos WHERE unidade_id=? "
            "AND mes_referencia >= ? AND mes_referencia <= ? ORDER BY mes_referencia",
            (UID, mes_min, mes_max),
        ).fetchall()
    return {r["mes_referencia"]: json.loads(r["resultado_json"]) for r in rows}


with open(os.path.join(_REPO_ROOT, "migrations", "data", "historico_wtower.json"), encoding="utf-8") as f:
    _dados_origem = json.load(f)[UID]
_por_mes_origem = {r["mes_referencia"]: r for r in _dados_origem}
checar("pré-condição: JSON de origem tem 53 competências (2022-01..2026-05)", len(_dados_origem) == 53)

FUNDO_MESES = [
    "2024-06", "2024-07", "2024-08", "2024-09", "2024-10", "2024-11", "2024-12",
    "2025-01", "2025-02", "2025-03",
]


# ═══════════════════════════════════════════════════════════════════════
# 0. Reconstrói o estado pré-existente real (migrations 0001-0012) —
#    mesma sequência que o sistema real já aplicou em produção.
# ═══════════════════════════════════════════════════════════════════════
init_db()
with get_db() as conn:
    # init_db() já semeia a partir de data/seed.db (app.paths.seed_db_if_missing),
    # que só tem 0001-0004 registradas em schema_migrations — as demais
    # (0005-0012) precisam ser aplicadas aqui, como em qualquer ambiente
    # novo. Nunca reaplica uma que já veio pronta do seed.
    ja_aplicadas = runner.aplicadas(conn)
    for migration_id, modulo in runner._descobrir_migracoes():
        if migration_id >= MIGRATION_0013_ID or migration_id in ja_aplicadas:
            continue
        modulo.apply(conn)
        conn.execute("INSERT INTO schema_migrations (id) VALUES (?)", (migration_id,))

    # Sentinela de junho/2026 real — inserida ANTES de 0013, para provar
    # que a correção nunca toca uma competência >= 2026-06 mesmo
    # processando o histórico da mesma unidade ao lado dela.
    _SENTINELA_JUNHO = {
        "unidade_id": UID, "mes_referencia": "2026-06", "faturamento": 999999.0,
        "resultado": 111111.0, "prejuizo_acumulado_entrada": -1.0, "prejuizo_acumulado_saida": -2.0,
        "aluguel_calculado": 888888.0, "custos": {}, "extras": {}, "status": "aprovado",
    }
    conn.execute(
        "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
        "VALUES (?, '2026-06', ?, ?, 'aprovado')",
        (UID, 999999.0, json.dumps(_SENTINELA_JUNHO)),
    )


print("=" * 70)
print("1. Estado pré-existente (antes de 0013) reproduz os bugs conhecidos")
print("=" * 70)
_antes = _todos()
checar("pré-existente: dez/2023 já mostra repasse indevido (aluguel_calculado = 6905.54)",
       _antes["2023-12"]["aluguel_calculado"] == 6905.54)
checar("pré-existente: jan/2024 calculado sobre o resultado cheio (aluguel_calculado = 11366.88)",
       _antes["2024-01"]["aluguel_calculado"] == 11366.88)
checar("pré-existente: jun/2024 sem Fundo em extras (bug ainda não corrigido)",
       "fundo_recomposicao" not in (_antes["2024-06"].get("extras") or {}))
_antes_2021_02 = _lancamento("2021-02")
checar("pré-existente: 2021-02 existe e aluguel_calculado = 0.0", _antes_2021_02["aluguel_calculado"] == 0.0)
print()


# ═══════════════════════════════════════════════════════════════════════
# 2. Aplica 0013 e valida os valores exatos confirmados pela operadora
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Aplicação de 0013 — valores exatos por competência")
print("=" * 70)
with get_db() as conn:
    _mod_0013.apply(conn)

dez23 = _lancamento("2023-12")
checar("dez/2023: ainda em prejuízo, aluguel_calculado corrigido para 0.0", dez23["aluguel_calculado"] == 0.0)
checar("dez/2023: prejuizo_acumulado_saida = -6867.96", dez23["prejuizo_acumulado_saida"] == -6867.96)
checar("dez/2023: resultado preservado (8631.93)", dez23["resultado"] == 8631.93)

jan24 = _lancamento("2024-01")
checar("jan/2024: virada — prejuizo_acumulado_entrada = -6867.96 (saída de dez/2023)",
       jan24["prejuizo_acumulado_entrada"] == -6867.96)
checar("jan/2024: prejuizo_acumulado_saida = 0.0 (não o excedente +7340.64)",
       jan24["prejuizo_acumulado_saida"] == 0.0)
checar("jan/2024: repasse parcial sobre o excedente = 5872.51 (não 11366.88, 80% do resultado cheio)",
       jan24["aluguel_calculado"] == 5872.51)
checar("jan/2024: nenhum Fundo de Recomposição (fora da janela jun/2024-mar/2025)",
       "fundo_recomposicao" not in (jan24.get("extras") or {}))

fev24 = _lancamento("2024-02")
checar("fev/2024: já estava correto — aluguel_calculado inalterado (6166.03)",
       fev24["aluguel_calculado"] == 6166.03)
checar("fev/2024: prejuizo_acumulado_saida = 0.0 (permanece zerado)", fev24["prejuizo_acumulado_saida"] == 0.0)

jun24 = _lancamento("2024-06")
checar("jun/2024 (primeiro mês com Fundo): aluguel_calculado bruto preservado (3614.77)",
       jun24["aluguel_calculado"] == 3614.77)
checar("jun/2024: extras.fundo_recomposicao = 717.38 (positivo, convenção do sistema)",
       jun24["extras"]["fundo_recomposicao"] == 717.38)
checar("jun/2024: extras.saldo_a_pagar = 2897.39 (= aluguel_calculado - fundo_recomposicao)",
       jun24["extras"]["saldo_a_pagar"] == 2897.39
       and abs(jun24["extras"]["saldo_a_pagar"] - (jun24["aluguel_calculado"] - jun24["extras"]["fundo_recomposicao"])) < 0.005)

mar25 = _lancamento("2025-03")
checar("mar/2025 (último mês com Fundo): aluguel_calculado bruto preservado (7133.35)",
       mar25["aluguel_calculado"] == 7133.35)
checar("mar/2025: extras.fundo_recomposicao = 717.38", mar25["extras"]["fundo_recomposicao"] == 717.38)
checar("mar/2025: extras.saldo_a_pagar = 6415.97", mar25["extras"]["saldo_a_pagar"] == 6415.97)

abr25 = _lancamento("2025-04")
checar("abr/2025 (primeiro mês sem Fundo depois da janela): aluguel_calculado = 6732.26",
       abr25["aluguel_calculado"] == 6732.26)
checar("abr/2025: sem fundo_recomposicao/saldo_a_pagar em extras",
       "fundo_recomposicao" not in (abr25.get("extras") or {})
       and "saldo_a_pagar" not in (abr25.get("extras") or {}))
print()


# ═══════════════════════════════════════════════════════════════════════
# 3. Exatamente 10 competências com Fundo; janela completa
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Janela do Fundo de Recomposição — exatamente 10 meses")
print("=" * 70)
_depois = _todos()
_com_fundo = [m for m, d in _depois.items() if "fundo_recomposicao" in (d.get("extras") or {})]
checar("exatamente 10 competências com Fundo de Recomposição", sorted(_com_fundo) == FUNDO_MESES)
checar("todos os 10 meses com Fundo = 717.38 exatamente",
       all(_depois[m]["extras"]["fundo_recomposicao"] == 717.38 for m in FUNDO_MESES))
checar("todos os 10 meses: saldo_a_pagar = aluguel_calculado - fundo_recomposicao (exato)",
       all(abs(_depois[m]["extras"]["saldo_a_pagar"]
               - (_depois[m]["aluguel_calculado"] - _depois[m]["extras"]["fundo_recomposicao"])) < 0.005
           for m in FUNDO_MESES))
print()


# ═══════════════════════════════════════════════════════════════════════
# 4. Nunca toca 2021 nem >= 2026-06
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Nunca toca 2021 nem >= 2026-06")
print("=" * 70)
_depois_2021_02 = _lancamento("2021-02")
checar("2021-02: nenhum campo alterado (idêntico ao pré-existente)", _depois_2021_02 == _antes_2021_02)
_depois_junho26 = _lancamento("2026-06")
checar("2026-06 (sentinela real, >= CADEIA_SALDO_DESDE): permanece exatamente como inserido",
       _depois_junho26 == _SENTINELA_JUNHO)
print()


# ═══════════════════════════════════════════════════════════════════════
# 5. Campos não relacionados preservados em todos os lançamentos tocados
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5. Campos preservados (faturamento, subtotal, custos, resultado, status)")
print("=" * 70)
_preserva_ok = True
for mes in _antes:
    a, d = _antes[mes], _depois[mes]
    if (a["faturamento"] != d["faturamento"] or a.get("subtotal") != d.get("subtotal")
            or a.get("custos") != d.get("custos") or a["resultado"] != d["resultado"]
            or a.get("observacoes") != d.get("observacoes") or a.get("status") != d.get("status")):
        _preserva_ok = False
        print(f"  divergência inesperada em {mes}")
checar("faturamento/subtotal/custos/resultado/observações/status preservados em todas as 53 competências",
       _preserva_ok)
print()


# ═══════════════════════════════════════════════════════════════════════
# 6. historico_anual — repasse líquido (considera o Fundo)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("6. historico_anual reconstruído com repasse líquido")
print("=" * 70)
with get_db() as conn:
    anos_hist = {r["ano"]: json.loads(r["dados_json"]) for r in conn.execute(
        "SELECT ano, dados_json FROM historico_anual WHERE unidade_id=? ORDER BY ano", (UID,)
    ).fetchall()}

soma_bruta_2024 = round(sum(_por_mes_origem[m]["aluguel_calculado"]
                             for m in _por_mes_origem if m.startswith("2024")), 2)
fundo_2024 = round(sum(717.38 for m in FUNDO_MESES if m.startswith("2024")), 2)
esperado_liquido_2024 = round(soma_bruta_2024 - fundo_2024, 2)
checar(f"historico_anual 2024: repasse líquido = {esperado_liquido_2024} (bruto {soma_bruta_2024} - Fundo {fundo_2024})",
       anos_hist[2024]["aluguel_calculado"] == esperado_liquido_2024)

soma_bruta_2025 = round(sum(_por_mes_origem[m]["aluguel_calculado"]
                             for m in _por_mes_origem if m.startswith("2025")), 2)
fundo_2025 = round(sum(717.38 for m in FUNDO_MESES if m.startswith("2025")), 2)
esperado_liquido_2025 = round(soma_bruta_2025 - fundo_2025, 2)
checar(f"historico_anual 2025: repasse líquido = {esperado_liquido_2025} (bruto {soma_bruta_2025} - Fundo {fundo_2025})",
       anos_hist[2025]["aluguel_calculado"] == esperado_liquido_2025)

checar("historico_anual 2022: repasse = 0.0 (unidade em prejuízo o ano inteiro)",
       anos_hist[2022]["aluguel_calculado"] == 0.0)
checar("historico_anual 2023: repasse = 0.0 (unidade em prejuízo o ano inteiro)",
       anos_hist[2023]["aluguel_calculado"] == 0.0)
checar("historico_anual 2026: inclui o real de junho (5 legados + 1 real = 6 meses)",
       anos_hist[2026]["quantidade_meses"] == 6)
print()


# ═══════════════════════════════════════════════════════════════════════
# 7. Idempotência
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("7. Idempotência")
print("=" * 70)
with get_db() as conn:
    antes_2a = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id=? ORDER BY id", (UID,)
    ).fetchall()
    estado_antes_2a = [(r["id"], r["resultado_json"]) for r in antes_2a]
    _mod_0013.apply(conn)
    depois_2a = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id=? ORDER BY id", (UID,)
    ).fetchall()
    estado_depois_2a = [(r["id"], r["resultado_json"]) for r in depois_2a]
    anos_hist_2a = {r["ano"]: r["dados_json"] for r in conn.execute(
        "SELECT ano, dados_json FROM historico_anual WHERE unidade_id=? ORDER BY ano", (UID,)
    ).fetchall()}
checar("segunda execução: nenhuma linha de lancamentos alterada", estado_antes_2a == estado_depois_2a)
checar("segunda execução: historico_anual recalculado para o mesmo resultado",
       {a: json.loads(v) for a, v in anos_hist_2a.items()} == anos_hist)
print()


# ═══════════════════════════════════════════════════════════════════════
# 8. Validação defensiva: resultado divergente do JSON aborta tudo
# ═══════════════════════════════════════════════════════════════════════
# app.paths.DATA_DIR é resolvido uma única vez na importação do processo —
# mudar os.environ["DATA_DIR"] depois não tem efeito em get_db(). Um
# segundo sandbox isolado precisa de um processo próprio para construir o
# estado pré-0013 (subprocess) e de uma conexão sqlite direta por caminho
# (nunca get_db()) para corromper um valor e aplicar 0013 — mesmo padrão já
# usado em testes_backfill_patio_manutencao.py (seção 3) e
# testes_bloco_bloqueia_envio.py.
print("=" * 70)
print("8. Validação defensiva — resultado divergente aborta a migração inteira")
print("=" * 70)
import sqlite3
import subprocess

_DIR2 = tempfile.mkdtemp(prefix="lyon_testes_correcao_wtower_abortar_")
atexit.register(shutil.rmtree, _DIR2, ignore_errors=True)
_SETUP_PRE_0013 = (
    "from app.models import init_db, get_db\n"
    "from migrations import runner\n"
    "init_db()\n"
    "with get_db() as conn:\n"
    "    ja_aplicadas = runner.aplicadas(conn)\n"
    "    for migration_id, modulo in runner._descobrir_migracoes():\n"
    f"        if migration_id >= {MIGRATION_0013_ID!r} or migration_id in ja_aplicadas:\n"
    "            continue\n"
    "        modulo.apply(conn)\n"
    "        conn.execute('INSERT INTO schema_migrations (id) VALUES (?)', (migration_id,))\n"
)
subprocess.run(
    [sys.executable, "-c", _SETUP_PRE_0013],
    env={**os.environ, "DATA_DIR": _DIR2}, cwd=_REPO_ROOT, check=True, capture_output=True,
)


def _raw_conn():
    conn = sqlite3.connect(os.path.join(_DIR2, "db.sqlite"))
    conn.row_factory = sqlite3.Row
    return conn


with _raw_conn() as conn:
    # Corrompe o resultado de um único mês, simulando uma competência que
    # não corresponde de verdade à mesma fonte do JSON.
    row = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia='2024-06'", (UID,)
    ).fetchone()
    dados_corrompidos = json.loads(row["resultado_json"])
    dados_corrompidos["resultado"] = 999999.0
    conn.execute("UPDATE lancamentos SET resultado_json=? WHERE id=?",
                 (json.dumps(dados_corrompidos), row["id"]))
    _mod_0013.apply(conn)

with _raw_conn() as conn:
    estado_pos_abortar = {r["mes_referencia"]: json.loads(r["resultado_json"]) for r in conn.execute(
        "SELECT mes_referencia, resultado_json FROM lancamentos WHERE unidade_id=? "
        "AND mes_referencia >= '2022-01' AND mes_referencia <= '2026-05'", (UID,)
    ).fetchall()}

checar("resultado corrompido em 2024-06 permanece (nada foi revertido nem sobrescrito às cegas)",
       estado_pos_abortar["2024-06"]["resultado"] == 999999.0)
checar("nenhum OUTRO mês foi corrigido (jan/2024 continua com o valor bugado, migração abortou inteira)",
       estado_pos_abortar["2024-01"]["aluguel_calculado"] == 11366.88)
checar("dez/2023 também continua com o bug (nada foi gravado nesta execução abortada)",
       estado_pos_abortar["2023-12"]["aluguel_calculado"] == 6905.54)
print()


print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DA CORREÇÃO DE W TOWER PASSARAM ===")
