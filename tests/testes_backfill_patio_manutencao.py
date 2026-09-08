"""
Cobertura permanente do backfill histórico de Pátio Manutenções (migration
0012), a partir de migrations/data/historico_patio_manutencao.json —
extraído de "Lyon - Dados para Relatórios.xlsx" (aba "Patio Manutenção")
por scripts/extrair_patio_manutencao.py.

Cobre:
  1. As 38 competências são inseridas corretamente (2023-04 a 2026-05).
  2. Saldo acumulado final bate com a âncora oficial (-42223.85).
  3. Valores amostrais do início, meio e fim da série batem com a planilha.
  4. Nenhum lançamento existente é sobrescrito — nem quando os valores já
     batem, nem quando divergem (as duas situações só são reportadas).
  5. Junho/2026 real (>= CADEIA_SALDO_DESDE) nunca é tocado, mesmo já
     existindo lado a lado com o histórico legado sendo inserido.
  6. Idempotência: segunda execução não insere nada novo.
  7. historico_anual é reconstruído corretamente a partir dos lançamentos,
     escopado só a esta unidade.

Não lê o Excel original — usa apenas o JSON já extraído e versionado
(mesmo padrão das demais migrations desta família).

Execução: python3 tests/testes_backfill_patio_manutencao.py
"""
import os, sys, tempfile, shutil, atexit, json, importlib.util

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_backfill_patio_manutencao_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from app.models import init_db, get_db

init_db()
_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


_spec = importlib.util.spec_from_file_location(
    "migration_0012_teste",
    os.path.join(_REPO_ROOT, "migrations", "0012_backfill_historico_patio_manutencao.py"),
)
_mod_0012 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod_0012)

UID = "patio_manutencao"


def _lancamento(mes):
    with get_db() as conn:
        row = conn.execute(
            "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
            (UID, mes),
        ).fetchone()
    return json.loads(row["resultado_json"]) if row else None


def _todos_legados():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT mes_referencia FROM lancamentos WHERE unidade_id=? AND mes_referencia < '2026-06' "
            "ORDER BY mes_referencia",
            (UID,),
        ).fetchall()
    return [r["mes_referencia"] for r in rows]


# Confere que o JSON de origem (versionado, gerado pelo script de extração)
# está presente e com o formato esperado — pré-condição desta suíte.
with open(os.path.join(_REPO_ROOT, "migrations", "data", "historico_patio_manutencao.json"), encoding="utf-8") as f:
    _dados_origem = json.load(f)[UID]
checar("pré-condição: JSON de origem tem 38 competências", len(_dados_origem) == 38)


# ═══════════════════════════════════════════════════════════════════════
# 1. Sentinela de junho/2026 real — inserida ANTES do backfill, para
#    provar que a migração nunca toca uma competência >= 2026-06 mesmo
#    processando o histórico da mesma unidade ao lado dela.
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. Backfill principal — 38 competências, âncora, amostras")
print("=" * 70)

_SENTINELA_JUNHO = {
    "unidade_id": UID, "mes_referencia": "2026-06", "faturamento": 999999.0,
    "resultado": 111111.0, "prejuizo_acumulado_entrada": -1.0, "prejuizo_acumulado_saida": -2.0,
    "aluguel_calculado": 0.0, "custos": {}, "extras": {"saldo_acumulado": -2.0}, "status": "aprovado",
}
with get_db() as conn:
    conn.execute(
        "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
        "VALUES (?, '2026-06', ?, ?, 'aprovado')",
        (UID, 999999.0, json.dumps(_SENTINELA_JUNHO)),
    )

with get_db() as conn:
    _mod_0012.apply(conn)

legados = _todos_legados()
checar("38 competências legadas inseridas", len(legados) == 38)
checar("primeira competência = 2023-04", legados[0] == "2023-04")
checar("última competência = 2026-05", legados[-1] == "2026-05")

mai26 = _lancamento("2026-05")
checar("saldo acumulado final (prejuizo_acumulado_saida) bate com a âncora oficial (-42223.85)",
       mai26["prejuizo_acumulado_saida"] == -42223.85)
checar("saldo acumulado final também refletido em extras.saldo_acumulado",
       mai26["extras"]["saldo_acumulado"] == -42223.85)
checar("mês final: aluguel_calculado = 0.0 (nenhum repasse inventado)",
       mai26["aluguel_calculado"] == 0.0)

# Amostra: início, meio, fim (valores conferidos contra a planilha)
abr23 = _lancamento("2023-04")
checar("amostra início (2023-04): faturamento = 5000.0", abr23["faturamento"] == 5000.0)
checar("amostra início (2023-04): resultado = 1674.91", abr23["resultado"] == 1674.91)
checar("amostra início (2023-04): primeiro mês -> entrada = 0 (saída == resultado)",
       abr23["prejuizo_acumulado_entrada"] == 0.0 and abr23["prejuizo_acumulado_saida"] == 1674.91)

nov24 = _lancamento("2024-11")
checar("amostra meio (2024-11): faturamento = 5196.5", nov24["faturamento"] == 5196.5)
checar("amostra meio (2024-11): resultado = 1233.95", nov24["resultado"] == 1233.95)
checar("amostra meio (2024-11): saldo acumulado = -8412.89", nov24["prejuizo_acumulado_saida"] == -8412.89)
checar("amostra meio (2024-11): custos preservados (aucon/instalacoes da planilha)",
       nov24["custos"] == {"aucon": 0.0, "instalacoes": 3702.73})

checar("amostra fim (2026-05): faturamento = 5481.26", mai26["faturamento"] == 5481.26)
checar("amostra fim (2026-05): resultado = 4049.2", mai26["resultado"] == 4049.2)

# Coerência entrada/saída em toda a série (saida[mes] == entrada[mes] + resultado[mes])
# — identidade contábil de cada lançamento, exata por construção (entrada é
# sempre calculada a partir da própria saída e do próprio resultado do mês).
todos = [_lancamento(m) for m in legados]
checar("coerência entrada/saída em todos os 38 meses (entrada + resultado = saída, exato)",
       all(abs(d["prejuizo_acumulado_entrada"] + d["resultado"] - d["prejuizo_acumulado_saida"]) < 0.005
           for d in todos))
# Continuidade: saída de um mês ~= entrada do mês seguinte, com tolerância de
# 2 centavos — cada célula "Saldo Acumulado" da planilha já vem arredondada
# independentemente (a soma real é feita em precisão total dentro do
# Excel), então uma diferença de ±0,01 entre meses consecutivos é esperada
# e cosmética, não um erro de extração (ver migrations/0012, mesma
# constatação já feita por scripts/extrair_patio_manutencao.py). Sem efeito
# funcional: nenhum desses lançamentos alimenta a cadeia real de cálculo.
checar("continuidade: saída de um mês ~= entrada do mês seguinte (tolerância de arredondamento, 2 centavos)",
       all(abs(todos[i]["prejuizo_acumulado_saida"] - todos[i + 1]["prejuizo_acumulado_entrada"]) < 0.02
           for i in range(len(todos) - 1)))
checar("nenhum mês legado tem aluguel_calculado != 0 (não inventa repasse)",
       all(d["aluguel_calculado"] == 0.0 for d in todos))

# Junho/2026 (sentinela real) nunca foi tocado
junho_depois = _lancamento("2026-06")
checar("junho/2026 (sentinela real) permanece exatamente como inserido — nunca tocado",
       junho_depois["faturamento"] == 999999.0 and junho_depois["resultado"] == 111111.0
       and junho_depois["prejuizo_acumulado_saida"] == -2.0)

# historico_anual reconstruído
with get_db() as conn:
    anos_hist = conn.execute(
        "SELECT ano, dados_json FROM historico_anual WHERE unidade_id=? ORDER BY ano", (UID,)
    ).fetchall()
anos_presentes = [r["ano"] for r in anos_hist]
checar("historico_anual tem entradas para 2023, 2024, 2025 e 2026",
       set(anos_presentes) >= {2023, 2024, 2025, 2026})
dados_2023 = json.loads(next(r["dados_json"] for r in anos_hist if r["ano"] == 2023))
soma_fat_2023_esperada = round(sum(r["faturamento"] for r in _dados_origem if r["mes_referencia"].startswith("2023")), 2)
soma_res_2023_esperada = round(sum(r["resultado"] for r in _dados_origem if r["mes_referencia"].startswith("2023")), 2)
checar("historico_anual 2023: faturamento agregado bate com a soma dos 9 meses da planilha",
       dados_2023["faturamento"] == soma_fat_2023_esperada)
checar("historico_anual 2023: resultado agregado bate com a soma dos 9 meses da planilha",
       dados_2023["resultado"] == soma_res_2023_esperada)
checar("historico_anual 2023: repasse agregado = 0.0 (nenhum repasse inventado)",
       dados_2023["aluguel_calculado"] == 0.0)
dados_2026 = json.loads(next(r["dados_json"] for r in anos_hist if r["ano"] == 2026))
checar("historico_anual 2026: inclui também junho/2026 (5 meses legados + 1 real = 6)",
       dados_2026["quantidade_meses"] == 6)
print()


# ═══════════════════════════════════════════════════════════════════════
# 2. Idempotência: segunda execução não insere nada novo
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Idempotência")
print("=" * 70)
with get_db() as conn:
    antes = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id=? ORDER BY id", (UID,)
    ).fetchall()
    estado_antes = [(r["id"], r["resultado_json"]) for r in antes]
    _mod_0012.apply(conn)
    depois = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id=? ORDER BY id", (UID,)
    ).fetchall()
    estado_depois = [(r["id"], r["resultado_json"]) for r in depois]
checar("segunda execução: nenhuma linha nova, nenhuma linha alterada", estado_antes == estado_depois)
checar("segunda execução: total de linhas continua 39 (38 legadas + 1 sentinela de junho)",
       len(estado_depois) == 39)
print()


# ═══════════════════════════════════════════════════════════════════════
# 3. Nunca sobrescreve — competência já existente, IGUAL e DIVERGENTE
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Nunca sobrescreve lançamento existente (igual e divergente)")
print("=" * 70)

# app.paths.DATA_DIR é resolvido uma única vez na importação do processo —
# mudar os.environ["DATA_DIR"] depois não tem efeito em get_db(). Um
# segundo sandbox isolado precisa de um processo próprio para inicializar
# o schema (subprocess) e de uma conexão sqlite direta por caminho (nunca
# get_db()) para o resto — mesmo padrão já usado em
# testes_bloco_bloqueia_envio.py para os espelhos DIR_A/DIR_B.
import sqlite3
import subprocess

_DIR2 = tempfile.mkdtemp(prefix="lyon_testes_backfill_patio_pre_existente_")
atexit.register(shutil.rmtree, _DIR2, ignore_errors=True)
subprocess.run(
    [sys.executable, "-c", "from app.models import init_db; init_db()"],
    env={**os.environ, "DATA_DIR": _DIR2}, cwd=_REPO_ROOT, check=True, capture_output=True,
)


def _raw_conn():
    conn = sqlite3.connect(os.path.join(_DIR2, "db.sqlite"))
    conn.row_factory = sqlite3.Row
    return conn


# 3a. Uma competência já existe com valor DIVERGENTE do extraído (ex.: foi
#     lançada manualmente com um número diferente) — não deve ser
#     sobrescrita, só reportada.
_valor_divergente = {
    "unidade_id": UID, "mes_referencia": "2023-04", "faturamento": 1.0,
    "resultado": 2.0, "prejuizo_acumulado_entrada": 0.0, "prejuizo_acumulado_saida": 2.0,
    "aluguel_calculado": 0.0, "custos": {}, "extras": {"saldo_acumulado": 2.0}, "status": "aprovado",
}
# 3b. Outra competência já existe IGUAL ao que a extração produziria.
_valor_igual = {
    "unidade_id": UID, "mes_referencia": "2023-05", "faturamento": 5000.0,
    "resultado": 3627.63, "prejuizo_acumulado_entrada": 1674.91, "prejuizo_acumulado_saida": 5302.54,
    "aluguel_calculado": 0.0, "custos": {"aucon": 0.0, "instalacoes": 1122.37},
    "extras": {"retencao_iss": 250.0, "saldo_acumulado": 5302.54}, "status": "aprovado",
}
with _raw_conn() as conn:
    conn.execute(
        "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
        "VALUES (?, '2023-04', 1.0, ?, 'aprovado')",
        (UID, json.dumps(_valor_divergente)),
    )
    conn.execute(
        "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
        "VALUES (?, '2023-05', 5000.0, ?, 'aprovado')",
        (UID, json.dumps(_valor_igual)),
    )
    _mod_0012.apply(conn)

with _raw_conn() as conn:
    row_divergente = json.loads(conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia='2023-04'", (UID,)
    ).fetchone()["resultado_json"])
    row_igual = json.loads(conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia='2023-05'", (UID,)
    ).fetchone()["resultado_json"])
    total_2023_04 = conn.execute(
        "SELECT COUNT(*) c FROM lancamentos WHERE unidade_id=? AND mes_referencia='2023-04'", (UID,)
    ).fetchone()["c"]
    legados_dir2 = [r["mes_referencia"] for r in conn.execute(
        "SELECT mes_referencia FROM lancamentos WHERE unidade_id=? AND mes_referencia < '2026-06' "
        "ORDER BY mes_referencia", (UID,)
    ).fetchall()]

checar("3a. competência divergente pré-existente: valor NÃO foi sobrescrito (faturamento continua 1.0)",
       row_divergente["faturamento"] == 1.0 and row_divergente["resultado"] == 2.0)
checar("3a. competência divergente: nenhuma linha duplicada foi criada", total_2023_04 == 1)
checar("3b. competência já igual pré-existente: permanece exatamente como estava",
       row_igual["faturamento"] == 5000.0 and row_igual["resultado"] == 3627.63)
# As demais 36 competências (que não existiam) continuam sendo inseridas
# normalmente, mesmo com essas duas pré-existentes ao lado.
checar("as demais 36 competências foram inseridas normalmente (total ainda é 38)",
       len(legados_dir2) == 38)
print()


print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DO BACKFILL DE PÁTIO MANUTENÇÕES PASSARAM ===")
