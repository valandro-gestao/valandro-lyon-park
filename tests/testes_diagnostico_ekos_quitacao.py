"""
Cobertura permanente de scripts/diagnostico_ekos_quitacao_out2026.py — o
diagnóstico READ-ONLY da conciliação da quitação de prejuízo acumulado da Ekos.

Regra reconhecida (v1.4.0): a quitação liquida só o saldo histórico de ENTRADA
(aplicada = min(recebida, |entrada|)); excedente pendente de conciliação; o
repasse incide sobre o resultado disponível depois disso.

Garante que o script:
  1. classifica INTEGRAL, PARCIAL, EXCEDENTE e SEM_SALDO_HISTORICO com
     aplicado/excedente/saldo ajustado corretos e projeta saída e repasse;
  2. reconhece um lançamento JÁ calculado com a rubrica (entrada ajustada em
     extras) sem acusar falsa quebra de cadeia nem "saída ≠ fórmula", e acusa
     quando o gravado diverge da regra;
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
PCT = 0.75


def _lanc(res, ent, inv=0.0, quit_rec=None, adulterar=False):
    """Lançamento como o calculador grava. `ent` = entrada histórica original."""
    ex = {"investimentos": inv} if inv else {}
    ent_ef = ent
    if quit_rec:
        apl = round(min(quit_rec, max(0.0, -ent)), 2)
        ent_ef = round(ent + apl, 2)
        ex.update({"quitacao_prejuizo": quit_rec, "quitacao_prejuizo_aplicada": apl,
                   "quitacao_prejuizo_excedente": round(quit_rec - apl, 2),
                   "prejuizo_acumulado_entrada_ajustada": ent_ef})
        if adulterar:
            ex["quitacao_prejuizo_aplicada"] = apl + 100.0
    base = res - inv + ent_ef
    saida = round(base, 2) if base <= 0 else 0.0
    alug = round(base * PCT, 2) if base > 0 else 0.0
    return {"resultado": res, "prejuizo_acumulado_entrada": ent, "prejuizo_acumulado_saida": saida,
            "aluguel_calculado": alug, "extras": ex}


def _montar(nome, out_res=None, out_status="aprovado", set_status="aprovado", wf="aprovado",
            set_res=-100.0, quit_rec=None, adulterar=False):
    """Cadeia Jul/Ago/Set (+ Out opcional). Entrada de Out = saída de Set."""
    d = os.path.join(_TMP, nome)
    os.makedirs(os.path.join(d, "runs", "2026-10")); os.makedirs(os.path.join(d, "runs", "2026-09"))
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
    con.execute("INSERT INTO parametros_vigentes (unidade_id,parametro,valor,competencia_inicio) "
                "VALUES ('ekos','percentual_aluguel','0.75','2026-07')")
    ent, sai_set = 0.0, None
    for mes, res, st in (("2026-07", -4110.61, "aprovado"), ("2026-08", -300.0, "aprovado"), ("2026-09", set_res, set_status)):
        # Jul: entrada 0; as demais herdam a saída do mês anterior
        l = _lanc(res, ent if mes != "2026-07" else 0.0)
        con.execute("INSERT INTO lancamentos (unidade_id,mes_referencia,faturamento,resultado_json,status) "
                    "VALUES ('ekos',?,1000,?,?)", (mes, json.dumps(l), st))
        ent = l["prejuizo_acumulado_saida"]
    sai_set = ent
    if out_res is not None:
        con.execute("INSERT INTO lancamentos (unidade_id,mes_referencia,faturamento,resultado_json,status) "
                    "VALUES ('ekos','2026-10',1000,?,?)",
                    (json.dumps(_lanc(out_res, sai_set, quit_rec=quit_rec, adulterar=adulterar)), out_status))
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


def L(rotulo, valor):          # linha formatada exatamente como o script imprime
    return f"{rotulo} {valor:>12}"


# 1. cenários sobre a ENTRADA (saída de Set = entrada de Out = -4.510,61) ─────────
# (nome, --valor, cenário, aplicada, excedente, saldo histórico após)
casos = [
    ("integral",  "4510.61", "INTEGRAL",  "4.510,61", "0,00",   "0,00"),
    ("parcial",   "2000",    "PARCIAL",   "2.000,00", "0,00",   "-2.510,61"),
    ("excedente", "4858.56", "EXCEDENTE", "4.510,61", "347,95", "0,00"),
]
for nome, valor, cen, aplic, exced, apos in casos:
    d = _montar(nome, out_res=None)
    antes = _arvore(d)
    r = _rodar(d, "--valor", valor, "--resultado", "1453.83")
    out = r.stdout
    checar(f"{nome}: execução sem erro", r.returncode == 0 and not r.stderr.strip())
    checar(f"{nome}: cenário {cen}", f"CENÁRIO: {cen}" in out)
    checar(f"{nome}: aplicado {aplic}", "Valor APLICADO ao saldo histórico (limite |entrada|) ...... " + f"{aplic:>12}" in out)
    checar(f"{nome}: excedente {exced}", "Excedente PENDENTE DE CONCILIAÇÃO ......................... " + f"{exced:>12}" in out)
    checar(f"{nome}: saldo histórico após a quitação {apos}", "Saldo histórico após a quitação ........................... " + f"{apos:>12}" in out)
    checar(f"{nome}: entrada de Set pela cadeia (-4.510,61)", "-4.510,61" in out)
    checar(f"{nome}: metadado de usuário omitido", "SEGREDO_USUARIO" not in out)
    checar(f"{nome}: árvore intacta (read-only)", _arvore(d) == antes)

# projeção (D=1.453,83): integral -> repasse 75% de 1.453,83 = 1.090,37 e saída 0
out = _rodar(_montar("proj", out_res=None), "--valor", "4510.61", "--resultado", "1453.83").stdout
checar("projeção integral: saída final 0,00 e repasse 1.090,37 (75% do disponível)",
       "(projeção pela regra) ..... " + f"{'0,00':>12}" in out and "1.090,37" in out)
out = _rodar(_montar("proj_neg", out_res=None), "--valor", "4510.61", "--resultado", "-1000").stdout
checar("projeção com resultado negativo: só o prejuízo operacional segue (-1.000,00), repasse 0,00",
       "(projeção pela regra) ..... " + f"{'-1.000,00':>12}" in out and "........ " + f"{'0,00':>12}" in out.split("(10)")[1])
out = _rodar(_montar("proj_parcial", out_res=None), "--valor", "2000", "--resultado", "1453.83").stdout
checar("projeção parcial: base 1453,83-2510,61 -> saída -1.056,78 e repasse 0,00", "-1.056,78" in out)

# SEM_SALDO_HISTORICO: Set fecha com saída 0 (resultado positivo absorveu tudo)
out = _rodar(_montar("sem_saldo", out_res=None, set_res=5000.0), "--resultado", "1000").stdout
checar("sem saldo histórico: cenário SEM_SALDO_HISTORICO, nada aplicado, valor inteiro pendente",
       "CENÁRIO: SEM_SALDO_HISTORICO" in out and "4.858,56" in out
       and "Valor APLICADO ao saldo histórico (limite |entrada|) ...... " + f"{'0,00':>12}" in out)

# 2. lançamento JÁ calculado COM a rubrica: reconhecido, sem falsos alarmes ───────
d = _montar("com_quitacao", out_res=1453.83, quit_rec=4510.61)
out = _rodar(d).stdout
checar("com quitação gravada: consistente com a regra", "CONSISTENTE com a regra" in out)
checar("com quitação gravada: sem falsa quebra de cadeia nem saída≠fórmula",
       "ENTRADA DIVERGE DA CADEIA" not in out and "SAÍDA≠FÓRMULA" not in out and "fórmula OK" in out and "entrada=cadeia" in out)
checar("com quitação gravada: tabela mostra recebida/aplicada/excedente", "QUITAÇÃO recebida 4.510,61 / aplicada 4.510,61 / excedente 0,00" in out)
checar("com quitação gravada: repasse gravado 1.090,37 reportado", "1.090,37" in out)
out = _rodar(_montar("com_quitacao_exc", out_res=1453.83, quit_rec=6000.0)).stdout
checar("com excedente gravado: sinaliza pendente de conciliação (1.489,39)", "PENDENTE DE CONCILIAÇÃO" in out and "1.489,39" in out)
checar("com excedente gravado: ainda consistente e sem falso alarme", "CONSISTENTE com a regra" in out and "SAÍDA≠FÓRMULA" not in out)
out = _rodar(_montar("adulterado", out_res=1453.83, quit_rec=4510.61, adulterar=True)).stdout
checar("lançamento com quitação divergente da regra é acusado", "DIVERGE da regra" in out)
out = _rodar(_montar("sem_q_gravado", out_res=-500.0)).stdout
checar("lançamento gravado SEM quitação: avisa que lançá-la exige reabrir/reaprovar",
       "já calculado/gravado sem quitação" in out and "JÁ gravado SEM quitação" in out)
out = _rodar(_montar("aprovado", out_res=6000.0)).stdout
checar("aprovado: alerta de sobrescrita na reaprovação", "sobrescreve a linha de lancamentos" in out)
checar("workflow e versões de PDF lidos", "'status': 'aprovado'" in out and "PDFs arquivados: 1" in out)

# 3. cadeia: Set não aprovado -> Out diverge ─────────────────────────────────────
out = _rodar(_montar("set_rascunho", out_res=-1000.0, set_status="rascunho")).stdout
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
checar("sem argumento: lê de $DATA_DIR/db.sqlite", r.returncode == 0 and "CENÁRIO:" in r.stdout)

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

# 7. regra pura (mesma de app.calculators.cumulativo) ─────────────────────────────
c = mod.classificar_quitacao
checar("regra: parcial", c(-6000, 4858.56) == {"cenario": "PARCIAL", "aplicada": 4858.56, "excedente": 0.0, "entrada_ajustada": -1141.44})
checar("regra: integral", c(-4858.56, 4858.56) == {"cenario": "INTEGRAL", "aplicada": 4858.56, "excedente": 0.0, "entrada_ajustada": 0.0})
checar("regra: excedente nunca gera saldo positivo", c(-100, 4858.56) == {"cenario": "EXCEDENTE", "aplicada": 100.0, "excedente": 4758.56, "entrada_ajustada": 0.0})
checar("regra: entrada 0 => SEM_SALDO_HISTORICO, valor inteiro pendente",
       c(0, 4858.56) == {"cenario": "SEM_SALDO_HISTORICO", "aplicada": 0.0, "excedente": 4858.56, "entrada_ajustada": 0.0})
checar("regra: entrada positiva (impossível) é tratada como zero", c(50, 10)["entrada_ajustada"] == 0.0 and c(50, 10)["aplicada"] == 0.0)
checar("regra: quitação <= 0 não aplica nada", c(-100, 0)["cenario"] == "SEM_QUITACAO" and c(-100, 0)["entrada_ajustada"] == -100.0)

print()
if _falhas:
    print(f"{len(_falhas)} FALHA(S):", *_falhas, sep="\n  - ")
    sys.exit(1)
print("TODOS OS TESTES PASSARAM")
