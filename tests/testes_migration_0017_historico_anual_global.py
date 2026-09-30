"""
Cobertura permanente da migration 0017 (reconstrução global emergencial de
`historico_anual` — homologação FIERGS, set/2026).

Causa raiz coberta aqui: `historico_anual` só é populado por migrations
(0006 primeiro, agora 0017), nunca "ao vivo" quando uma competência é
aprovada — então qualquer unidade com aprovações posteriores à última vez
que a reconstrução rodou fica com o cache desatualizado (caso real:
FIERGS tinha 5 meses aprovados em `lancamentos`, mas `historico_anual`
continuava congelado em 2, porque as 3 aprovações mais recentes
aconteceram depois de 0006 já ter sido aplicada em produção).

Cobre exatamente o que foi pedido para a 0017:
  1. a reconstrução passa a considerar lançamentos aprovados DEPOIS da
     última reconstrução (simula o cenário real: cache parcial + meses
     novos em `lancamentos`);
  2. múltiplas unidades e múltiplos anos na mesma execução;
  3. idempotência (segunda execução não muda nada);
  4. `lancamentos` nunca é tocado (comparação byte-a-byte antes/depois);
  5. nenhum id de unidade é hardcoded — usa unidades sintéticas
     desconhecidas do arquivo da migration;
  6. unidade sem nenhum lançamento (ex.: Pátio — Manutenções) não é
     tocada — nunca faz DELETE;
  7. a migration é descoberta e registrada normalmente pelo runner, numa
     base nova (fluxo real de deploy).

Não lê nem depende de dados reais de produção — todo o cenário usa
unidades e lançamentos sintéticos, inseridos diretamente em `lancamentos`
(sem passar por app.engine.calcular), porque o único contrato desta
migration é o formato de `resultado_json` (mesmo dict de
ResultadoUnidade.__dict__ que app.models.salvar_lancamento já grava).

Execução: python3 tests/testes_migration_0017_historico_anual_global.py
"""
import os, sys, tempfile, shutil, atexit, json, importlib.util, subprocess

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_migration_0017_")
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


MIGRATION_0017_ID = "0017_reconstruir_historico_anual_global"
_mod_0017 = _carregar_modulo(MIGRATION_0017_ID)

# Confirma, estaticamente, que o arquivo da migration não menciona nenhuma
# unidade real por nome — garante item 4 do pedido ("não hardcode valores
# nem FIERGS") por inspeção do próprio código-fonte, não só por
# comportamento observado.
with open(os.path.join(_REPO_ROOT, "migrations", f"{MIGRATION_0017_ID}.py"), encoding="utf-8") as f:
    _CODIGO_FONTE_0017 = f.read()
_CODIGO_SEM_DOCSTRING = _CODIGO_FONTE_0017.split('"""', 2)[-1]  # remove o docstring do módulo
checar("0. Código-fonte da migration (fora do docstring) não contém 'fiergs' "
       "hardcoded — reconstrução é genérica, não específica de uma unidade",
       "fiergs" not in _CODIGO_SEM_DOCSTRING.lower())


def _inserir_lancamento(conn, uid, mes, faturamento, resultado, aluguel_calculado,
                         status="aprovado", repasse_outros=0.0):
    dados = {
        "unidade_id": uid, "mes_referencia": mes, "faturamento": faturamento,
        "aliquota_imposto": 0.0, "subtotal": faturamento, "ponto_equilibrio": 0.0,
        "custos": {}, "resultado": resultado,
        "prejuizo_acumulado_entrada": 0.0, "prejuizo_acumulado_saida": 0.0,
        "aluguel_calculado": aluguel_calculado, "splits": {},
        "extras": {"repasse_outros": repasse_outros} if repasse_outros else {},
        "observacoes": "", "status": status,
    }
    conn.execute(
        "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (uid, mes, faturamento, json.dumps(dados, ensure_ascii=False), status),
    )


def _historico(conn, uid):
    rows = conn.execute(
        "SELECT ano, dados_json FROM historico_anual WHERE unidade_id=? ORDER BY ano", (uid,)
    ).fetchall()
    return {r["ano"]: json.loads(r["dados_json"]) for r in rows}


def _todos_lancamentos(conn):
    rows = conn.execute(
        "SELECT id, unidade_id, mes_referencia, faturamento, resultado_json, status, criado_em "
        "FROM lancamentos ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# Bootstrap: schema + todas as migrations ANTERIORES à 0017 (fluxo real
# de qualquer base — nunca aplica 0017 automaticamente aqui, para
# controlar exatamente o estado de `lancamentos`/`historico_anual` antes
# de chamar apply() manualmente).
# ═══════════════════════════════════════════════════════════════════════
init_db()
with get_db() as conn:
    ja_aplicadas = runner.aplicadas(conn)
    for migration_id, modulo in runner._descobrir_migracoes():
        if migration_id >= MIGRATION_0017_ID or migration_id in ja_aplicadas:
            continue
        modulo.apply(conn)
        conn.execute("INSERT INTO schema_migrations (id) VALUES (?)", (migration_id,))

UID_A = "teste_hist_global_alfa"    # nunca mencionada em nenhuma migration
UID_B = "teste_hist_global_beta"    # idem — prova de generalidade (item 4)
UID_SEM_LANCAMENTO = "teste_hist_global_sem_lancamento"  # papel do Pátio — Manutenções

with get_db() as conn:
    # ── Cenário 1 (item 5 do pedido): cache PARCIAL simulando o exato bug
    #    real — 0006/histórico anterior só viu os 2 primeiros meses; os
    #    outros 2 foram aprovados DEPOIS da última reconstrução e nunca
    #    entraram no cache.
    _inserir_lancamento(conn, UID_A, "2026-05", 171662.00, 93824.54, 79750.85)
    _inserir_lancamento(conn, UID_A, "2026-06", 215160.00, 126427.45, 109313.25)
    _inserir_lancamento(conn, UID_A, "2026-07", 141780.00, 48536.65, 41256.15)
    _inserir_lancamento(conn, UID_A, "2026-08", 735705.00, 484972.08, 439174.31)
    # cache desatualizado: só reflete mai+jun (exatamente o sintoma real do FIERGS)
    conn.execute(
        "INSERT INTO historico_anual (unidade_id, ano, dados_json) VALUES (?, ?, ?)",
        (UID_A, 2026, json.dumps({
            "faturamento": 386822.00, "resultado": 220251.99,
            "aluguel_calculado": 189064.10, "quantidade_meses": 2,
        })),
    )

    # ── Cenário 2 (item 2 do pedido): múltiplas unidades e múltiplos anos,
    #    sem NENHUM histórico_anual pré-existente (unidade nova) — inclui
    #    repasse_outros para provar que a soma de extras continua correta.
    _inserir_lancamento(conn, UID_B, "2025-11", 50000.0, 20000.0, 15000.0, repasse_outros=500.0)
    _inserir_lancamento(conn, UID_B, "2025-12", 60000.0, 25000.0, 18000.0)
    _inserir_lancamento(conn, UID_B, "2026-01", 70000.0, 30000.0, 21000.0, repasse_outros=1000.0)

    # ── Cenário 3 (item 6 do pedido): unidade SEM nenhum lançamento, mas
    #    com um histórico_anual legado pré-existente — nunca deve ser
    #    tocada (mesma regra "nunca faz DELETE" já documentada em 0006).
    conn.execute(
        "INSERT INTO historico_anual (unidade_id, ano, dados_json) VALUES (?, ?, ?)",
        (UID_SEM_LANCAMENTO, 2024, json.dumps({
            "faturamento": 1.0, "resultado": 2.0, "aluguel_calculado": 3.0,
        })),
    )

    lancamentos_antes = _todos_lancamentos(conn)

print("=" * 70)
print("1 — Reconstrução considera lançamentos posteriores à última reconstrução")
print("=" * 70)

with get_db() as conn:
    _mod_0017.apply(conn)

with get_db() as conn:
    hist_a = _historico(conn, UID_A)

checar("1a. UID_A/2026 agora tem quantidade_meses=4 (não mais 2 — os dois "
       "meses aprovados 'depois da 0006' entraram na reconstrução)",
       hist_a[2026]["quantidade_meses"] == 4)
checar("1b. UID_A/2026: faturamento agora soma os 4 meses "
       "(171.662,00+215.160,00+141.780,00+735.705,00 = 1.264.307,00)",
       hist_a[2026]["faturamento"] == 1264307.00)
checar("1c. UID_A/2026: resultado agora soma os 4 meses "
       "(93.824,54+126.427,45+48.536,65+484.972,08 = 753.760,72)",
       hist_a[2026]["resultado"] == 753760.72)
checar("1d. UID_A/2026: repasse (aluguel_calculado) agora soma os 4 meses "
       "(79.750,85+109.313,25+41.256,15+439.174,31 = 669.494,56)",
       hist_a[2026]["aluguel_calculado"] == 669494.56)


print("=" * 70)
print("2 — Múltiplas unidades e múltiplos anos na mesma execução")
print("=" * 70)

with get_db() as conn:
    hist_b = _historico(conn, UID_B)

checar("2a. UID_B tem exatamente 2 anos reconstruídos (2025 e 2026)",
       set(hist_b.keys()) == {2025, 2026})
checar("2b. UID_B/2025: quantidade_meses=2 (Nov+Dez)", hist_b[2025]["quantidade_meses"] == 2)
checar("2c. UID_B/2025: faturamento=110.000,00 (50.000+60.000)",
       hist_b[2025]["faturamento"] == 110000.0)
checar("2d. UID_B/2025: repasse inclui repasse_outros do mês com extras "
       "(15.000+500 + 18.000 = 33.500,00)", hist_b[2025]["aluguel_calculado"] == 33500.0)
checar("2e. UID_B/2026: quantidade_meses=1 (só Jan)", hist_b[2026]["quantidade_meses"] == 1)
checar("2f. UID_B/2026: repasse inclui repasse_outros (21.000+1.000 = 22.000,00)",
       hist_b[2026]["aluguel_calculado"] == 22000.0)


print("=" * 70)
print("3 — Unidade sem nenhum lançamento: histórico legado NUNCA tocado")
print("=" * 70)

with get_db() as conn:
    hist_sem = _historico(conn, UID_SEM_LANCAMENTO)

checar("3a. UID_SEM_LANCAMENTO continua com exatamente 1 registro (2024), "
       "não foi apagado nem alterado", hist_sem == {
           2024: {"faturamento": 1.0, "resultado": 2.0, "aluguel_calculado": 3.0}})


print("=" * 70)
print("4 — `lancamentos` nunca é modificado pela migration")
print("=" * 70)

with get_db() as conn:
    lancamentos_depois = _todos_lancamentos(conn)

checar("4a. Conteúdo de `lancamentos` é BYTE-A-BYTE idêntico antes/depois "
       "da migration (mesma quantidade de linhas, mesmos valores, "
       "incluindo resultado_json e criado_em)",
       lancamentos_antes == lancamentos_depois)


print("=" * 70)
print("5 — Idempotência: segunda execução não altera nada")
print("=" * 70)

with get_db() as conn:
    _mod_0017.apply(conn)
    hist_a_2 = _historico(conn, UID_A)
    hist_b_2 = _historico(conn, UID_B)
    hist_sem_2 = _historico(conn, UID_SEM_LANCAMENTO)
    lancamentos_apos_2a_execucao = _todos_lancamentos(conn)

checar("5a. UID_A: segunda execução produz exatamente o mesmo resultado",
       hist_a_2 == hist_a)
checar("5b. UID_B: segunda execução produz exatamente o mesmo resultado",
       hist_b_2 == hist_b)
checar("5c. UID_SEM_LANCAMENTO: segunda execução continua sem tocar",
       hist_sem_2 == hist_sem)
checar("5d. `lancamentos` continua intocado depois da segunda execução",
       lancamentos_apos_2a_execucao == lancamentos_antes)


# ═══════════════════════════════════════════════════════════════════════
# 6. A migration é descoberta e aplicada normalmente pelo runner numa
#    base nova (fluxo real de deploy) — sem precisar de nenhum passo
#    manual além de scripts/migrate.py / migrations.runner.run_all().
#
#    app.paths.DATA_DIR/DB_PATH são constantes resolvidas na primeira
#    importação do módulo (lidas de os.environ uma única vez) — reatribuir
#    os.environ["DATA_DIR"] no meio deste processo NÃO move get_db() para
#    outro arquivo (mesmo padrão já observado no restante da suíte, que
#    sempre usa um subprocesso/módulo novo — ex. probes de
#    streamlit.testing.v1.AppTest — para testar um DATA_DIR diferente).
#    Por isso esta seção roda num subprocesso Python novo, com DATA_DIR
#    apontando para uma base própria, garantidamente vazia.
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("6 — Descoberta/registro normal pelo runner numa base nova")
print("=" * 70)

_SCRATCH2 = tempfile.mkdtemp(prefix="lyon_testes_migration_0017_fresh_")
atexit.register(shutil.rmtree, _SCRATCH2, ignore_errors=True)

_PROBE_RUNNER = """
import os, sys, json
sys.path.insert(0, {repo_root!r})
from migrations import runner
from app.models import get_db

aplicadas_agora = runner.run_all(verbose=False)
with get_db() as conn:
    registradas = list(runner.aplicadas(conn))
segunda_rodada = runner.run_all(verbose=False)
print(json.dumps({{
    "aplicadas_agora": aplicadas_agora,
    "registradas": registradas,
    "segunda_rodada": segunda_rodada,
}}))
""".format(repo_root=_REPO_ROOT)

_env_probe = dict(os.environ)
_env_probe["DATA_DIR"] = _SCRATCH2
_resultado_probe = subprocess.run(
    [sys.executable, "-c", _PROBE_RUNNER],
    cwd=_REPO_ROOT, env=_env_probe, capture_output=True, text=True, timeout=120,
)
checar("6a0. Subprocesso com DATA_DIR novo roda sem exceção",
       _resultado_probe.returncode == 0)
if _resultado_probe.returncode != 0:
    print(_resultado_probe.stdout)
    print(_resultado_probe.stderr)
    _saida_probe = {"aplicadas_agora": [], "registradas": [], "segunda_rodada": ["__erro__"]}
else:
    _saida_probe = json.loads(_resultado_probe.stdout.strip().splitlines()[-1])

checar("6a. Numa base nova, run_all() aplica a 0017 junto com as demais",
       MIGRATION_0017_ID in _saida_probe["aplicadas_agora"])
checar("6b. 0017 fica registrada em schema_migrations",
       MIGRATION_0017_ID in _saida_probe["registradas"])
checar("6c. Rodar run_all() de novo não reaplica a 0017 (já registrada)",
       MIGRATION_0017_ID not in _saida_probe["segunda_rodada"])


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA MIGRATION 0017 PASSARAM ===")
