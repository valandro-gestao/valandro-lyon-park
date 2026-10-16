"""
Cobertura permanente de scripts/diagnostico_split_repasse.py — o diagnóstico
READ-ONLY de Repasse x Parcela Fixa x Saldo a Pagar das unidades
RESULTADO_SPLIT (Medcenter e Viva Open Mall).

Fixture sintética, com ids reais (medcenter, viva_open_mall) para exercitar a
referência embutida, e um fenômeno por mês:

  medcenter       2024-01..05  normais (75%, parcela 80.000,00)
                  2024-06      saldo 8 centavos fora (DIVERGENCIA_CENTAVOS)
                  2026-06/07   calculados pelo sistema, com extras (75% -> 85%)
  viva_open_mall  2023-04      parcela 33.870,97 isolada (PARCELA_ATIPICA)
                  2023-05..08  regime 30.000,00 (vigência diz 32.533,36)
                  2025-03..06  regime 32.533,36 (MUDANCA_DE_PARCELA)
                  2025-07      extras.parcela_fixa divergente (DIVERGE_EXTRAS)
                  2025-08      saldo zero (SALDO_NAO_POSITIVO)
                  2025-09      status 'rascunho' (STATUS_NAO_APROVADO)
                  2026-06      sem extras após jun/2026 (SEM_EXTRAS_POS_JUN2026)
                  2026-07      extras parciais (EXTRAS_PARCIAIS)
  u_extra         vigências corrompida/sobreposta, mês sem percentual
  fk              COM_ALIQUOTA — deve ser ignorada

Garante também: estritamente read-only (banco/arquivos byte a byte idênticos,
conexão recusa escrita), só biblioteca padrão, entradas inválidas tratadas.

Execução: python3 tests/testes_diagnostico_split_repasse.py
"""
import ast, hashlib, importlib.util, json, os, sqlite3, subprocess, sys, tempfile, shutil, atexit
from pathlib import Path

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_REPO_ROOT, "scripts", "diagnostico_split_repasse.py")

_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


_TMP = tempfile.mkdtemp(prefix="lyon_testes_diag_split_")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
DB = os.path.join(_TMP, "db.sqlite")

# ── fixture ──────────────────────────────────────────────────────────────────
con = sqlite3.connect(DB)
con.executescript("""
CREATE TABLE unidades (id TEXT PRIMARY KEY, nome TEXT, contratante TEXT, ativo INTEGER, inicio TEXT,
                       tipo_calculo TEXT, tipo_relatorio TEXT);
CREATE TABLE lancamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, unidade_id TEXT NOT NULL,
    mes_referencia TEXT NOT NULL, faturamento REAL NOT NULL, resultado_json TEXT NOT NULL,
    status TEXT DEFAULT 'rascunho', criado_em TEXT DEFAULT (datetime('now')), UNIQUE(unidade_id, mes_referencia));
CREATE TABLE parametros_vigentes (id INTEGER PRIMARY KEY AUTOINCREMENT, unidade_id TEXT NOT NULL,
    parametro TEXT NOT NULL, valor TEXT NOT NULL, tipo_dado TEXT, descricao TEXT,
    competencia_inicio TEXT NOT NULL, competencia_fim TEXT,
    alterado_em TEXT DEFAULT (datetime('now')), alterado_por TEXT DEFAULT 'sistema');
CREATE TABLE historico_anual (id INTEGER PRIMARY KEY AUTOINCREMENT, unidade_id TEXT NOT NULL,
    ano INTEGER NOT NULL, dados_json TEXT NOT NULL, UNIQUE(unidade_id, ano));
""")
for uid, calc in (("medcenter", "RESULTADO_SPLIT"), ("viva_open_mall", "RESULTADO_SPLIT"),
                  ("u_extra", "RESULTADO_SPLIT"), ("fk", "COM_ALIQUOTA")):
    con.execute("INSERT INTO unidades VALUES (?,?,?,?,?,?,?)", (uid, uid, uid, 1, "2020-01-01", calc, "padrao"))


def vig(uid, parametro, valor, ini, fim=None, por="seed_yaml"):
    con.execute("INSERT INTO parametros_vigentes (unidade_id, parametro, valor, competencia_inicio, "
                "competencia_fim, alterado_por) VALUES (?,?,?,?,?,?)", (uid, parametro, json.dumps(valor), ini, fim, por))


# medcenter: exatamente a referência embutida
for p, i, f, v in [("aliquota_imposto", "2020-01", None, 0.1425), ("despesas_fixas", "2020-01", None, 42332.29),
                   ("parcela_fixa", "2020-01", None, 80000.0), ("percentual_contratante", "2020-01", "2026-06", 0.75),
                   ("percentual_contratante", "2026-07", None, 0.85), ("percentual_operador", "2020-01", None, 0.15)]:
    vig("medcenter", p, v, i, f)
# viva: referência, MENOS percentual_operador, MAIS uma vigência só em produção
for p, i, f, v in [("aliquota_imposto", "2020-01", None, 0.1425), ("despesas_fixas", "2020-01", None, 26626.96),
                   ("parcela_fixa", "2020-01", None, 32533.36), ("percentual_contratante", "2020-01", None, 0.85)]:
    vig("viva_open_mall", p, v, i, f)
vig("viva_open_mall", "despesas_fixas", 27000.0, "2026-09", None, por="aprovacao")
# u_extra: percentual com fim < início (corrompida) e parcela sobreposta
vig("u_extra", "percentual_contratante", 0.80, "2020-01", "2019-12", por="aprovacao")
vig("u_extra", "parcela_fixa", 1000.0, "2020-01", None)
vig("u_extra", "parcela_fixa", 1100.0, "2024-01", None, por="aprovacao")


def lanc(uid, mes, res, pct, parcela, extras=None, status="aprovado", saldo=None):
    repasse = round(res * pct, 2)
    saldo = round(repasse - parcela, 2) if saldo is None else saldo
    d = {"unidade_id": uid, "mes_referencia": mes, "faturamento": res * 2, "resultado": res,
         "aluguel_calculado": saldo, "extras": extras or {}, "status": status}
    con.execute("INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
                "VALUES (?,?,?,?,?)", (uid, mes, res * 2, json.dumps(d), status))
    return repasse, saldo


def extras_ok(res, pct, parcela):
    rep = round(res * pct, 2)
    return {"resultado_contratante": rep, "parcela_fixa": parcela, "saldo_a_pagar": round(rep - parcela, 2),
            "percentual_contratante": pct, "percentual_operador": 0.15}


MED = {}
for i, mes in enumerate(("2024-01", "2024-02", "2024-03", "2024-04", "2024-05")):
    MED[mes] = lanc("medcenter", mes, 150000.0 + 10000 * i, 0.75, 80000.0)
# 2024-06: saldo 8 centavos abaixo do que a parcela redonda produziria
_rep = round(200000.0 * 0.75, 2)
MED["2024-06"] = lanc("medcenter", "2024-06", 200000.0, 0.75, 0, saldo=round(_rep - 79999.92, 2))
MED["2026-06"] = lanc("medcenter", "2026-06", 210000.0, 0.75, 80000.0, extras_ok(210000.0, 0.75, 80000.0))
MED["2026-07"] = lanc("medcenter", "2026-07", 220000.0, 0.85, 80000.0, extras_ok(220000.0, 0.85, 80000.0))

VIVA = {}
VIVA["2023-04"] = lanc("viva_open_mall", "2023-04", 79857.52, 0.85, 33870.97)
for i, mes in enumerate(("2023-05", "2023-06", "2023-07", "2023-08")):
    VIVA[mes] = lanc("viva_open_mall", mes, 80000.0 + 5000 * i, 0.85, 30000.0)
for i, mes in enumerate(("2025-03", "2025-04", "2025-05", "2025-06")):
    VIVA[mes] = lanc("viva_open_mall", mes, 100000.0 + 5000 * i, 0.85, 32533.36)
_e = extras_ok(120000.0, 0.85, 30000.0)          # extras.parcela_fixa diverge da derivada (32.533,36)
VIVA["2025-07"] = lanc("viva_open_mall", "2025-07", 120000.0, 0.85, 32533.36, _e)
VIVA["2025-08"] = lanc("viva_open_mall", "2025-08", 90000.0, 0.85, 0, saldo=0.0)
VIVA["2025-09"] = lanc("viva_open_mall", "2025-09", 125000.0, 0.85, 32533.36, status="rascunho")
VIVA["2026-06"] = lanc("viva_open_mall", "2026-06", 130000.0, 0.85, 32533.36)               # sem extras
VIVA["2026-07"] = lanc("viva_open_mall", "2026-07", 140000.0, 0.85, 32533.36, {"parcela_fixa": 32533.36})

lanc("u_extra", "2024-01", 50000.0, 0.80, 1000.0)
lanc("fk", "2024-01", 50000.0, 0.80, 1000.0)

# cache desatualizado só para medcenter/2024
con.execute("INSERT INTO historico_anual (unidade_id, ano, dados_json) VALUES (?,?,?)",
            ("medcenter", 2024, json.dumps({"faturamento": 1.0, "resultado": 1.0, "aluguel_calculado": 123.0, "quantidade_meses": 6})))
con.commit()
con.close()


def _snapshot() -> dict:
    snap = {}
    for raiz, _, arquivos in os.walk(_TMP):
        for a in arquivos:
            p = os.path.join(raiz, a)
            with open(p, "rb") as f:
                snap[os.path.relpath(p, _TMP)] = (hashlib.sha256(f.read()).hexdigest(), os.stat(p).st_mtime_ns)
    return snap


def _rodar(*args):
    return subprocess.run([sys.executable, _SCRIPT, *args], capture_output=True, text=True,
                          env={**os.environ, "DATA_DIR": "/nao/existe"})


def _tsv(*args) -> dict:
    r = _rodar(*args, "--tsv")
    linhas = [l.split("\t") for l in r.stdout.splitlines() if l.strip()]
    cab, corpo = linhas[0], linhas[1:]
    return {(l[0], l[1]): dict(zip(cab, l)) for l in corpo}


def flags(t, uid, mes) -> set:
    return set(filter(None, t[(uid, mes)]["flags"].split(",")))


antes = _snapshot()
out = _rodar(DB)
t = _tsv(DB)

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1 — Escopo e execução")
print("=" * 70)
checar("1a. Executa com código 0", out.returncode == 0)
checar("1b. Analisa só as unidades RESULTADO_SPLIT (fk ignorada)",
       {u for u, _ in t} == {"medcenter", "viva_open_mall", "u_extra"})
checar("1c. Avisa que o conjunto difere do esperado (u_extra)", "AVISO" in out.stdout and "u_extra" in out.stdout)
checar("1d. TSV traz todos os lançamentos RESULTADO_SPLIT (8 + 14 + 1 = 23; fk fora)", len(t) == 23)
checar("1e. --unidades restringe a análise",
       {u for u, _ in _tsv(DB, "--unidades", "medcenter")} == {"medcenter"})

print("=" * 70)
print("2 — Reconstrução: percentual, repasse calculado, parcela derivada")
print("=" * 70)
m = t[("medcenter", "2024-03")]
checar("2a. Medcenter 2024-03: percentual 0,75 vindo da vigência", m["percentual"] == "0.7500" and m["origem_percentual"] == "vigência")
checar("2b. Repasse = round(resultado x percentual, 2)", float(m["repasse_calculado"]) == MED["2024-03"][0])
checar("2c. Parcela derivada = repasse - saldo persistido = 80.000,00", float(m["parcela_derivada"]) == 80000.00)
checar("2d. Saldo persistido é o gravado em aluguel_calculado", float(m["saldo_persistido"]) == MED["2024-03"][1])
checar("2e. Mês sem extras marcado 'nao'", m["tem_extras"] == "nao")
checar("2f. Meses normais sem nenhuma sinalização além de SEM_EXTRAS_LEGADO", flags(t, "medcenter", "2024-03") == {"SEM_EXTRAS_LEGADO"})
mj = t[("medcenter", "2026-07")]
checar("2g. Medcenter 2026-07: percentual 0,85 vindo de extras", mj["percentual"] == "0.8500" and mj["origem_percentual"] == "extras")
checar("2h. Mês com extras consistentes: COM_EXTRAS e nada mais",
       flags(t, "medcenter", "2026-06") == {"COM_EXTRAS", "LACUNA"} and flags(t, "medcenter", "2026-07") == {"COM_EXTRAS"})

print("=" * 70)
print("3 — Valores atípicos e divergências")
print("=" * 70)
checar("3a. Medcenter 2024-06: DIVERGENCIA_CENTAVOS (parcela 79.999,92)",
       "DIVERGENCIA_CENTAVOS" in flags(t, "medcenter", "2024-06") and float(t[("medcenter", "2024-06")]["parcela_derivada"]) == 79999.92)
checar("3b. Centavos de arredondamento (até R$ 0,01) NÃO são sinalizados",
       all("DIVERGENCIA_CENTAVOS" not in flags(t, "medcenter", mm) for mm in ("2024-01", "2024-02", "2024-03", "2024-04", "2024-05")))
checar("3c. Viva 2023-04: PARCELA_ATIPICA (33.870,97 fora de qualquer regime)",
       "PARCELA_ATIPICA" in flags(t, "viva_open_mall", "2023-04"))
checar("3d. Viva 2025-07: DIVERGE_EXTRAS (extras.parcela_fixa x derivada)", "DIVERGE_EXTRAS" in flags(t, "viva_open_mall", "2025-07"))
checar("3e. Viva 2025-08: SALDO_NAO_POSITIVO e parcela NÃO derivada",
       "SALDO_NAO_POSITIVO" in flags(t, "viva_open_mall", "2025-08") and t[("viva_open_mall", "2025-08")]["parcela_derivada"] == "")
checar("3f. Viva 2025-09: STATUS_NAO_APROVADO", "STATUS_NAO_APROVADO" in flags(t, "viva_open_mall", "2025-09"))
checar("3g. Viva 2026-06: SEM_EXTRAS_POS_JUN2026", "SEM_EXTRAS_POS_JUN2026" in flags(t, "viva_open_mall", "2026-06"))
checar("3h. Viva 2026-07: EXTRAS_PARCIAIS", "EXTRAS_PARCIAIS" in flags(t, "viva_open_mall", "2026-07"))
checar("3i. Medcenter 2026-06: LACUNA após 2024-06", "LACUNA" in flags(t, "medcenter", "2026-06"))
checar("3j. u_extra 2024-01: SEM_PERCENTUAL (vigência corrompida não cobre)", "SEM_PERCENTUAL" in flags(t, "u_extra", "2024-01"))

print("=" * 70)
print("4 — Regimes de parcela e vigência de parcela_fixa")
print("=" * 70)
o = out.stdout
sec3 = o.split("3. REGIMES")[1].split("4. VALORES")[0]
checar("4a. Viva: regime 30.000,00 (2023-05→2023-08) identificado", "2023-05 → 2023-08: parcela 30.000,00" in sec3)
checar("4b. Viva: regime 32.533,36 identificado", "parcela 32.533,36" in sec3)
checar("4c. Viva: MUDANÇA_DE_PARCELA 30.000,00 → 32.533,36", "MUDANÇA_DE_PARCELA" in sec3 and "30.000,00 → 32.533,36" in sec3)
checar("4d. Viva: VIGENCIA_PARCELA_DIVERGENTE (vigência 32.533,36 cobre o regime de 30.000,00)",
       "VIGENCIA_PARCELA_DIVERGENTE" in sec3 and "(2023-05…2023-08) com 32.533,36" in sec3)
checar("4e. Medcenter: regime 80.000,00 sem divergência de vigência",
       "VIGENCIA_PARCELA_DIVERGENTE" not in sec3.split("[viva_open_mall]")[0])
checar("4f. A parcela de abr/2023 NÃO vira regime (fica sinalizada)", "2023-04 →" not in sec3)

print("=" * 70)
print("5 — Vigências: produção x referência local, corrompidas e sobrepostas")
print("=" * 70)
sec1 = o.split("1. VIGÊNCIAS")[1].split("2. LANÇAMENTOS")[0]
sec_med = sec1.split("[medcenter]")[1].split("[viva_open_mall]")[0]
sec_viva = sec1.split("[viva_open_mall]")[1].split("[u_extra]")[0]
sec_extra = sec1.split("[u_extra]")[1]
checar("5a. Medcenter idêntico à referência: 0 só-produção, 0 só-referência", "0 linha(s) SÓ em produção, 0 SÓ na referência" in sec_med)
checar("5b. Viva: vigência só em produção (despesas_fixas 27000) listada", "+ produção: despesas_fixas" in sec_viva and "27000" in sec_viva)
checar("5c. Viva: vigência só na referência (percentual_operador) listada", "- referência: percentual_operador" in sec_viva)
checar("5d. u_extra: VIGENCIA_CORROMPIDA (fim < início)", "VIGENCIA_CORROMPIDA" in sec_extra)
checar("5e. u_extra: VIGENCIA_SOBREPOSTA (parcela aberta + posterior)", "VIGENCIA_SOBREPOSTA" in sec_extra)
checar("5f. u_extra: sem referência embutida — comparação não feita", "sem referência local embutida" in sec_extra)

print("=" * 70)
print("6 — Histórico anual projetado x cache")
print("=" * 70)
sec5 = o.split("5. HISTÓRICO ANUAL")[1].split("SINALIZADORES")[0]
rep24 = round(sum(MED[k][0] for k in ("2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06")), 2)
sal24 = round(sum(MED[k][1] for k in ("2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06")), 2)


def _brl(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


linha24 = next(l for l in sec5.splitlines() if l.strip().startswith("2024") and "123,00" in l)
checar("6a. Medcenter 2024: repasse projetado = Σ round(resultado x pct)", _brl(rep24) in linha24)
checar("6b. Medcenter 2024: saldo projetado = Σ aluguel_calculado persistido", _brl(sal24) in linha24)
checar("6c. Cache divergente sinalizado (Δ vs saldo Σ)", "Δ" in linha24 and "CACHE_DESATUALIZADO" in o)
sinal = o.split("SINALIZADORES")[1]
checar("6d. Sinalizadores consolidam CACHE_DESATUALIZADO medcenter/2024", "medcenter/2024" in sinal)

print("=" * 70)
print("7 — Sinalizadores")
print("=" * 70)
for classe in ("SEM_PERCENTUAL", "SALDO_NAO_POSITIVO", "DIVERGE_EXTRAS", "EXTRAS_PARCIAIS", "SEM_EXTRAS_POS_JUN2026",
               "VIGENCIA_CORROMPIDA", "VIGENCIA_SOBREPOSTA", "PARCELA_ATIPICA", "DIVERGENCIA_CENTAVOS",
               "VIGENCIA_PARCELA_DIVERGENTE", "VIGENCIAS_DIFERENTES_DO_LOCAL", "LACUNA", "STATUS_NAO_APROVADO"):
    linha_sinal = next((l for l in sinal.splitlines() if classe in l and l.strip().startswith("[")), "")
    checar(f"7a. Sinalizador {classe} acionado", linha_sinal.strip().startswith(("[!!]", "[! ]")))
checar("7b. 'Reconstruíveis' conta só meses sem extras, com percentual e saldo > 0",
       "reconstruíveis (sem extras, percentual conhecido, saldo > 0): " in sinal)
checar("7c. Fecha dizendo que NÃO corrige/migra/grava", "NÃO corrige, NÃO migra e NÃO grava nada" in o)

print("=" * 70)
print("8 — Estritamente read-only")
print("=" * 70)
depois = _snapshot()
checar("8a. Banco e arquivos byte a byte idênticos (conteúdo e mtime) depois de rodar", antes == depois)
checar("8b. Nenhum arquivo novo (nem -journal/-wal/-shm)",
       set(antes) == set(depois) and not any(n.endswith(("-journal", "-wal", "-shm")) for n in depois))
_spec = importlib.util.spec_from_file_location("diag_split", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
c = _mod.conectar_ro(Path(DB))
for nome, sql in (("INSERT", "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json) VALUES ('x','2026-05',1,'{}')"),
                  ("UPDATE", "UPDATE lancamentos SET status='x'"), ("DELETE", "DELETE FROM lancamentos"),
                  ("DROP", "DROP TABLE lancamentos")):
    try:
        c.execute(sql)
        ok = False
    except sqlite3.OperationalError:
        ok = True
    checar(f"8c. A conexão do script recusa {nome}", ok)
c.close()
with open(_SCRIPT, encoding="utf-8") as f:
    _arv = ast.parse(f.read())
_imps = {n.names[0].name.split(".")[0] for n in ast.walk(_arv) if isinstance(n, ast.Import)} | {
    n.module.split(".")[0] for n in ast.walk(_arv) if isinstance(n, ast.ImportFrom) and n.module}
checar(f"8d. Só biblioteca padrão, sem app.* (imports: {sorted(_imps)})",
       _imps <= {"argparse", "json", "os", "sqlite3", "sys", "collections", "pathlib"} and "app" not in _imps)
_escritas = [n for n in ast.walk(_arv) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and (n.func.attr in ("write_text", "write_bytes", "unlink", "rmdir", "mkdir", "rename",
                                  "remove", "executescript", "commit", "executemany")
                  # str.replace é inofensivo; só interessa os.replace / shutil.*
                  or (n.func.attr == "replace" and isinstance(n.func.value, ast.Name) and n.func.value.id in ("os", "shutil")))]
_open_w = [n for n in ast.walk(_arv) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"]
checar("8e. Sem chamadas de escrita/remoção/commit nem open() no código do script", not _escritas and not _open_w)
_sqls = [n.args[0].value for n in ast.walk(_arv) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and n.func.attr == "execute" and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)]
checar("8f. Todo SQL literal é SELECT ou PRAGMA query_only",
       all(s.lstrip().upper().startswith(("SELECT", "PRAGMA QUERY_ONLY")) for s in _sqls))

print("=" * 70)
print("9 — Entradas inválidas e esquemas incompletos")
print("=" * 70)
antes_dir = set(os.listdir(_TMP))
r2 = _rodar(os.path.join(_TMP, "nao_existe.sqlite"))
checar("9a. Banco inexistente: erro e mensagem clara", r2.returncode != 0 and "Banco não encontrado" in (r2.stderr + r2.stdout))
checar("9b. Banco inexistente: não cria arquivo", set(os.listdir(_TMP)) == antes_dir)

MIN_DB = os.path.join(_TMP, "minimo.sqlite")
cm = sqlite3.connect(MIN_DB)
cm.execute("CREATE TABLE lancamentos (id INTEGER PRIMARY KEY, unidade_id TEXT, mes_referencia TEXT, faturamento REAL, "
           "resultado_json TEXT, status TEXT)")
cm.execute("INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) VALUES "
           "('medcenter','2024-01',1,'{\"resultado\":100000,\"aluguel_calculado\":0.0,\"extras\":{}}','aprovado')")
cm.commit(); cm.close()
r3 = _rodar(MIN_DB)
checar("9c. Sem tabelas unidades/parametros_vigentes/historico_anual: não quebra, usa as unidades padrão",
       r3.returncode == 0 and "tabela `unidades` ausente" in r3.stdout and "SEM_PERCENTUAL" in r3.stdout)
r4 = _rodar(DB, "--unidades", "nao_existe")
checar("9d. Unidade sem lançamentos: não quebra", r4.returncode == 0 and "0 lançamento(s)" in r4.stdout)
checar("9e. Banco de teste ainda intacto depois das entradas inválidas", _snapshot().get("db.sqlite") == antes.get("db.sqlite"))

print()
if _falhas:
    print(f"{len(_falhas)} FALHA(S):")
    for n in _falhas:
        print("  -", n)
    sys.exit(1)
print("Todas as verificações passaram.")
