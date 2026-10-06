"""
Cobertura permanente de scripts/diagnostico_aprovacao_inconsistente.py — o
diagnóstico READ-ONLY de unidades com workflow `aprovado` sem lançamento
`aprovado` correspondente (defeito dos antigos atalhos de aprovação só de
workflow).

Garante que o script:
  1. classifica corretamente SEM_LANCAMENTO, LANCAMENTO_NAO_APROVADO e SEM_PDF,
     sem acusar unidades consistentes e sem tratar gerado/reaberto como erro;
  2. lista como INFORMATIVO (não inconsistência) lançamento aprovado com
     workflow não aprovado;
  3. é estritamente read-only: banco e arquivos byte a byte idênticos depois
     de rodar, nenhum arquivo novo criado, e a conexão recusa escrita;
  4. não importa `app.*` (sem init_db/seed) e usa só biblioteca padrão;
  5. falha com mensagem clara (sem criar nada) quando o banco não existe, e
     reporta — sem abortar — um status.json ilegível.

Execução: python3 tests/testes_diagnostico_aprovacao_inconsistente.py
"""
import ast, hashlib, importlib.util, json, os, re, sqlite3, subprocess, sys, tempfile, shutil, atexit

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_REPO_ROOT, "scripts", "diagnostico_aprovacao_inconsistente.py")

_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


_TMP = tempfile.mkdtemp(prefix="lyon_testes_diag_aprov_")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
DB = os.path.join(_TMP, "db.sqlite")
RUNS = os.path.join(_TMP, "runs")

# ── fixture: banco mínimo (só a tabela que o script lê) + runs ──────────────
con = sqlite3.connect(DB)
con.execute("""CREATE TABLE lancamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, unidade_id TEXT NOT NULL,
    mes_referencia TEXT NOT NULL, faturamento REAL NOT NULL,
    resultado_json TEXT NOT NULL, status TEXT DEFAULT 'rascunho',
    criado_em TEXT DEFAULT (datetime('now')), UNIQUE(unidade_id, mes_referencia))""")
for uid, mes, status in [
    ("u_ok", "2026-05", "aprovado"),
    ("u_sem_pdf", "2026-05", "aprovado"),
    ("u_lanc_rascunho", "2026-05", "rascunho"),
    ("u_reaberto", "2026-05", "aprovado"),       # informativo
    ("u_gerado_com_lanc", "2026-05", "aprovado"),  # informativo
    ("patio_real", "2026-05", "aprovado"),
    ("u_ok", "2026-06", "aprovado"),
    ("historico_sem_run", "2025-01", "aprovado"),  # fora de escopo (sem status.json)
]:
    con.execute("INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
                "VALUES (?,?,?,?,?)", (uid, mes, 1.0, "{}", status))
con.commit()
con.close()


def _pdf(mes, nome):
    d = os.path.join(RUNS, mes, "reports")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, nome)
    with open(p, "wb") as f:
        f.write(b"%PDF-1.4 teste")
    return p


def _wf(status, pdf=None):
    return {"status": status, "pdf_path": pdf, "version": 1}


def _status_json(mes, conteudo):
    os.makedirs(os.path.join(RUNS, mes), exist_ok=True)
    with open(os.path.join(RUNS, mes, "status.json"), "w", encoding="utf-8") as f:
        json.dump(conteudo, f)


_status_json("2026-05", {
    "u_ok":              _wf("aprovado", _pdf("2026-05", "u_ok.pdf")),
    "u_sem_lanc":        _wf("aprovado", _pdf("2026-05", "u_sem_lanc.pdf")),   # SEM_LANCAMENTO
    "u_lanc_rascunho":   _wf("aprovado", _pdf("2026-05", "u_lanc_rascunho.pdf")),  # LANCAMENTO_NAO_APROVADO
    "u_sem_pdf":         _wf("aprovado", os.path.join(RUNS, "2026-05", "reports", "inexistente.pdf")),  # SEM_PDF
    "u_pdf_nulo":        _wf("aprovado", None),                                  # SEM_PDF (+ SEM_LANCAMENTO)
    "u_reaberto":        _wf("reaberto", _pdf("2026-05", "u_reaberto.pdf")),     # informativo
    "u_gerado_com_lanc": _wf("gerado", _pdf("2026-05", "u_gerado_com_lanc.pdf")),  # informativo
    "u_gerado_sem_lanc": _wf("gerado", _pdf("2026-05", "u_gerado_sem_lanc.pdf")),  # nada (esperado)
    "u_pendente":        _wf("pendente"),                                        # nada
    "patio_real":        _wf("aprovado", _pdf("2026-05", "patio_real.pdf")),
})
_status_json("2026-06", {"u_ok": _wf("aprovado", _pdf("2026-06", "u_ok.pdf"))})
os.makedirs(os.path.join(RUNS, "2026-07"))
with open(os.path.join(RUNS, "2026-07", "status.json"), "w") as f:
    f.write("{ json quebrado")


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


# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1 — Classificação das inconsistências")
print("=" * 70)
antes = _snapshot()
r = _rodar(DB, RUNS)
out = r.stdout
checar("1a. Executa com código 0 (relata, não 'falha' por achar inconsistência)", r.returncode == 0)


def _linhas(classe):
    return [l for l in out.splitlines() if l.strip().startswith(f"[{classe}")]


def _uids(linhas):
    """Extrai o uid de linhas '[CLASSE   ] 2026-05  uid   workflow=...'."""
    return sorted(re.match(r"\s*\[\w+\s*\]\s+\S+\s+(\S+)", l).group(1) for l in linhas)


sem_lanc = _linhas("SEM_LANCAMENTO")
checar("1b. SEM_LANCAMENTO: u_sem_lanc e u_pdf_nulo (e só eles)",
       _uids(sem_lanc) == ["u_pdf_nulo", "u_sem_lanc"])
nao_apr = _linhas("LANCAMENTO_NAO_APROVADO")
checar("1c. LANCAMENTO_NAO_APROVADO: só u_lanc_rascunho, com o status do lançamento",
       len(nao_apr) == 1 and "u_lanc_rascunho" in nao_apr[0] and "'rascunho'" in nao_apr[0])
sem_pdf = _linhas("SEM_PDF")
checar("1d. SEM_PDF: u_sem_pdf e u_pdf_nulo (e só eles)",
       _uids(sem_pdf) == ["u_pdf_nulo", "u_sem_pdf"])
secao_inc = out.split("INCONSISTÊNCIAS")[1].split("INFORMATIVO")[0]
for ok_uid in ("u_ok", "patio_real", "u_reaberto", "u_gerado_com_lanc", "u_gerado_sem_lanc", "u_pendente"):
    checar(f"1e. '{ok_uid}' NÃO aparece como inconsistência", ok_uid not in secao_inc)
checar("1f. Pátio (uid patio_real) é cruzado normalmente com lancamentos", "patio_real" not in secao_inc)
checar("1g. Competência histórica sem status.json (2025-01) fora de escopo",
       "2025-01" not in out and "historico_sem_run" not in out)

print("=" * 70)
print("2 — Informativo e sinalizadores")
print("=" * 70)
secao_info = out.split("INFORMATIVO")[1].split("SINALIZADORES")[0]
checar("2a. INFORMATIVO lista u_reaberto e u_gerado_com_lanc",
       "u_reaberto" in secao_info and "u_gerado_com_lanc" in secao_info)
checar("2b. INFORMATIVO não lista u_gerado_sem_lanc (não há lançamento aprovado)",
       "u_gerado_sem_lanc" not in secao_info)
sinal = out.split("SINALIZADORES")[1]
checar("2c. Sinalizadores: SEM_LANCAMENTO = 2", "SEM_LANCAMENTO" in sinal and any(
    "SEM_LANCAMENTO" in l and l.rstrip().endswith("2") for l in sinal.splitlines()))
checar("2d. Sinalizadores: 1 status.json ilegível reportado sem abortar",
       "ilegíveis: 1" in sinal and "2026-07" in sinal)
checar("2e. Resultado final avisa que o script NÃO corrige nada", "NÃO corrige nada" in out)
checar("2f. Competências lidas: 2026-05 e 2026-06 (2026-07 ilegível)",
       "2026-05: 10 unidade(s)" in out and "2026-06: 1 unidade(s)" in out)

print("=" * 70)
print("3 — Estritamente read-only")
print("=" * 70)
depois = _snapshot()
checar("3a. Banco e todos os arquivos byte a byte idênticos (conteúdo e mtime) depois de rodar",
       antes == depois)
checar("3b. Nenhum arquivo novo (nem -journal/-wal/-shm) criado",
       set(antes) == set(depois) and not any(n.endswith(("-journal", "-wal", "-shm")) for n in depois))

_spec = importlib.util.spec_from_file_location("diag_aprov", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
conn_ro = _mod._conectar_ro(__import__("pathlib").Path(DB))
try:
    conn_ro.execute("INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json) "
                    "VALUES ('x','2026-05',1,'{}')")
    escreveu = True
except sqlite3.OperationalError:
    escreveu = False
checar("3c. A conexão do script recusa INSERT (modo read-only imposto pelo SQLite)", not escreveu)
try:
    conn_ro.execute("DELETE FROM lancamentos")
    apagou = True
except sqlite3.OperationalError:
    apagou = False
checar("3d. A conexão do script recusa DELETE", not apagou)
conn_ro.close()

with open(_SCRIPT, encoding="utf-8") as f:
    _arvore = ast.parse(f.read())
_imports = {n.names[0].name.split(".")[0] for n in ast.walk(_arvore) if isinstance(n, ast.Import)} | {
    n.module.split(".")[0] for n in ast.walk(_arvore) if isinstance(n, ast.ImportFrom) and n.module}
checar(f"3e. Só biblioteca padrão, sem importar app.* (imports: {sorted(_imports)})",
       _imports <= {"json", "os", "sqlite3", "sys", "pathlib"} and "app" not in _imports)
_escritas = [n for n in ast.walk(_arvore) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("write_text", "write_bytes", "unlink", "rmdir", "mkdir", "rename",
                                 "replace", "remove", "executescript", "commit")]
checar("3f. Sem chamadas de escrita/remoção/commit no código do script", not _escritas)

print("=" * 70)
print("4 — Entradas inválidas")
print("=" * 70)
antes_vazio = set(os.listdir(_TMP))
r2 = _rodar(os.path.join(_TMP, "nao_existe.sqlite"), RUNS)
checar("4a. Banco inexistente: sai com erro e mensagem clara", r2.returncode != 0
       and "Banco não encontrado" in (r2.stderr + r2.stdout))
checar("4b. Banco inexistente: não cria arquivo nenhum", set(os.listdir(_TMP)) == antes_vazio)

_vazio = tempfile.mkdtemp(dir=_TMP)
r3 = _rodar(DB, _vazio)
checar("4c. Sem nenhum status.json: informa que não há o que verificar, sem inconsistência",
       r3.returncode == 0 and "nada a verificar" in r3.stdout and "nenhuma inconsistência" in r3.stdout)

print()
if _falhas:
    print(f"{len(_falhas)} FALHA(S):")
    for n in _falhas:
        print("  -", n)
    sys.exit(1)
print("Todas as verificações passaram.")
