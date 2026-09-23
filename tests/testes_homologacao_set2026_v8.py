"""
Cobertura permanente da 8ª rodada de homologação de set/2026 (produção real
— Débora, EKOS/OKA). Achado: o PDF de unidades `COM_ALIQUOTA_CUMUL` só
mostrava a linha "(+/-) Prejuízo Acumulado" quando `"prejuizo"` estava
presente em `cfg["relatorio"]["linhas"]` — uma config estrutural por
unidade (fora de `parametros_vigentes`). As 6 unidades já homologadas desse
tipo (Viva Trindade, W Tower, Dom Pedro, Anitta Mall, A. Schneider, ILP, MW
Tristeza) têm "prejuizo" nessa lista; EKOS/OKA não têm (herdado de uma
config anterior à correção deste tipo_calculo) — o PDF pulava de
"Resultado" direto para "Repasse", mesmo com o acumulado sendo usado
corretamente no cálculo do repasse (confirmado: o número do repasse nunca
esteve errado, só a apresentação).

Corrigido em app/reporter.py (_prestacao_padrao): a condição passou a ser
orientada ao DADO do próprio `ResultadoUnidade`
(`r.prejuizo_acumulado_entrada or r.prejuizo_acumulado_saida`), não mais à
config `relatorio.linhas`. `COM_ALIQUOTA_CUMUL` é o único tipo que passa
por este builder e de fato preenche esses dois campos — `COM_ALIQUOTA`/
`PERCENTUAL_SIMPLES` nunca os tocam (ficam 0.0/0.0 por padrão do
dataclass), então a linha continua oculta para eles. Nenhum valor é
recalculado no reporter — só o que o calculator já retornou é lido.

Execução: python3 tests/testes_homologacao_set2026_v8.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v8_")
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
# 1. Cadeia real EKOS julho -> agosto (relatorio.linhas SEM "prejuizo",
#    réplica exata da config herdada de EKOS/OKA)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. Cadeia EKOS julho -> agosto — PDF mostra o acumulado sem 'prejuizo' em linhas_cfg")
print("=" * 70)
from app.calculators.cumulativo import calcular_com_aliquota_cumul
from app.reporter import _prestacao_padrao

# Réplica da config estrutural herdada por EKOS/OKA (sem "prejuizo" —
# causa raiz confirmada).
CFG_EKOS = {
    "id": "ekos", "aliquota_imposto": 0.1425, "ponto_equilibrio": 6550.0,
    "taxa_cobranca": 0.015, "percentual_aluguel": 0.85,
    "relatorio": {"linhas": ["faturamento", "aliquota", "taxa_cobranca",
                              "subtotal", "pe", "custos", "resultado", "total_aluguel"]},
}
checar("Config de teste replica o cenário real: 'prejuizo' NÃO está em relatorio.linhas",
       "prejuizo" not in CFG_EKOS["relatorio"]["linhas"])


def _linha(prestacao, substr):
    return next((l for l in prestacao.linhas if substr in l.descricao), None)


# --- Julho: golden real, resultado -4.110,61 gera o acumulado ---
r_jul = calcular_com_aliquota_cumul(
    CFG_EKOS, "2026-07", faturamento=2895.42, saldo_override=0.0,
    custos_extras={"base_calculo_taxa_cobranca": 2895.42},
)
checar("Julho: Resultado = -R$ 4.110,61 (golden real)", r_jul.resultado == -4110.61)
checar("Julho: prejuizo_acumulado_saida = -4.110,61 (gera o acumulado para agosto)",
       r_jul.prejuizo_acumulado_saida == -4110.61)

prest_jul = _prestacao_padrao(r_jul, CFG_EKOS)
linha_prej_jul = _linha(prest_jul, "Prejuízo Acumulado")
checar("Julho: PDF já mostra '(+/-) Prejuízo Acumulado' (mês em que o acumulado nasce)",
       linha_prej_jul is not None)
checar("Julho: valor mostrado é -4.110,61, igual ao do calculator (sem recalcular)",
       linha_prej_jul is not None and linha_prej_jul.valor == r_jul.prejuizo_acumulado_saida)
idx_resultado_jul = next(i for i, l in enumerate(prest_jul.linhas) if l.descricao == "Resultado")
idx_repasse_jul = next(i for i, l in enumerate(prest_jul.linhas) if l.descricao == "Repasse")
idx_prej_jul = prest_jul.linhas.index(linha_prej_jul)
checar("Julho: ordem Resultado -> Prejuízo Acumulado -> Repasse",
       idx_resultado_jul < idx_prej_jul < idx_repasse_jul)

# --- Agosto: recebe a saída de julho como entrada, mostra a NOVA saída ---
r_ago = calcular_com_aliquota_cumul(
    CFG_EKOS, "2026-08", faturamento=5000.0, saldo_override=r_jul.prejuizo_acumulado_saida,
    custos_extras={"base_calculo_taxa_cobranca": 5000.0},
)
checar("Agosto: prejuizo_acumulado_entrada = saída de julho (-4.110,61), cadeia correta",
       r_ago.prejuizo_acumulado_entrada == r_jul.prejuizo_acumulado_saida)
checar("Agosto: prejuizo_acumulado_saida é a NOVA saída (diferente da de julho)",
       r_ago.prejuizo_acumulado_saida != r_jul.prejuizo_acumulado_saida)

prest_ago = _prestacao_padrao(r_ago, CFG_EKOS)
linha_prej_ago = _linha(prest_ago, "Prejuízo Acumulado")
checar("Agosto: PDF mostra '(+/-) Prejuízo Acumulado' (sem depender de linhas_cfg)",
       linha_prej_ago is not None)
checar("Agosto: valor mostrado é a NOVA saída (não a de julho, não recalculado)",
       linha_prej_ago is not None and linha_prej_ago.valor == r_ago.prejuizo_acumulado_saida)
idx_resultado_ago = next(i for i, l in enumerate(prest_ago.linhas) if l.descricao == "Resultado")
idx_repasse_ago = next(i for i, l in enumerate(prest_ago.linhas) if l.descricao == "Repasse")
idx_prej_ago = prest_ago.linhas.index(linha_prej_ago)
checar("Agosto: ordem Resultado -> Prejuízo Acumulado -> Repasse mantida",
       idx_resultado_ago < idx_prej_ago < idx_repasse_ago)


# ═══════════════════════════════════════════════════════════════════════
# 2. Competência sem entrada/saída de acumulado não mostra linha R$ 0,00
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Sem prejuízo acumulado (entrada e saída = 0), a linha continua oculta")
print("=" * 70)
CFG_SEM_ACUMULADO = dict(CFG_EKOS)
# Faturamento suficiente para cobrir PE sem deixar resultado_com_prejuizo
# negativo -> prejuizo_acumulado_saida fica 0.0, e entrada também é 0.0
# (saldo_override explícito) — cenário "nunca teve prejuízo acumulado".
r_sem = calcular_com_aliquota_cumul(
    CFG_SEM_ACUMULADO, "2026-07", faturamento=20000.0, saldo_override=0.0,
    custos_extras={"base_calculo_taxa_cobranca": 20000.0},
)
checar("Cenário de controle: entrada = 0.0 e saída = 0.0",
       r_sem.prejuizo_acumulado_entrada == 0.0 and r_sem.prejuizo_acumulado_saida == 0.0)
prest_sem = _prestacao_padrao(r_sem, CFG_SEM_ACUMULADO)
checar("Sem entrada/saída de acumulado, a linha 'Prejuízo Acumulado' NÃO aparece (não vira R$ 0,00)",
       _linha(prest_sem, "Prejuízo Acumulado") is None)


# ═══════════════════════════════════════════════════════════════════════
# 3. Regressão: demais COM_ALIQUOTA_CUMUL (relatorio.linhas COM "prejuizo")
#    continuam exatamente iguais
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Regressão — unidades que já tinham 'prejuizo' em linhas_cfg não mudam")
print("=" * 70)
CFG_VIVA = {
    "id": "viva_trindade", "aliquota_imposto": 0.0, "percentual_aluguel": 0.85,
    "ponto_equilibrio": 0.0,
    "relatorio": {"linhas": ["faturamento", "aliquota", "subtotal", "pe", "condominio",
                              "iptu", "resultado", "prejuizo", "aluguel",
                              "investimentos", "saldo_a_pagar"]},
}
r_viva = calcular_com_aliquota_cumul(
    CFG_VIVA, "2026-08", faturamento=-1525.24 + 2400.0, saldo_override=-157142.75,
    custos_extras={"outras_despesas": 2400.0},
)
checar("Regressão: golden da Viva Trindade continua -158.667,99",
       r_viva.prejuizo_acumulado_saida == -158667.99)
prest_viva = _prestacao_padrao(r_viva, CFG_VIVA)
linha_viva = _linha(prest_viva, "Prejuízo Acumulado")
checar("Regressão: Viva Trindade (já tinha 'prejuizo' em linhas_cfg) continua mostrando a linha",
       linha_viva is not None and linha_viva.valor == -158667.99)


# ═══════════════════════════════════════════════════════════════════════
# 4. COM_ALIQUOTA e PERCENTUAL_SIMPLES continuam sem linha indevida
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. COM_ALIQUOTA / PERCENTUAL_SIMPLES — nenhuma linha indevida")
print("=" * 70)
from app.calculators.base import calcular_com_aliquota, calcular_percentual_simples

CFG_ALIQ = {"id": "fk_teste", "aliquota_imposto": 0.1425, "ponto_equilibrio": 1000.0,
            "percentual_aluguel": 0.85,
            "relatorio": {"linhas": ["faturamento", "aliquota", "subtotal", "pe", "resultado", "aluguel"]}}
r_aliq = calcular_com_aliquota(CFG_ALIQ, "2026-07", faturamento=50000.0)
checar("COM_ALIQUOTA nunca preenche prejuizo_acumulado_entrada/saida (ficam 0.0/0.0)",
       r_aliq.prejuizo_acumulado_entrada == 0.0 and r_aliq.prejuizo_acumulado_saida == 0.0)
prest_aliq = _prestacao_padrao(r_aliq, CFG_ALIQ)
checar("COM_ALIQUOTA: PDF não mostra 'Prejuízo Acumulado' (nunca teve essa config)",
       _linha(prest_aliq, "Prejuízo Acumulado") is None)

CFG_SIMPLES = {"id": "vasco_teste", "ponto_equilibrio": 1000.0, "percentual_aluguel": 0.1,
               "relatorio": {"linhas": ["faturamento", "resultado", "aluguel"]}}
r_simples = calcular_percentual_simples(CFG_SIMPLES, "2026-07", faturamento=5000.0)
checar("PERCENTUAL_SIMPLES nunca preenche prejuizo_acumulado_entrada/saida (ficam 0.0/0.0)",
       r_simples.prejuizo_acumulado_entrada == 0.0 and r_simples.prejuizo_acumulado_saida == 0.0)
prest_simples = _prestacao_padrao(r_simples, CFG_SIMPLES)
checar("PERCENTUAL_SIMPLES: PDF não mostra 'Prejuízo Acumulado'",
       _linha(prest_simples, "Prejuízo Acumulado") is None)


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 8) PASSARAM ===")
