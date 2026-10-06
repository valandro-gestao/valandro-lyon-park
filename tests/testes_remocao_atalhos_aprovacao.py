"""
Cobertura permanente da remoção dos atalhos de aprovação de WORKFLOW da
interface ativa (out/2026):

  - "Aprovar todos" (barra de ações da lista) e o "Aprovar" rápido da linha de
    cada unidade chamavam só `run_manager.mark_approved` — sem recalcular e sem
    gravar o lançamento. Uma unidade `gerado` nunca aprovada individualmente
    (sem linha em `lancamentos`) ficava com workflow `aprovado` sem lançamento.
  - A aprovação oficial passa a acontecer SÓ na tela de detalhe da unidade
    (`_aprovar_unidade`), depois da conferência; "Abrir" é o caminho.

O que esta suíte garante:
  1. A lista não tem "Aprovar todos" nem nenhum botão "Aprovar"/`qaprov_*`;
     "Gerar pendentes", "Baixar ZIP" e "Abrir"/"Reabrir" continuam presentes.
  2. Renderizar a lista não muda nenhum status de workflow.
  3. As funções do lote não existem mais no módulo.
  4. (AST) `mark_approved` só é chamado a partir de `_aprovar_unidade` e da
     aprovação por split do Pátio — nunca de um atalho.
  5. A aprovação individual da tela de detalhe CONTINUA funcionando: lançamento
     `aprovado` + PDF + workflow `aprovado` (ponta a ponta, via AppTest).

Roda em banco SQLite isolado (tempfile), nunca em data/seed.db ou db.sqlite.
Execução: python3 tests/testes_remocao_atalhos_aprovacao.py
"""
import os, sys, tempfile, shutil, atexit, ast

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_remocao_atalhos_")
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
from app import run_manager as rm
from app.models import get_db
from app.engine import load_units

MES = "2026-06"

_PROBE_COUNTER = [0]
_PROBE_PATHS: list[str] = []
atexit.register(lambda: [os.remove(p) for p in _PROBE_PATHS if os.path.exists(p)])


def _probe(selected_unit, mes_ref: str) -> str:
    _PROBE_COUNTER[0] += 1
    path = os.path.join(_REPO_ROOT, "tests", f"_probe_remocao_atalhos_{_PROBE_COUNTER[0]}.py")
    with open(path, "w") as f:
        f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
import streamlit as st
st.session_state.selected_unit = {selected_unit!r}
from app.ui.fechamento import tela_fechamento
tela_fechamento({mes_ref!r})
''')
    _PROBE_PATHS.append(path)
    return path


def _abrir(selected_unit, mes_ref: str = MES) -> AppTest:
    at = AppTest.from_file(_probe(selected_unit, mes_ref), default_timeout=90)
    at.run()
    return at


def _status_workflow() -> dict:
    return {uid: info["status"] for uid, info in rm.load_run(MES).items()}


def _lancamento(uid: str):
    with get_db() as conn:
        return conn.execute(
            "SELECT status FROM lancamentos WHERE unidade_id=? AND mes_referencia=?", (uid, MES)
        ).fetchone()


# Estados de workflow cobrindo todas as linhas possíveis da lista. Nenhuma
# destas unidades tem lançamento na competência — exatamente o cenário em que
# o atalho antigo produzia "aprovado" sem lançamento.
load_units(force=True)
ESTADOS = {
    "fk": "gerado",
    "anitta_mall": "revisado",
    "monza": "aprovado",
    "praia_de_bellas": "reaberto",
    "patio_real": "gerado",
    "patio_maiojama": "gerado",
}
for _uid, _st in ESTADOS.items():
    rm._update_unit(MES, _uid, status=_st)
ANTES = _status_workflow()

# ═══════════════════════════════════════════════════════════════════════
# 1. A lista não oferece mais nenhuma aprovação
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1 — Lista: sem 'Aprovar todos' nem 'Aprovar' rápido; ações restantes intactas")
print("=" * 70)

at = _abrir(None)
rotulos = [(b.label or "") for b in at.button]
chaves = [str(getattr(b, "key", "") or "") for b in at.button]

checar("1a. Lista renderiza sem exceção", len(at.exception) == 0)
checar("1b. Não existe o botão 'Aprovar todos'", "Aprovar todos" not in rotulos)
checar("1c. Não existe nenhum botão com rótulo 'Aprovar' na lista", "Aprovar" not in rotulos)
checar("1d. Não existe nenhum botão com key 'qaprov_*'",
       not any(k.startswith("qaprov_") for k in chaves))
checar("1e. 'Gerar pendentes' continua presente", "Gerar pendentes" in rotulos)
checar("1f. 'Baixar ZIP' continua presente (desabilitado sem PDF)",
       any(r.startswith("Baixar ZIP") for r in rotulos))
for uid in ("fk", "anitta_mall", "monza", "praia_de_bellas"):
    checar(f"1g. '{uid}': botão 'Abrir' presente", f"open_{uid}_{MES}" in chaves)
checar("1h. Unidade aprovada (monza): 'Reabrir' continua presente", f"reab_monza_{MES}" in chaves)
checar("1i. Pátio: 'Abrir' presente para a unidade virtual", f"open_patio_{MES}" in chaves)
checar("1j. Nenhum texto 'Aprovar todos' em markdown/diálogo renderizado",
       "Aprovar todos" not in "\n".join(str(m.value) for m in at.markdown))

# ═══════════════════════════════════════════════════════════════════════
# 2. Renderizar a lista nunca muda workflow nem cria lançamento
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2 — Renderizar a lista não aprova nada")
print("=" * 70)
checar("2a. Status de workflow idêntico depois de renderizar a lista", _status_workflow() == ANTES)
checar("2b. Nenhum lançamento criado para as unidades da lista",
       all(_lancamento(u) is None for u in ESTADOS))

# ═══════════════════════════════════════════════════════════════════════
# 3. Código do lote removido (não fica função órfã com o defeito)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3 — Funções do lote removidas do módulo")
print("=" * 70)
import app.ui.fechamento as fech
checar("3a. _aprovar_todos_gerados não existe mais", not hasattr(fech, "_aprovar_todos_gerados"))
checar("3b. _dialog_confirmar_aprovar_todos não existe mais",
       not hasattr(fech, "_dialog_confirmar_aprovar_todos"))
checar("3c. _aprovar_unidade (aprovação oficial) continua existindo", hasattr(fech, "_aprovar_unidade"))
for _arq in ("app/ui/fechamento.py", "main.py"):
    with open(os.path.join(_REPO_ROOT, _arq), encoding="utf-8") as f:
        _src = f.read()
    checar(f"3d. '{_arq}' sem 'Aprovar todos' / 'qaprov_'",
           "Aprovar todos" not in _src and "qaprov_" not in _src)

# ═══════════════════════════════════════════════════════════════════════
# 4. (AST) mark_approved só é chamado por quem grava o lançamento antes
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4 — mark_approved só dentro de _aprovar_unidade e da aprovação do Pátio")
print("=" * 70)


def _chamadores_mark_approved(caminho: str) -> set[str]:
    with open(caminho, encoding="utf-8") as f:
        arvore = ast.parse(f.read())
    achados = set()
    for fn in ast.walk(arvore):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for no in ast.walk(fn):
                if (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                        and no.func.attr == "mark_approved"):
                    achados.add(fn.name)
    return achados


_chamadores = _chamadores_mark_approved(os.path.join(_REPO_ROOT, "app/ui/fechamento.py"))
checar(f"4a. Chamadores de mark_approved em fechamento.py = "
       f"{{_aprovar_unidade, _barra_acoes_patio}} (achado: {sorted(_chamadores)})",
       _chamadores == {"_aprovar_unidade", "_barra_acoes_patio"})

# ═══════════════════════════════════════════════════════════════════════
# 5. A aprovação individual da tela de detalhe continua funcionando
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5 — Aprovação individual (tela de detalhe) preservada, ponta a ponta")
print("=" * 70)
UID = "fk"
at5 = _abrir(UID)
checar("5a. Detalhe renderiza sem exceção", len(at5.exception) == 0)
checar("5b. Botão 'Aprovar' da tela de detalhe presente (key act_apr_fk)",
       any(str(getattr(b, "key", "")) == f"act_apr_{UID}" for b in at5.button))

at5.number_input(key=f"fat_{UID}").set_value(50000.0).run()
at5.button(key=f"act_apr_{UID}").click().run()

checar("5c. Aprovar no detalhe: sem exceção", len(at5.exception) == 0)
_l = _lancamento(UID)
checar("5d. Lançamento gravado com status 'aprovado'", _l is not None and _l["status"] == "aprovado")
_run = rm.get_unit_run(MES, UID)
checar("5e. Workflow 'aprovado'", _run["status"] == "aprovado")
checar("5f. PDF gerado e existente em disco",
       bool(_run.get("pdf_path")) and os.path.exists(_run["pdf_path"]))
checar("5g. Só a unidade aprovada mudou: demais unidades com o status anterior",
       {u: s for u, s in _status_workflow().items() if u != UID}
       == {u: s for u, s in ANTES.items() if u != UID})

print()
if _falhas:
    print(f"{len(_falhas)} FALHA(S):")
    for n in _falhas:
        print("  -", n)
    sys.exit(1)
print("Todas as verificações passaram.")
