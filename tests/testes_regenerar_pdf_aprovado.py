"""
Cobertura permanente da regeneração do PDF de uma competência JÁ APROVADA
(run_manager.regenerar_pdf_aprovado e o botão "Regenerar PDF"):

  1. a aprovação original é preservada (status, last_approved_at, reopened_at);
  2. o PDF sai SÓ do lançamento aprovado persistido — nunca de um "Calcular"
     temporário da sessão;
  3. lançamentos, parâmetros, saldos e histórico anual não são alterados, e
     NENHUMA escrita no banco acontece (a conexão roda com query_only), inclusive
     a semeadura de parâmetros de get_unit_com_params;
  4. o PDF anterior fica em "Versões" (byte a byte) e a versão sobe 1;
  5. falha em qualquer etapa preserva o PDF vigente, o status e as versões;
  6. Pátio aprovado: regeneração desabilitada, com explicação; PDF auxiliar de
     Direito de Uso (Nilo) só do lançamento aprovado;
  7. status.json é gravado de forma atômica.

O comportamento das competências NÃO aprovadas fica coberto por
tests/testes_gerar_pdf_nao_aprovados.py (escrito antes desta alteração).

Roda em banco SQLite isolado (tempfile) a partir do data/seed.db versionado.
Execução: python3 tests/testes_regenerar_pdf_aprovado.py
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile, atexit
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_regenerar_pdf_")
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


from streamlit.testing.v1 import AppTest
import app.models as models
from app import run_manager as rm
from app.engine import calcular, load_units, get_unit_com_params
from app.models import criar_unidade, salvar_lancamento, salvar_parametros, get_db
from app.paths import RUNS_DIR
from app.renderer import OUTPUT_DIR

load_units(force=True)
MES = "2026-09"
MED, VIVA, UID_DU = "medcenter", "viva_open_mall", "regen_du"
FAT_MED = 560000.00
FAT_VIVA = round((124540.20 + 26626.96) / (1 - 0.1425), 2)    # exemplo da operação: saldo 73.325,81
TEM_PDFTOTEXT = shutil.which("pdftotext") is not None

_PROBES: list[str] = []
atexit.register(lambda: [os.remove(p) for p in _PROBES if os.path.exists(p)])


def abrir(uid, mes=MES):
    """Sessão NOVA com a unidade selecionada uma única vez (como o botão 'Abrir')."""
    path = os.path.join(_REPO_ROOT, "tests", f"_probe_regen_{len(_PROBES)}.py")
    with open(path, "w") as f:
        f.write(f'''
import os, sys
os.environ["DATA_DIR"] = {_SCRATCH!r}
sys.path.insert(0, {_REPO_ROOT!r})
import streamlit as st
if "_i" not in st.session_state:
    st.session_state._i = 1
    st.session_state.selected_unit = {uid!r}
from app.ui.fechamento import tela_fechamento
tela_fechamento({mes!r})
''')
    _PROBES.append(path)
    at = AppTest.from_file(path, default_timeout=120)
    at.run()
    return at


def aprovar_pela_ui(uid, fat):
    at = abrir(uid)
    at.number_input(key=f"fat_{uid}").set_value(fat).run()
    at.button(key=f"act_calc_{uid}").click().run()
    at.button(key=f"act_apr_{uid}").click().run()
    return at


def texto_pdf(caminho):
    return subprocess.run(["pdftotext", "-layout", str(caminho), "-"], capture_output=True, text=True).stdout


def sha_arquivo(caminho):
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


def brl(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


TABELAS = ("lancamentos", "parametros_vigentes", "saldos_acumulados", "historico_anual", "unidades", "rascunhos_unidade")


def db_estado(tabelas=TABELAS):
    out = {}
    with get_db() as c:
        for t in tabelas:
            out[t] = hashlib.sha256(json.dumps([tuple(r) for r in c.execute(f"SELECT * FROM {t} ORDER BY 1,2")],
                                                default=str).encode()).hexdigest()
    return out


def arquivos(pasta):
    return sorted(str(p.relative_to(pasta)) for p in Path(pasta).rglob("*") if p.is_file()) if Path(pasta).exists() else []


def estado(uid, mes=MES):
    u = rm.get_unit_run(mes, uid)
    return {
        "status": u["status"], "version": u["version"], "versions": json.dumps(u["versions"], sort_keys=True),
        "aprovado_em": u["last_approved_at"], "revisado_em": u["last_reviewed_at"], "reaberto_em": u["reopened_at"],
        "reaberto_motivo": u["reopened_reason"], "pdf_path": u["pdf_path"],
        "pdf_sha": sha_arquivo(u["pdf_path"]) if u["pdf_path"] and Path(u["pdf_path"]).exists() else None,
        "gerado_em": u["last_generated_at"],
    }


@contextmanager
def banco_somente_leitura():
    """Qualquer escrita no banco, em qualquer módulo da aplicação, levanta OperationalError."""
    original = models.get_db

    def get_db_ro():
        conn = original()
        conn.execute("PRAGMA query_only=ON")
        return conn

    patches = [mock.patch.object(m, "get_db", get_db_ro) for n, m in list(sys.modules.items())
               if n.startswith("app") and getattr(m, "get_db", None) is original]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


# ── cenário: Medcenter e Viva aprovados PELA INTERFACE em set/2026 ──────────
for uid, fat in ((MED, FAT_MED), (VIVA, FAT_VIVA)):
    at = aprovar_pela_ui(uid, fat)
    assert len(at.exception) == 0 and rm.get_unit_run(MES, uid)["status"] == "aprovado", uid

lanc_viva = rm.load_resultado_from_db(MES, VIVA)
checar("0. Cenário: Viva aprovado pela UI com o exemplo da operação (saldo 73.325,81)", lanc_viva.aluguel_calculado == 73325.81)

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1 — Regeneração (serviço): aprovação preservada, banco SEM escrita, versão anterior guardada")
print("=" * 70)
for uid in (MED, VIVA):
    a_db, a_st = db_estado(), estado(uid)
    outros_antes = {u: estado(u) for u in (MED, VIVA) if u != uid}
    versions_dir = Path(a_st["pdf_path"]).parent / "versions"
    with banco_somente_leitura():
        caminho = rm.regenerar_pdf_aprovado(MES, uid)
    d_st = estado(uid)
    checar(f"1a. [{uid}] regenerou sem nenhuma escrita no banco (conexões em query_only)", Path(caminho).exists())
    checar(f"1b. [{uid}] workflow continua 'aprovado'", d_st["status"] == "aprovado")
    checar(f"1c. [{uid}] carimbos de aprovação/revisão/reabertura preservados",
           (d_st["aprovado_em"], d_st["revisado_em"], d_st["reaberto_em"], d_st["reaberto_motivo"])
           == (a_st["aprovado_em"], a_st["revisado_em"], a_st["reaberto_em"], a_st["reaberto_motivo"]) and d_st["reaberto_em"] is None)
    checar(f"1d. [{uid}] versão sobe de {a_st['version']} para {a_st['version'] + 1} e last_generated_at é atualizado",
           d_st["version"] == a_st["version"] + 1 and d_st["gerado_em"] >= a_st["gerado_em"])
    u = rm.get_unit_run(MES, uid)
    checar(f"1e. [{uid}] o PDF anterior foi arquivado em Versões (status_at_time 'aprovado')",
           len(u["versions"]) == 1 and u["versions"][0]["status_at_time"] == "aprovado" and u["versions"][0]["version"] == a_st["version"])
    checar(f"1f. [{uid}] o arquivo arquivado é IDÊNTICO byte a byte ao PDF vigente de antes",
           sha_arquivo(u["versions"][0]["pdf_path"]) == a_st["pdf_sha"])
    checar(f"1g. [{uid}] o caminho do PDF vigente não mudou", d_st["pdf_path"] == a_st["pdf_path"])
    checar(f"1h. [{uid}] lançamentos, parâmetros, saldos, histórico anual e unidades IDÊNTICOS", db_estado() == a_db)
    checar(f"1i. [{uid}] as outras unidades não foram tocadas", all(estado(u) == v for u, v in outros_antes.items()))
    checar(f"1j. [{uid}] nenhum temporário sobrou em reports/, versions/ nem na área do renderer",
           not [a for a in arquivos(Path(a_st["pdf_path"]).parent) if ".regen_" in a or a.endswith(".tmp")]
           and not [f for f in os.listdir(OUTPUT_DIR) if f.startswith("regen_")])
    if TEM_PDFTOTEXT:
        t = texto_pdf(caminho)
        checar(f"1k. [{uid}] o PDF novo traz a nomenclatura nova e o card 'Saldo a Pagar'",
               "Saldo a Pagar" in t and "Repasse ao Contratante" in t and "Valor do Repasse" not in t)
saldo_viva = brl(lanc_viva.aluguel_calculado)
if TEM_PDFTOTEXT:
    checar("1l. Viva: o PDF regenerado traz os valores do lançamento aprovado (73.325,81 e 105.859,17)",
           saldo_viva in texto_pdf(rm.get_unit_run(MES, VIVA)["pdf_path"]) and "105.859,17" in texto_pdf(rm.get_unit_run(MES, VIVA)["pdf_path"]))
checar("1m. As competências aprovadas continuam entrando nos históricos dos outros meses",
       MES in __import__("app.split_repasse", fromlist=["x"]).competencias_aprovadas(MED))

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2 — Sem semeadura de parâmetros no caminho de regeneração")
print("=" * 70)
with get_db() as c:
    c.execute("DELETE FROM parametros_vigentes WHERE unidade_id=? AND parametro='percentual_operador'", (MED,))
    antes_linhas = c.execute("SELECT COUNT(*) FROM parametros_vigentes WHERE unidade_id=?", (MED,)).fetchone()[0]
a_db = db_estado()
rm.regenerar_pdf_aprovado(MES, MED)       # sem query_only: se houvesse semeadura, ela gravaria
with get_db() as c:
    depois_linhas = c.execute("SELECT COUNT(*) FROM parametros_vigentes WHERE unidade_id=?", (MED,)).fetchone()[0]
checar("2a. Regenerar NÃO recria o parâmetro que faltava no banco (parametros_vigentes idêntico)",
       depois_linhas == antes_linhas and db_estado() == a_db)
get_unit_com_params(MED, MES)              # controle: o caminho normal semeia
with get_db() as c:
    controle = c.execute("SELECT COUNT(*) FROM parametros_vigentes WHERE unidade_id=?", (MED,)).fetchone()[0]
checar("2b. (controle) get_unit_com_params, o caminho normal, RECRIA o parâmetro — a proteção tem efeito", controle == antes_linhas + 1)

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3 — Pela interface: rótulo, e a sessão 'envenenada' nunca vira PDF")
print("=" * 70)
a_db, a_st = db_estado(), estado(VIVA)
at = abrir(VIVA)
btn = at.button(key=f"act_pdf_{VIVA}")
checar("3a. Competência aprovada: o botão se chama 'Regenerar PDF'", btn.label == "Regenerar PDF")
checar("3b. Não há botão 'Aprovar' numa competência aprovada", "Aprovar" not in [b.label for b in at.button])
at.number_input(key=f"fat_{VIVA}").set_value(1000.0).run()
at.button(key=f"act_calc_{VIVA}").click().run()                  # cálculo TEMPORÁRIO na sessão
at.button(key=f"act_pdf_{VIVA}").click().run()
d_st = estado(VIVA)
checar("3c. Após Calcular(1.000) + Regenerar na mesma sessão: sem exceção e workflow 'aprovado'",
       len(at.exception) == 0 and d_st["status"] == "aprovado" and d_st["version"] == a_st["version"] + 1)
if TEM_PDFTOTEXT:
    t = texto_pdf(d_st["pdf_path"])
    checar("3d. O PDF traz os valores do lançamento APROVADO, não os da sessão (sem 1.000,00)",
           saldo_viva in t and "105.859,17" in t and "1.000,00" not in t)
checar("3e. Lançamentos, parâmetros e saldos idênticos (a sessão não gravou nada)",
       all(db_estado(("lancamentos", "parametros_vigentes", "saldos_acumulados", "historico_anual"))[k] == a_db[k]
           for k in ("lancamentos", "parametros_vigentes", "saldos_acumulados", "historico_anual")))
checar("3f. Carimbos de aprovação preservados pela interface", d_st["aprovado_em"] == a_st["aprovado_em"] and d_st["reaberto_em"] is None)
# lançamento da sessão envenenada não foi persistido e o chip continua Aprovado
at2 = abrir(VIVA)
checar("3g. Sessão nova: continua 'Regenerar PDF' (competência aprovada)", at2.button(key=f"act_pdf_{VIVA}").label == "Regenerar PDF")

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4 — Recusas: nada muda")
print("=" * 70)


def tentar(uid, mes=MES):
    a, a_d = estado(uid, mes), db_estado()
    try:
        rm.regenerar_pdf_aprovado(mes, uid)
        return False, a == estado(uid, mes) and a_d == db_estado()
    except ValueError as e:
        return True, a == estado(uid, mes) and a_d == db_estado(), str(e)


r = tentar("patio_real", "2026-05")
checar("4a. Pátio (REAL): recusado, com mensagem 'ainda não está disponível', sem alterar nada", r[0] and r[1] and "ainda não está disponível" in r[2])
r = tentar("patio_maiojama", "2026-05")
checar("4b. Pátio (MAIOJAMA): recusado", r[0] and r[1])
for st_ in ("pendente", "gerado", "reaberto", "erro", "revisado"):
    rm._update_unit("2026-05", "fk", status=st_)
    r = tentar("fk", "2026-05")
    checar(f"4c. Workflow '{st_}': recusado (só competência aprovada)", r[0] and r[1])
rm._update_unit("2026-05", "fk", status="aprovado", last_approved_at="2026-06-02T10:00:00")
with get_db() as c:
    c.execute("UPDATE lancamentos SET status='rascunho' WHERE unidade_id='fk' AND mes_referencia='2026-05'")
r = tentar("fk", "2026-05")
checar("4d. Workflow 'aprovado' mas lançamento 'rascunho': recusado ('Lançamento aprovado não encontrado')", r[0] and r[1] and "Lançamento aprovado" in r[2])
with get_db() as c:
    c.execute("DELETE FROM lancamentos WHERE unidade_id='fk' AND mes_referencia='2026-05'")
r = tentar("fk", "2026-05")
checar("4e. Workflow 'aprovado' sem lançamento nenhum: recusado", r[0] and r[1])

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5 — Falhas injetadas: PDF vigente, status e versões preservados")
print("=" * 70)
real_replace = os.replace


def replace_falha_no_pdf(src, dst, *a, **k):
    if str(dst).endswith(".pdf"):
        raise OSError("falha injetada na substituição do PDF")
    return real_replace(src, dst, *a, **k)


def cenario(nome, ctx):
    a_st, a_db = estado(VIVA), db_estado()
    pasta = Path(a_st["pdf_path"]).parent
    arq_antes = arquivos(pasta)
    run_antes = json.dumps(rm.load_run(MES), sort_keys=True)
    try:
        with ctx:
            rm.regenerar_pdf_aprovado(MES, VIVA)
        levantou = False
    except BaseException:
        levantou = True
    d_st = estado(VIVA)
    checar(f"5. [{nome}] a regeneração falha (e propaga o erro)", levantou)
    checar(f"5. [{nome}] status 'aprovado' (nunca 'erro') e carimbos intactos",
           d_st["status"] == "aprovado" and d_st["aprovado_em"] == a_st["aprovado_em"] and d_st["reaberto_em"] is None)
    checar(f"5. [{nome}] PDF vigente byte a byte igual", d_st["pdf_sha"] == a_st["pdf_sha"] and d_st["pdf_path"] == a_st["pdf_path"])
    checar(f"5. [{nome}] versão e lista de versões inalteradas (status.json idêntico)",
           (d_st["version"], d_st["versions"]) == (a_st["version"], a_st["versions"]) and json.dumps(rm.load_run(MES), sort_keys=True) == run_antes)
    checar(f"5. [{nome}] nenhum arquivo novo (nem backup órfão, nem temporário)",
           arquivos(pasta) == arq_antes and not [f for f in os.listdir(OUTPUT_DIR) if f.startswith("regen_")])
    checar(f"5. [{nome}] banco intacto", db_estado() == a_db)


cenario("falha ao montar/renderizar o HTML", mock.patch.object(rm, "render_html", side_effect=RuntimeError("falha injetada")))
cenario("falha no WeasyPrint (export_pdf)", mock.patch.object(rm, "export_pdf", side_effect=RuntimeError("falha injetada")))


def export_pdf_invalido(html, nome):
    p = Path(OUTPUT_DIR) / nome
    p.write_bytes(b"lixo")
    return str(p)


cenario("PDF gerado inválido (truncado)", mock.patch.object(rm, "export_pdf", export_pdf_invalido))
cenario("falha ao gravar o status.json (registro da versão)", mock.patch.object(rm, "_update_unit", side_effect=OSError("falha injetada")))
cenario("falha na substituição atômica do PDF", mock.patch.object(rm.os, "replace", replace_falha_no_pdf))

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("6 — Pátio aprovado: regeneração desabilitada com explicação; não aprovado não muda")
print("=" * 70)
for sub in ("patio_real", "patio_maiojama"):
    rm._update_unit("2026-05", sub, status="aprovado", last_approved_at="2026-06-02T10:00:00")
a_run = json.dumps(rm.load_run("2026-05"), sort_keys=True)
a_db = db_estado()
at = abrir("patio", "2026-05")
botoes = [b for b in at.button if b.key in ("wf_gen_patio_real", "wf_gen_patio_maiojama")]
checar("6a. Os dois contratantes aprovados têm o botão 'Regenerar PDF' DESABILITADO",
       len(botoes) == 2 and all(b.label == "Regenerar PDF" and b.disabled for b in botoes))
checar("6b. A mensagem explica que a operação ainda não está disponível",
       sum("ainda não está disponível" in str(c.value) for c in at.caption) == 2)
# Obs.: ABRIR qualquer tela de unidade chama get_unit_com_params (semeia parâmetros do YAML que ainda
# não existam no banco — comportamento anterior a esta alteração, fora do caminho de regeneração; para
# unidades já semeadas é um no-op). Por isso aqui se compara o que o clique/tela jamais pode mudar.
checar("6c. Abrir o Pátio aprovado não muda workflow, lançamentos, saldos nem histórico (e, antes desta correção, o clique levava a 'erro')",
       json.dumps(rm.load_run("2026-05"), sort_keys=True) == a_run
       and all(db_estado(("lancamentos", "saldos_acumulados", "historico_anual"))[k] == a_db[k]
               for k in ("lancamentos", "saldos_acumulados", "historico_anual")))

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("7 — PDF auxiliar de Direito de Uso (Nilo): competência aprovada usa só o lançamento")
print("=" * 70)
criar_unidade(UID_DU, "Regen DU", "Contratante DU", "2020-01-01", "COM_ALIQUOTA_CUMUL_DU")
salvar_parametros(UID_DU, MES, {"aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "numero_vagas": 100,
                                "faixas_aluguel": [{"percentual": 0.5, "ate": 100000.0}, {"percentual": 0.7}],
                                "despesas_rateio_du": [{"id": "agua", "nome": "Água"}]}, alterado_por="teste")
load_units(force=True)
RATEIO_APROVADO = 5555.55
r_du = calcular(UID_DU, MES, 250000.0, saldo_override=0.0, custos_extras={"despesas_rateio_du": {"agua": RATEIO_APROVADO}})
r_du.status, r_du.mes_referencia = "aprovado", MES
salvar_lancamento(r_du)
rm.generate_report(MES, UID_DU, r_du)
rm.mark_approved(MES, UID_DU)
at = abrir(UID_DU)
at.number_input(key=f"fat_{UID_DU}").set_value(250000.0).run()
at.number_input(key=f"du_despesas_rateio_du_{UID_DU}_agua").set_value(77777.0).run()      # valor TEMPORÁRIO na sessão
at.button(key=f"act_calc_{UID_DU}").click().run()
a_db = db_estado(("lancamentos", "parametros_vigentes", "saldos_acumulados", "historico_anual"))
at.button(key=f"act_pdf_du_{UID_DU}").click().run()
pdf_bytes = at.session_state[f"_pdf_du_bytes_{UID_DU}"]
aux = Path(_SCRATCH) / "aux_du.pdf"
aux.write_bytes(pdf_bytes)
checar("7a. O PDF auxiliar foi gerado sem exceção numa competência aprovada", len(at.exception) == 0 and pdf_bytes[:5] == b"%PDF-")
if TEM_PDFTOTEXT:
    t = texto_pdf(aux)
    checar("7b. Traz o valor do lançamento APROVADO (Água 5.555,55) e NÃO o da sessão (77.777,00)",
           brl(RATEIO_APROVADO) in t and "77.777,00" not in t)
checar("7c. Nada foi gravado (lançamentos/parâmetros/saldos idênticos) e o workflow segue 'aprovado'",
       db_estado(("lancamentos", "parametros_vigentes", "saldos_acumulados", "historico_anual")) == a_db
       and rm.get_unit_run(MES, UID_DU)["status"] == "aprovado")

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("8 — status.json atômico")
print("=" * 70)
antes = Path(rm._status_path(MES)).read_bytes()


def dump_falha(obj, f, **k):
    f.write('{"corrompido": ')          # escrita parcial
    raise OSError("disco cheio (injetado)")


try:
    with mock.patch.object(rm.json, "dump", dump_falha):
        rm._save_run(MES, {"x": 1})
except OSError:
    pass
checar("8a. Falha no meio da gravação: o status.json anterior continua íntegro (byte a byte)", Path(rm._status_path(MES)).read_bytes() == antes)
checar("8b. ...e nenhum arquivo temporário sobra", not list(Path(rm._status_path(MES)).parent.glob("*.tmp")))

print()
if _falhas:
    print(f"{len(_falhas)} FALHA(S):")
    for n in _falhas:
        print("  -", n)
    sys.exit(1)
print("Todas as verificações passaram.")
