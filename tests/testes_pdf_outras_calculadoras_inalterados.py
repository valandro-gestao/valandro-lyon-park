"""
Cobertura permanente: o relatório (HTML que vira PDF) das calculadoras que NÃO
são RESULTADO_SPLIT não pode mudar quando o relatório do Medcenter/Viva Open Mall
muda. Compara o HTML normalizado de cada caso com a referência versionada em
tests/golden_pdf/, e confere que o CSS e o logo continuam idênticos.

Cobre uma unidade de cada situação: PERCENTUAL_SIMPLES, COM_ALIQUOTA (com e sem
carregadores), COM_ALIQUOTA_CUMUL (e com_eventos), COM_ALIQUOTA_CUMUL_DU (e o
PDF auxiliar de Direito de Uso), COM_FAIXAS (e com_eventos), COM_ALIQUOTA_SPLIT,
PATIO_MANUTENCAO e o Pátio REAL/MAIOJAMA.

A referência é gerada com `python3 tests/testes_pdf_outras_calculadoras_inalterados.py
--regenerar` e SÓ deve ser regerada de propósito (mudança deliberada de layout
de uma dessas calculadoras, ou do data/seed.db). O data/seed.db versionado muda
só por commit explícito; se mudar, este teste acusa e a referência é revista.

Execução: python3 tests/testes_pdf_outras_calculadoras_inalterados.py
"""
import hashlib, os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_golden_pdf_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "tests"))

import _golden_casos as G

G.preparar_banco()
G.congelar_data()

from app.renderer import render_html, CSS_PATH, LOGO_PATH

GOLDEN_DIR = os.path.join(_REPO_ROOT, "tests", "golden_pdf")
REGENERAR = "--regenerar" in sys.argv

_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


def _sha(caminho: str) -> str:
    with open(caminho, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


ativos = {"report.css": _sha(CSS_PATH), "logo.png": _sha(LOGO_PATH)}

if REGENERAR:
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    for nome, fn in G.casos().items():
        html = G.normalizar_html(render_html(fn()))
        with open(os.path.join(GOLDEN_DIR, f"{nome}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        print(f"gerado: tests/golden_pdf/{nome}.html ({len(html)} bytes)")
    with open(os.path.join(GOLDEN_DIR, "_ativos.sha256"), "w", encoding="utf-8") as f:
        for k, v in sorted(ativos.items()):
            f.write(f"{v}  {k}\n")
    print("Referência regerada — revise o diff antes de commitar.")
    sys.exit(0)

print("=" * 70)
print("1 — CSS e logo do relatório inalterados")
print("=" * 70)
with open(os.path.join(GOLDEN_DIR, "_ativos.sha256"), encoding="utf-8") as f:
    esperados = {l.split("  ", 1)[1].strip(): l.split("  ", 1)[0] for l in f if l.strip()}
for nome, h in ativos.items():
    checar(f"1. {nome} idêntico à referência", esperados.get(nome) == h)

print("=" * 70)
print("2 — HTML de cada calculadora idêntico à referência")
print("=" * 70)
casos = G.casos()
arquivos = sorted(n[:-5] for n in os.listdir(GOLDEN_DIR) if n.endswith(".html"))
checar("2a. Todos os casos têm referência (e vice-versa)", sorted(casos) == arquivos)
for nome, fn in casos.items():
    caminho = os.path.join(GOLDEN_DIR, f"{nome}.html")
    if not os.path.exists(caminho):
        checar(f"2. {nome}: referência ausente", False)
        continue
    atual = G.normalizar_html(render_html(fn()))
    with open(caminho, encoding="utf-8") as f:
        ref = f.read()
    ok = atual == ref
    if not ok:
        import difflib
        d = list(difflib.unified_diff(ref.splitlines(), atual.splitlines(), "referência", "atual", lineterm="", n=1))
        print("   " + "\n   ".join(d[:25]))
    checar(f"2. {nome}: HTML idêntico à referência", ok)

print()
if _falhas:
    print(f"{len(_falhas)} FALHA(S):")
    for n in _falhas:
        print("  -", n)
    sys.exit(1)
print("Todas as verificações passaram.")
