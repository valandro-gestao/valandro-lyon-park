"""
Cobertura permanente da 4ª rodada de homologação de set/2026 (produção real
— Débora, Viva Trindade já validada em produção).

Único achado desta rodada: inconsistência de APRESENTAÇÃO na memória de
cálculo exibida na tela de Fechamento (não na fórmula, que está correta e
já validada — agosto/2026 chega a `prejuizo_acumulado_saida = -158.667,99`,
ver tests/testes_homologacao_set2026_v3.py). A tabela da tela mostrava
Receita → Impostos → Subtotal → PE → Condomínio → Resultado → Repasse e
omitia "Outras Despesas" (que o PDF já mostra corretamente, via
app.reporter._prestacao_padrao) — o valor já estava correto no cálculo,
só não aparecia na memória visual.

Corrigido em app/ui/fechamento.py:
  - `_valor_outras_despesas`/`_valor_investimentos`: funções puras que
    decidem se/como cada rubrica aparece na memória de cálculo, com EXATAMENTE
    a mesma condição já usada no PDF (`app.reporter._prestacao_padrao`) —
    outras_despesas sempre que presente; investimentos só quando não há
    saldo_a_pagar (regime pós-repasse antigo, mostrado via aluguel líquido).
  - `_dre_rows_unit`: extraído de `_mostrar_resultado_unit` para função pura
    (mesmas linhas, mesma ordem, só sem chamadas Streamlit) — usa só o que
    o calculator já retornou em `r`/`r.extras`, nunca recalcula.
  - `_build_dre_rows` (memória histórica de "Competências anteriores"): usa
    os mesmos dois helpers, mesma correção, mesmo motivo.

Nenhuma fórmula financeira, aprovação ou persistência foi alterada — só a
apresentação (mesmas garantias validadas em
tests/testes_homologacao_set2026_v3.py continuam intactas).

Execução: python3 tests/testes_homologacao_set2026_v4.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v4_")
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


# ═══════════════════════════════════════════════════════════════════════
# 1. Memória de cálculo (tela) — Outras Despesas e Investimentos aparecem
#    na posição correta, sem alterar o valor final
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. _dre_rows_unit — Outras Despesas antes de Resultado, Investimentos depois")
print("=" * 70)
from app.models import ResultadoUnidade
from app.ui.fechamento import (
    _dre_rows_unit, _valor_outras_despesas, _valor_investimentos,
)


def _r(**kw) -> ResultadoUnidade:
    base = dict(
        unidade_id="viva_trindade", mes_referencia="2026-08",
        faturamento=100000.0, subtotal=100000.0, ponto_equilibrio=0.0,
        custos={}, resultado=-1525.24,
        prejuizo_acumulado_entrada=-157142.75, prejuizo_acumulado_saida=-158667.99,
        aluguel_calculado=0.0, extras={},
    )
    base.update(kw)
    return ResultadoUnidade(**base)


def _index(rows, label):
    for i, (lbl, _) in enumerate(rows):
        if lbl == label:
            return i
    return None


# --- 1a. Reprodução exata do caso reportado: agosto/2026 Viva Trindade,
#     Outras Despesas = 2.400,00, já descontada do Resultado pelo calculator.
print("--- 1a. Caso real reportado (agosto/2026, Outras Despesas = 2.400,00) ---")
r_agosto = _r(extras={"outras_despesas": 2400.0})
rows = _dre_rows_unit(r_agosto)
labels = [lbl for lbl, _ in rows]

checar("'(-) Outras Despesas' aparece na memória de cálculo",
       "(-) Outras Despesas" in labels)
i_od, i_res = _index(rows, "(-) Outras Despesas"), _index(rows, "Resultado")
checar("Outras Despesas aparece ANTES de Resultado",
       i_od is not None and i_res is not None and i_od < i_res)
checar("Valor de Outras Despesas exibido é (R$ 2.400,00) — mesmo valor do cálculo",
       dict(rows)["(-) Outras Despesas"] == "(R$ 2.400,00)")
checar("Resultado exibido continua -R$ 1.525,24 (valor final não muda com a apresentação)",
       dict(rows)["Resultado"] == "(R$ 1.525,24)")
checar("Nenhuma linha de Investimentos quando extras não tem essa rubrica",
       "(-) Investimentos" not in labels)


# --- 1b. Investimentos > 0 aparece DEPOIS de Resultado (regime v1.2.0,
#     sem saldo_a_pagar) — coexistindo com Outras Despesas.
print("--- 1b. Outras Despesas + Investimentos coexistindo, cada um na sua posição ---")
r_ambos = _r(resultado=-2000.0, extras={"outras_despesas": 2400.0, "investimentos": 500.0})
rows2 = _dre_rows_unit(r_ambos)
labels2 = [lbl for lbl, _ in rows2]
i_od2, i_res2, i_inv2 = (_index(rows2, "(-) Outras Despesas"),
                          _index(rows2, "Resultado"),
                          _index(rows2, "(-) Investimentos"))
checar("Ambas as rubricas coexistem na memória de cálculo",
       "(-) Outras Despesas" in labels2 and "(-) Investimentos" in labels2)
checar("Outras Despesas continua antes de Resultado mesmo com Investimentos presente",
       i_od2 < i_res2)
checar("Investimentos aparece DEPOIS de Resultado",
       i_inv2 is not None and i_res2 < i_inv2)
checar("Valor de Investimentos exibido é (R$ 500,00)",
       dict(rows2)["(-) Investimentos"] == "(R$ 500,00)")


# --- 1c. Regime antigo (saldo_a_pagar): Investimentos NÃO vira uma linha
#     separada — o líquido já está na própria linha de Repasse/Saldo a
#     Pagar (mesma regra do PDF, evita duplicar a dedução).
print("--- 1c. Regime antigo (saldo_a_pagar) não duplica a dedução de Investimentos ---")
r_antigo = _r(unidade_id="w_tower", aluguel_calculado=1000.0,
              extras={"investimentos": 300.0, "saldo_a_pagar": 700.0})
rows3 = _dre_rows_unit(r_antigo)
labels3 = [lbl for lbl, _ in rows3]
checar("Sem saldo_a_pagar? não é este caso — aqui a linha (-) Investimentos NÃO aparece",
       "(-) Investimentos" not in labels3)
checar("'Saldo a Pagar' aparece como linha final com o valor líquido",
       ("Saldo a Pagar", "R$ 700,00") in rows3)


# --- 1d. Valores zero/ausentes continuam ocultos (padrão visual já
#     existente para rubricas opcionais) — nem Outras Despesas nem
#     Investimentos aparecem quando não há valor.
print("--- 1d. Rubricas com valor zero/ausente continuam ocultas ---")
r_zerado = _r(extras={})
rows4 = _dre_rows_unit(r_zerado)
labels4 = [lbl for lbl, _ in rows4]
checar("extras vazio -> nenhuma das duas linhas aparece",
       "(-) Outras Despesas" not in labels4 and "(-) Investimentos" not in labels4)
checar("_valor_outras_despesas(extras vazio) é None", _valor_outras_despesas({}) is None)
checar("_valor_investimentos(extras vazio) é None", _valor_investimentos({}) is None)
checar("_valor_outras_despesas com 0.0 explícito continua None (oculto)",
       _valor_outras_despesas({"outras_despesas": 0.0}) is None)


# ═══════════════════════════════════════════════════════════════════════
# 2. Memória histórica (Competências anteriores) — mesma correção, mesmo
#    motivo, testada via _valor_outras_despesas/_valor_investimentos
#    (as mesmas funções puras usadas por _build_dre_rows).
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Helpers da memória histórica (mesmo cálculo usado por _build_dre_rows)")
print("=" * 70)
extras_historico_ago = {"outras_despesas": 2400.0}
extras_historico_jul = {}  # julho não teve Outras Despesas
checar("Agosto (histórico): Outras Despesas presente -> valor negativo formatável",
       _valor_outras_despesas(extras_historico_ago) == -2400.0)
checar("Julho (histórico): sem Outras Despesas -> None (célula fica '—')",
       _valor_outras_despesas(extras_historico_jul) is None)


# ═══════════════════════════════════════════════════════════════════════
# 3. Ponta a ponta: calculator real (cumulativo.py, INTOCADO) -> extras ->
#    memória de cálculo. Confirma que a apresentação usa exatamente o valor
#    que o calculator produziu, sem recalcular nada na UI, e reproduz a
#    cadeia oficial de agosto/2026 (golden já validado em produção).
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Ponta a ponta com o calculator real — agosto/2026 Viva Trindade")
print("=" * 70)
from app.calculators.cumulativo import calcular_com_aliquota_cumul

cfg_agosto = {
    "id": "viva_trindade", "aliquota_imposto": 0.0, "percentual_aluguel": 0.85,
    "ponto_equilibrio": 0.0,
    "custos_variaveis": {"investimentos": 0.0},
}
r_golden = calcular_com_aliquota_cumul(
    cfg_agosto, "2026-08", faturamento=-1525.24 + 2400.0,
    saldo_override=-157142.75,
    custos_extras={"outras_despesas": 2400.0},
)
# Confirma que o cenário reproduz o golden já validado em produção antes de
# checar a apresentação (nenhuma mudança de fórmula nesta rodada).
checar("Golden segue válido: prejuizo_acumulado_saida = -158.667,99",
       r_golden.prejuizo_acumulado_saida == -158667.99)
checar("Golden segue válido: resultado = -1.525,24 (já líquido de Outras Despesas)",
       r_golden.resultado == -1525.24)

rows_golden = _dre_rows_unit(r_golden)
labels_golden = [lbl for lbl, _ in rows_golden]
i_od_g, i_res_g = _index(rows_golden, "(-) Outras Despesas"), _index(rows_golden, "Resultado")
checar("Memória de cálculo do golden mostra '(-) Outras Despesas' antes de 'Resultado'",
       i_od_g is not None and i_res_g is not None and i_od_g < i_res_g)
checar("Memória de cálculo do golden mostra Outras Despesas = (R$ 2.400,00)",
       dict(rows_golden)["(-) Outras Despesas"] == "(R$ 2.400,00)")
checar("Memória de cálculo do golden mostra Resultado = -R$ 1.525,24 (inalterado)",
       dict(rows_golden)["Resultado"] == "(R$ 1.525,24)")


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 4) PASSARAM ===")
