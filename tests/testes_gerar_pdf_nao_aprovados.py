"""
Cobertura permanente (caracterização): o botão "Gerar PDF" das competências NÃO
APROVADAS — e o do Pátio não aprovado — se comporta exatamente como sempre,
mesmo depois de a regeneração de PDF de competência APROVADA ter ganhado um
caminho próprio (run_manager.regenerar_pdf_aprovado).

Escrita ANTES da alteração e executada contra o código antigo: estas
asserções descrevem o comportamento que NÃO pode mudar.

  - rótulo do botão: "Gerar PDF";
  - pendente / gerado / revisado / reaberto / erro: o workflow termina em
    `gerado`, a versão sobe 1, e o PDF anterior só é arquivado em
    "Versões" quando o status era `revisado` ou `reaberto`;
  - o resultado da SESSÃO ("Calcular") continua tendo prioridade sobre o
    lançamento persistido nas competências não aprovadas;
  - sem lançamento e sem cálculo: "Calcule antes de gerar o PDF." e nada muda;
  - Pátio não aprovado, com "Calcular Pátio" feito: gera o PDF do contratante.

Roda em banco SQLite isolado (tempfile) a partir do data/seed.db versionado.
Execução: python3 tests/testes_gerar_pdf_nao_aprovados.py
"""
import os, sys, tempfile, shutil, atexit, subprocess

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_gerar_pdf_nao_aprov_")
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


from pathlib import Path
from streamlit.testing.v1 import AppTest
from app import run_manager as rm
from app.engine import load_units
from app.paths import RUNS_DIR

load_units(force=True)
UID, MES = "fk", "2026-05"          # fk tem lançamento no seed em 2026-05
TEM_PDFTOTEXT = shutil.which("pdftotext") is not None

_PROBES: list[str] = []
atexit.register(lambda: [os.remove(p) for p in _PROBES if os.path.exists(p)])


def abrir(uid, mes):
    """Sessão NOVA, com a unidade selecionada uma única vez (como o botão 'Abrir')."""
    path = os.path.join(_REPO_ROOT, "tests", f"_probe_gerar_pdf_{len(_PROBES)}.py")
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


def texto_pdf(caminho):
    return subprocess.run(["pdftotext", "-layout", caminho, "-"], capture_output=True, text=True).stdout


def limpar_wf():
    shutil.rmtree(RUNS_DIR, ignore_errors=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def preparar(status):
    """Competência com um PDF já gerado e o workflow no `status` indicado."""
    limpar_wf()
    rm.generate_report(MES, UID, rm.load_resultado_from_db(MES, UID))
    rm._update_unit(MES, UID, status=status)
    return rm.get_unit_run(MES, UID)


def brl(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


fat_db = rm.load_resultado_from_db(MES, UID).faturamento

print("=" * 70)
print("1 — Cada status não aprovado: rótulo, status final, versão e arquivamento")
print("=" * 70)
for status, arquiva in (("pendente", False), ("gerado", False), ("revisado", True), ("reaberto", True), ("erro", False)):
    antes = preparar(status)
    at = abrir(UID, MES)
    rotulo = at.button(key=f"act_pdf_{UID}").label
    at.button(key=f"act_pdf_{UID}").click().run()
    u = rm.get_unit_run(MES, UID)
    checar(f"1a. [{status}] rótulo do botão é 'Gerar PDF'", rotulo == "Gerar PDF")
    checar(f"1b. [{status}] sem exceção e o workflow termina em 'gerado'", len(at.exception) == 0 and u["status"] == "gerado")
    checar(f"1c. [{status}] versão sobe de {antes['version']} para {antes['version'] + 1}", u["version"] == antes["version"] + 1)
    checar(f"1d. [{status}] arquivamento do PDF anterior {'SIM' if arquiva else 'NÃO'} (status_at_time = {status if arquiva else '—'})",
           len(u["versions"]) == len(antes["versions"]) + (1 if arquiva else 0)
           and (not arquiva or u["versions"][-1]["status_at_time"] == status))
    if TEM_PDFTOTEXT:
        checar(f"1e. [{status}] sem cálculo na sessão: o PDF sai do lançamento persistido (faturamento {brl(fat_db)})",
               brl(fat_db) in texto_pdf(u["pdf_path"]))

print("=" * 70)
print("2 — Resultado da SESSÃO continua com prioridade nas não aprovadas")
print("=" * 70)
preparar("reaberto")
at = abrir(UID, MES)
at.number_input(key=f"fat_{UID}").set_value(1000.0).run()
at.button(key=f"act_calc_{UID}").click().run()
at.button(key=f"act_pdf_{UID}").click().run()
u = rm.get_unit_run(MES, UID)
checar("2a. [reaberto] Calcular(1.000) + Gerar PDF: o workflow termina em 'gerado'", u["status"] == "gerado")
if TEM_PDFTOTEXT:
    t = texto_pdf(u["pdf_path"])
    checar("2b. [reaberto] o PDF traz o valor da SESSÃO (1.000,00), como sempre", "1.000,00" in t and brl(fat_db) not in t)

print("=" * 70)
print("3 — Sem lançamento e sem cálculo")
print("=" * 70)
limpar_wf()
at = abrir(UID, "2026-06")          # fk não tem lançamento em 2026-06
before = rm.load_run("2026-06")
at.button(key=f"act_pdf_{UID}").click().run()
checar("3a. 'Calcule antes de gerar o PDF.' e nenhuma alteração de workflow",
       [e.value for e in at.error] == ["Calcule antes de gerar o PDF."] and rm.load_run("2026-06") == before)

print("=" * 70)
print("4 — Pátio NÃO aprovado, com 'Calcular Pátio' feito na sessão, continua gerando")
print("=" * 70)
limpar_wf()
at = abrir("patio", "2026-06")
rotulos = [b.label for b in at.button]
checar("4a. Pátio não aprovado: botões 'Gerar PDF' (um por contratante)", rotulos.count("Gerar PDF") == 2)
at.number_input(key="fat_patio").set_value(520000.0).run()
at.button(key="calc_patio").click().run()
at.button(key="wf_gen_patio_real").click().run()
u = rm.get_unit_run("2026-06", "patio_real")
checar("4b. 'Gerar PDF' do Pátio REAL: workflow 'gerado', versão 1 e PDF existente",
       u["status"] == "gerado" and u["version"] == 1 and bool(u["pdf_path"]) and Path(u["pdf_path"]).exists())
if TEM_PDFTOTEXT:
    checar("4c. O PDF do Pátio traz o contratante REAL", "REAL" in texto_pdf(u["pdf_path"]))

print()
if _falhas:
    print(f"{len(_falhas)} FALHA(S):")
    for n in _falhas:
        print("  -", n)
    sys.exit(1)
print("Todas as verificações passaram.")
