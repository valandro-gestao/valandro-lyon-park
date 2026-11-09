"""
Cobertura permanente de scripts/diagnostico_ekos_quitacao_out2026.py — o
diagnóstico READ-ONLY da conciliação da quitação de prejuízo acumulado da Ekos.

Garante que o script:
  1. classifica corretamente os 4 cenários (INTEGRAL, PARCIAL, EXCEDENTE,
     ABSORVIDO) sobre valores gravados, com aplicado/excedente/saldo final
     corretos e o repasse gravado reportado sem alteração;
  2. aceita a saída digitada quando a competência ainda não tem lançamento;
  3. sinaliza entrada divergente da cadeia (mês anterior não aprovado);
  4. é estritamente read-only: banco e árvore de arquivos byte a byte
     idênticos depois de rodar, e a conexão recusa escrita;
  5. não importa `app.*`, usa só biblioteca padrão, não depende de caminhos
     locais (padrão /mnt/data via $DATA_DIR) e não imprime metadados de usuário;
  6. falha com mensagem clara, sem criar nada, quando o banco não existe.

Execução: python3 tests/testes_diagnostico_ekos_quitacao.py
"""
import ast, atexit, hashlib, importlib.util, json, os, shutil, sqlite3, subprocess, sys, tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_REPO_ROOT, "scripts", "diagnostico_ekos_quitacao_out2026.py")

_falhas = []


def checar(nome, condicao):
    print(f"{'[OK]' if condicao else '[FALHOU]'} {nome}")
    if not condicao:
        _falhas.append(nome)


_TMP = tempfile.mkdtemp(prefix="lyon_testes_diag_ekos_")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)


def _lanc(res, ent, inv=0.0, pct=0.85):
    base = res - inv + ent
    saida = round(base, 2) if base <= 0 else 0.0
    alug = round(base * pct, 2) if base > 0 else 0.0
    return {"resultado": res, "prejuizo_acumulado_entrada": ent, "prejuizo_acumulado_saida": saida,
            "aluguel_calculado": alug, "extras": ({"investimentos": inv} if inv else {})}


def _montar(nome, out_res=None, out_status="aprovado", set_status="aprovado", wf="aprovado"):
    """Cadeia Jul/Ago/Set + Out opcional. Devolve o diretório (db.sqlite + runs/)."""
    d = os.path.join(_TMP, nome)
    os.makedirs(os.path.join(d, "runs", "2026-10"))
    os.makedirs(os.path.join(d, "runs", "2026-09"))
    con = sqlite3.connect(os.path.join(d, "db.sqlite"))
    con.executescript("""
      CREATE TABLE schema_migrations (id TEXT PRIMARY KEY);
      CREATE TABLE unidades (id TEXT PRIMARY KEY, nome TEXT, tipo_calculo TEXT, ativo INTEGER, inicio TEXT);
      CREATE TABLE lancamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, unidade_id TEXT NOT NULL,
        mes_referencia TEXT NOT NULL, faturamento REAL NOT NULL, resultado_json TEXT NOT NULL,
        status TEXT DEFAULT 'rascunho', UNIQUE(unidade_id, mes_referencia));
      CREATE TABLE parametros_vigentes (id INTEGER PRIMARY KEY AUTOINCREMENT, unidade_id TEXT NOT NULL,
        parametro TEXT NOT NULL, valor TEXT NOT NULL, competencia_inicio TEXT NOT NULL,
        competencia_fim TEXT, alterado_em TEXT, alterado_por TEXT);
      CREATE TABLE rascunhos_unidade (unidade_id TEXT NOT NULL, mes_referencia TEXT NOT NULL,
        dados_json TEXT NOT NULL, atualizado_em TEXT, PRIMARY KEY (unidade_id, mes_referencia));
    """)
    con.execute("INSERT INTO schema_migrations VALUES ('0019_x')")
    con.execute("INSERT INTO unidades VALUES ('ekos','Ekos','COM_ALIQUOTA_CUMUL',1,'2026-07-01')")
    cadeia = [("2026-07", -4110.61, 0.0, "aprovado"),
              ("2026-08", -300.0, -4110.61, "aprovado"),
              ("2026-09", -100.0, -4410.61, set_status)]
    for mes, res, ent, st in cadeia:
        con.execute("INSERT INTO lancamentos (unidade_id,mes_referencia,faturamento,resultado_json,status) "
                    "VALUES ('ekos',?,1000,?,?)", (mes, json.dumps(_lanc(res, ent)), st))
    if out_res is not None:
        ent = -4510.61
        con.execute("INSERT INTO lancamentos (unidade_id,mes_referencia,faturamento,resultado_json,status) "
                    "VALUES ('ekos','2026-10',1000,?,?)", (json.dumps(_lanc(out_res, ent)), out_status))
    con.execute("INSERT INTO rascunhos_unidade VALUES ('ekos','2026-10',?, '2026-11-05')",
                (json.dumps({"fat_ekos": 1234.5, "_aucon_meta": {"periodo": "2026-10", "usuario": "SEGREDO_USUARIO"}}),))
    con.commit(); con.close()
    with open(os.path.join(d, "runs", "2026-10", "status.json"), "w") as f:
        json.dump({"ekos": {"status": wf, "version": 2, "last_generated_at": "2026-11-05T10:00:00",
                            "last_approved_at": "2026-11-05T11:00:00", "versions": [{"version": 1}]}}, f)
    return d


def _rodar(d, *extra, env=None):
    e = dict(os.environ); e.pop("DATA_DIR", None)
    if env:
        e.update(env)
    return subprocess.run([sys.executable, "-I", _SCRIPT, os.path.join(d, "db.sqlite"), *extra],
                          capture_output=True, text=True, env=e)


def _arvore(d):
    h = hashlib.sha256()
    for raiz, _, arqs in sorted(os.walk(d)):
        for a in sorted(arqs):
            p = os.path.join(raiz, a)
            h.update(p.encode()); h.update(open(p, "rb").read())
    return h.hexdigest()


# 1. cenários (saída de Set = -4.510,61; Q = 4.858,56) ─────────────────────────
casos = [
    ("parcial",   -1000.0,  "PARCIAL",   "4.858,56", "0,00",    "-652,05"),   # saída -5.510,61
    ("integral",   -347.95, "INTEGRAL",  "4.858,56", "0,00",    "0,00"),      # saída -4.858,56
    ("excedente",   200.0,  "EXCEDENTE", "4.310,61", "547,95",  "0,00"),      # saída -4.310,61
    ("absorvido",  6000.0,  "ABSORVIDO", "0,00",     "4.858,56", "0,00"),     # base > 0, saída 0
]
for nome, res, cen, aplic, exced, final in casos:
    d = _montar(nome, out_res=res)
    antes = _arvore(d)
    r = _rodar(d)
    out = r.stdout
    checar(f"{nome}: execução sem erro", r.returncode == 0 and not r.stderr.strip())
    checar(f"{nome}: cenário {cen}", f"CENÁRIO: {cen}" in out)
    checar(f"{nome}: aplicado {aplic}", f"Valor aplicável ........................................ {aplic:>12}" in out)
    checar(f"{nome}: excedente {exced}", f"Excedente PENDENTE DE CONCILIAÇÃO ..................... {exced:>12}" in out)
    checar(f"{nome}: saldo final {final}", f"Saldo final a transportar para 2026-11 ................ {final:>12}" in out)
    checar(f"{nome}: entrada de Set pela cadeia (-4.510,61)", "-4.510,61" in out)
    checar(f"{nome}: workflow e versões de PDF lidos", "'status': 'aprovado'" in out and "PDFs arquivados: 1" in out)
    checar(f"{nome}: metadado de usuário omitido", "SEGREDO_USUARIO" not in out)
    checar(f"{nome}: árvore intacta (read-only)", _arvore(d) == antes)

d = _montar("absorvido_repasse", out_res=6000.0)
out = _rodar(d).stdout
checar("absorvido: repasse gravado é reportado (1.265,98 = 85% de 1.489,39)", "1.265,98" in out)
checar("absorvido: diz que o prejuízo foi absorvido", "SALDO JÁ ABSORVIDO" in out)
checar("aprovado: alerta de sobrescrita na reaprovação", "sobrescreve a linha de lancamentos" in out)

# 2. sem lançamento de Out ─────────────────────────────────────────────────────
d = _montar("sem_out", out_res=None, wf="gerado")
out = _rodar(d).stdout
checar("sem lançamento: diz que não é classificável com dado gravado", "sem dados gravados para classificar" in out)
out2 = _rodar(d, "--saida-antes", "-4210.33").stdout
checar("sem lançamento + --saida-antes: classifica como indicativo (EXCEDENTE, 648,23)",
       "EXCEDENTE" in out2 and "648,23" in out2 and "valor digitado" in out2)

# 3. cadeia: Set não aprovado -> Out diverge ─────────────────────────────────────
d = _montar("set_rascunho", out_res=-1000.0, set_status="rascunho")
out = _rodar(d).stdout
checar("Set não aprovado: sinaliza que não alimenta a cadeia", "NÃO APROVADO: não alimenta a cadeia" in out)
checar("Set não aprovado: sinaliza entrada de Out divergente da cadeia", "ENTRADA DIVERGE DA CADEIA" in out)

# 4. banco inexistente ───────────────────────────────────────────────────────────
ausente = os.path.join(_TMP, "nao_existe")
r = subprocess.run([sys.executable, "-I", _SCRIPT, os.path.join(ausente, "db.sqlite")], capture_output=True, text=True)
checar("banco inexistente: código 2, mensagem clara, nada criado",
       r.returncode == 2 and "banco não encontrado" in r.stderr and not os.path.exists(ausente))

# 5. DATA_DIR default (sem argumento de caminho) ─────────────────────────────────
d = _montar("via_data_dir", out_res=200.0)
r = subprocess.run([sys.executable, "-I", _SCRIPT], capture_output=True, text=True, env={**os.environ, "DATA_DIR": d})
checar("sem argumento: lê de $DATA_DIR/db.sqlite", r.returncode == 0 and "EXCEDENTE" in r.stdout)

# 6. propriedades estáticas e de importação ─────────────────────────────────────
src = open(_SCRIPT, encoding="utf-8").read()
tree = ast.parse(src)
mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)} | \
       {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
checar("só biblioteca padrão, sem app.*", mods <= {"argparse", "json", "os", "sqlite3", "sys", "pathlib"} and "app" not in mods)
checar("abre o banco com mode=ro e PRAGMA query_only=ON", "?mode=ro" in src and "PRAGMA query_only=ON" in src)
checar("default de produção /mnt/data, sem caminho local do Mac", '"/mnt/data"' in src and "/Users/" not in src)
sqls = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
checar("nenhuma instrução de escrita nos SQLs do script",
       not any(s.lstrip().lower().startswith(("insert", "update", "delete", "create", "drop", "alter", "replace", "vacuum"))
               for s in sqls))

spec = importlib.util.spec_from_file_location("diag_ekos", _SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)           # import não executa nada (main protegido)
con = mod.abrir_ro(os.path.join(_montar("conn", out_res=1.0), "db.sqlite"))
try:
    con.execute("INSERT INTO schema_migrations VALUES ('x')")
    escreveu = True
except sqlite3.OperationalError:
    escreveu = False
checar("a conexão recusa escrita", not escreveu)

# 7. regra pura ───────────────────────────────────────────────────────────────────
c = mod.classificar_quitacao
checar("regra: parcial", c(-6000, 4858.56) == {"cenario": "PARCIAL", "aplicada": 4858.56, "excedente": 0.0, "saldo_final": -1141.44})
checar("regra: integral", c(-4858.56, 4858.56)["cenario"] == "INTEGRAL")
checar("regra: excedente nunca gera saldo positivo", c(-100, 4858.56)["saldo_final"] == 0.0 and c(-100, 4858.56)["excedente"] == 4758.56)
checar("regra: saldo zero => ABSORVIDO, valor inteiro pendente", c(0, 4858.56) == {"cenario": "ABSORVIDO", "aplicada": 0.0, "excedente": 4858.56, "saldo_final": 0.0})
checar("regra: saída positiva (impossível) é tratada como zero", c(50, 10)["saldo_final"] == 0.0 and c(50, 10)["aplicada"] == 0.0)
checar("regra: quitação <= 0 não aplica nada", c(-100, 0)["cenario"] == "SEM_QUITACAO" and c(-100, 0)["saldo_final"] == -100.0)

print()
if _falhas:
    print(f"{len(_falhas)} FALHA(S):", *_falhas, sep="\n  - ")
    sys.exit(1)
print("TODOS OS TESTES PASSARAM")
