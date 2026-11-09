"""
Cobertura permanente da Quitação de Prejuízo Acumulado (v1.4.0 — rubrica
mensal `quitacao_prejuizo` de COM_ALIQUOTA_CUMUL, caso Ekos out/2026).

Regra aprovada: o recebimento de terceiro liquida EXCLUSIVAMENTE o saldo
histórico de ENTRADA; não é faturamento, não altera o resultado operacional;
o repasse incide sobre o resultado disponível DEPOIS de o saldo ser liquidado;
o excedente fica pendente de conciliação (fora de receita, repasse e saldo
futuro); só o prejuízo remanescente vai para o mês seguinte; histórico
(jul–set) e demais unidades não mudam.

Execução: python3 tests/testes_quitacao_prejuizo.py
"""
import json, os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_quitacao_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "tests"))

import _golden_casos as G

G.preparar_banco()          # banco isolado = seed + todas as migrations

from app import engine
from app.models import (
    criar_unidade, salvar_parametros, salvar_lancamento, get_saldo_entrada, get_db,
    ResultadoUnidade, CADEIA_SALDO_DESDE,
)
from app.calculadora_schema import rubricas_mensais_ativas, rubricas_mensais_do_tipo
from app.ui import fechamento as fch

_falhas = []


def checar(nome, condicao):
    print(f"{'[OK]' if condicao else '[FALHOU]'} {nome}")
    if not condicao:
        _falhas.append(nome)


def prox(a, b, tol=0.005):
    return abs(a - b) < tol


# Unidade "Ekos-like": mesmos parâmetros do cenário (PE 6.550, imposto 14,25%,
# taxa de cobrança 1,5%, repasse 75%) — nunca toca a Ekos real nem produção.
EK, OUTRA = "ekos_teste", "outra_cumul_teste"
for uid, flag in ((EK, True), (OUTRA, False)):
    criar_unidade(id=uid, nome=uid, contratante="T", inicio="2026-07-01", tipo_calculo="COM_ALIQUOTA_CUMUL")
    p = {"aliquota_imposto": 0.1425, "ponto_equilibrio": 6550.0, "percentual_aluguel": 0.75, "taxa_cobranca": 0.015}
    if flag:
        p["tem_quitacao_prejuizo"] = True
    salvar_parametros(uid, "2026-07", p, alterado_por="teste")
engine.load_units(force=True)

E = -4858.56
FAT_POS = 9500.09     # rascunho real: resultado operacional +1.453,83
FAT_NEG = 5000.0      # resultado operacional -2.337,50


def calc(uid, fat, q=None, entrada=E, mes="2026-10"):
    extras = {} if q is None else {"quitacao_prejuizo": q}
    return engine.calcular(uid, mes, faturamento=fat, saldo_override=entrada, custos_extras=extras)


# ═══ 1. cenários numéricos (resultado operacional positivo e negativo) ═══════
print("=" * 70, "\n1. Cenários — integral, parcial, excedente, resultado + e -\n" + "=" * 70)
base_pos = calc(EK, FAT_POS)                      # sem quitação (referência)
checar("referência sem quitação: resultado 1.453,83, saída -3.404,73, repasse 0",
       prox(base_pos.resultado, 1453.83) and prox(base_pos.prejuizo_acumulado_saida, -3404.73)
       and base_pos.aluguel_calculado == 0.0)

r = calc(EK, FAT_POS, 4858.56)                    # INTEGRAL, resultado positivo
checar("integral/resultado+: aplicada 4.858,56, excedente 0, entrada ajustada 0",
       prox(r.extras["quitacao_prejuizo_aplicada"], 4858.56) and r.extras["quitacao_prejuizo_excedente"] == 0
       and r.extras["prejuizo_acumulado_entrada_ajustada"] == 0)
checar("integral/resultado+: repasse = 75% de 1.453,83 = 1.090,37; saída 0",
       prox(r.aluguel_calculado, 1090.37) and r.prejuizo_acumulado_saida == 0.0)
checar("integral: entrada gravada continua -4.858,56 (cadeia íntegra)", r.prejuizo_acumulado_entrada == E)
checar("integral: valor recebido preservado em extras", r.extras["quitacao_prejuizo"] == 4858.56)
checar("sem status de pendência quando não há excedente", "quitacao_prejuizo_excedente_status" not in r.extras)

r_neg = calc(EK, FAT_NEG, 4858.56)                # INTEGRAL, resultado negativo
checar("integral/resultado-: só o prejuízo operacional de out vai p/ novembro (-2.337,50)",
       prox(r_neg.resultado, -2337.50) and prox(r_neg.prejuizo_acumulado_saida, -2337.50) and r_neg.aluguel_calculado == 0.0)

r_par = calc(EK, FAT_POS, 2000.0)                 # PARCIAL: sobra saldo histórico
checar("parcial: aplicada 2.000, entrada ajustada -2.858,56, excedente 0",
       prox(r_par.extras["quitacao_prejuizo_aplicada"], 2000.0)
       and prox(r_par.extras["prejuizo_acumulado_entrada_ajustada"], -2858.56) and r_par.extras["quitacao_prejuizo_excedente"] == 0)
checar("parcial: resultado de out absorve o resto; saída -1.404,73; sem repasse",
       prox(r_par.prejuizo_acumulado_saida, -1404.73) and r_par.aluguel_calculado == 0.0)
r_par_neg = calc(EK, FAT_NEG, 2000.0)
checar("parcial/resultado-: saída = entrada ajustada + resultado = -5.196,06",
       prox(r_par_neg.prejuizo_acumulado_saida, -2858.56 - 2337.50))

r_exc = calc(EK, FAT_POS, 6000.0)                 # EXCEDENTE de 1.141,44
checar("excedente: aplicada limitada ao saldo (4.858,56), excedente 1.141,44",
       prox(r_exc.extras["quitacao_prejuizo_aplicada"], 4858.56) and prox(r_exc.extras["quitacao_prejuizo_excedente"], 1141.44))
checar("excedente: identificado como pendente de conciliação",
       r_exc.extras["quitacao_prejuizo_excedente_status"] == "pendente_conciliacao")
checar("excedente: NÃO altera repasse (= integral), saldo, faturamento nem resultado",
       r_exc.aluguel_calculado == r.aluguel_calculado and r_exc.prejuizo_acumulado_saida == r.prejuizo_acumulado_saida
       and r_exc.faturamento == r.faturamento and r_exc.resultado == r.resultado)
checar("excedente nunca vira saldo positivo", r_exc.prejuizo_acumulado_saida <= 0
       and r_exc.extras["prejuizo_acumulado_entrada_ajustada"] <= 0)
checar("excedente não aparece como custo/receita (r.custos e subtotal intactos)",
       r_exc.custos == base_pos.custos and r_exc.subtotal == base_pos.subtotal and "quitacao_prejuizo" not in r_exc.custos)

r_zero = calc(EK, FAT_POS, 4858.56, entrada=0.0)  # sem saldo em aberto
checar("entrada 0 + recebimento: nada aplicado, tudo pendente de conciliação",
       r_zero.extras["quitacao_prejuizo_aplicada"] == 0 and prox(r_zero.extras["quitacao_prejuizo_excedente"], 4858.56)
       and prox(r_zero.aluguel_calculado, 0.75 * 1453.83))

r_neg_input = calc(EK, FAT_POS, -100.0)
checar("valor negativo é tratado como zero (nada aplicado)",
       r_neg_input.prejuizo_acumulado_saida == base_pos.prejuizo_acumulado_saida and "quitacao_prejuizo" not in r_neg_input.extras)

# invariantes: resultado operacional / faturamento / subtotal nunca mudam
for nome, rr in (("integral", r), ("parcial", r_par), ("excedente", r_exc)):
    checar(f"{nome}: faturamento, subtotal, resultado e custos idênticos ao cálculo sem quitação",
           (rr.faturamento, rr.subtotal, rr.resultado, rr.custos) ==
           (base_pos.faturamento, base_pos.subtotal, base_pos.resultado, base_pos.custos))
print()

# ═══ 2. unidades que NÃO usam a rubrica ficam idênticas ═════════════════════
print("=" * 70, "\n2. Outras unidades COM_ALIQUOTA_CUMUL — nenhuma mudança\n" + "=" * 70)
ref = calc(OUTRA, FAT_POS)
for q in (None, 0.0, 4858.56):
    rr = calc(OUTRA, FAT_POS, q)
    checar(f"sem a flag, quitacao_prejuizo={q} é ignorada (resultado idêntico ao sem rubrica)",
           rr.__dict__ == ref.__dict__ and not any(k.startswith("quitacao") for k in rr.extras))
checar("Q=0 na unidade COM a flag também é idêntico ao cálculo sem a rubrica",
       calc(EK, FAT_POS, 0.0).__dict__ == calc(EK, FAT_POS).__dict__)
checar("a rubrica só é oferecida a quem liga tem_quitacao_prejuizo",
       "quitacao_prejuizo" in rubricas_mensais_do_tipo("COM_ALIQUOTA_CUMUL")
       and "quitacao_prejuizo" in rubricas_mensais_ativas("COM_ALIQUOTA_CUMUL", engine.get_unit_com_params(EK, "2026-10"))
       and "quitacao_prejuizo" not in rubricas_mensais_ativas("COM_ALIQUOTA_CUMUL", engine.get_unit_com_params(OUTRA, "2026-10")))
checar("outros tipos de cálculo não ganham a rubrica",
       all("quitacao_prejuizo" not in rubricas_mensais_do_tipo(t)
           for t in ("COM_ALIQUOTA", "COM_FAIXAS", "PERCENTUAL_SIMPLES", "COM_ALIQUOTA_CUMUL_DU")))
checar("campo do Fechamento só existe com a flag",
       "quitacao_prejuizo" in [i.id for i in fch._itens_custos_variaveis(engine.get_unit_com_params(EK, "2026-10"))]
       and "quitacao_prejuizo" not in [i.id for i in fch._itens_custos_variaveis(engine.get_unit_com_params(OUTRA, "2026-10"))])
checar("é rubrica mensal NÃO vigência (nunca vira parametros_vigentes ao aprovar)",
       fch._e_rubrica_mensal_nao_vigente("COM_ALIQUOTA_CUMUL", "quitacao_prejuizo"))
print()

# ═══ 3. cadeia real + histórico jul–set preservado + transporte p/ novembro ══
print("=" * 70, "\n3. Cadeia Jul–Set -> Out com quitação -> Nov\n" + "=" * 70)
UID = "ekos_cadeia"
criar_unidade(id=UID, nome=UID, contratante="T", inicio="2026-07-01", tipo_calculo="COM_ALIQUOTA_CUMUL")
salvar_parametros(UID, "2026-07", {"aliquota_imposto": 0.1425, "ponto_equilibrio": 6550.0, "percentual_aluguel": 0.75,
                                   "taxa_cobranca": 0.015}, alterado_por="teste")
salvar_parametros(UID, "2026-10", {"tem_quitacao_prejuizo": True}, alterado_por="teste")   # ativação só em out
engine.load_units(force=True)
for mes, ent, sai in (("2026-07", 0.0, -4110.61), ("2026-08", -4110.61, -5717.09), ("2026-09", -5717.09, -4858.56)):
    salvar_lancamento(ResultadoUnidade(unidade_id=UID, mes_referencia=mes, faturamento=1000.0, resultado=sai - ent,
                                       prejuizo_acumulado_entrada=ent, prejuizo_acumulado_saida=sai, status="aprovado"))


def _snapshot():
    with get_db() as c:
        return [tuple(x) for x in c.execute(
            "SELECT unidade_id, mes_referencia, faturamento, resultado_json, status FROM lancamentos "
            "WHERE unidade_id=? AND mes_referencia<'2026-10' ORDER BY mes_referencia", (UID,)).fetchall()]


hist_antes = _snapshot()
checar("entrada de outubro vem da saída de setembro (-4.858,56)", get_saldo_entrada(UID, "2026-10") == -4858.56)
out = engine.calcular(UID, "2026-10", faturamento=FAT_POS, custos_extras={"quitacao_prejuizo": 4858.56})
checar("outubro pela cadeia real: repasse 1.090,37, saída 0", prox(out.aluguel_calculado, 1090.37) and out.prejuizo_acumulado_saida == 0)
out.status = "aprovado"
salvar_lancamento(out)
with get_db() as c:
    gravado = json.loads(c.execute("SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia='2026-10'",
                                   (UID,)).fetchone()[0])
checar("dados persistidos: recebido, aplicado, excedente e entrada original/ajustada",
       gravado["extras"]["quitacao_prejuizo"] == 4858.56 and gravado["extras"]["quitacao_prejuizo_aplicada"] == 4858.56
       and gravado["extras"]["quitacao_prejuizo_excedente"] == 0 and gravado["prejuizo_acumulado_entrada"] == -4858.56
       and gravado["extras"]["prejuizo_acumulado_entrada_ajustada"] == 0)
checar("histórico jul–set byte a byte intacto depois de aprovar outubro", _snapshot() == hist_antes)
checar("reabrir outubro: o valor recebido já lançado volta como default do campo",
       fch._valor_ja_lancado(UID, "2026-10", "quitacao_prejuizo") == 4858.56)
_cfg_uid = engine.get_unit_com_params(UID, "2026-10")
_params = fch._coletar_params_usados(UID, _cfg_uid, None, {"quitacao_prejuizo": 4858.56})
checar("aprovar não grava a quitação como vigência (nenhum parâmetro quitacao_prejuizo)",
       not any("quitacao_prejuizo" in k and k != "tem_quitacao_prejuizo" for k in _params))
checar("novembro herda saída 0 de outubro (nada do saldo quitado volta)", get_saldo_entrada(UID, "2026-11") == 0.0)
nov = engine.calcular(UID, "2026-11", faturamento=FAT_POS)
checar("novembro sem a rubrica (nunca herdada): sem chaves de quitação e sem prejuízo", not any(k.startswith("quitacao") for k in nov.extras)
       and nov.prejuizo_acumulado_entrada == 0.0)

# remanescente: resultado negativo de out -> só o prejuízo operacional segue
UID2 = "ekos_cadeia_neg"
criar_unidade(id=UID2, nome=UID2, contratante="T", inicio="2026-07-01", tipo_calculo="COM_ALIQUOTA_CUMUL")
salvar_parametros(UID2, "2026-07", {"aliquota_imposto": 0.1425, "ponto_equilibrio": 6550.0, "percentual_aluguel": 0.75,
                                    "taxa_cobranca": 0.015, "tem_quitacao_prejuizo": True,
                                    "saldo_acumulado_inicial": -4858.56}, alterado_por="teste")
engine.load_units(force=True)
o2 = engine.calcular(UID2, "2026-10", faturamento=FAT_NEG, custos_extras={"quitacao_prejuizo": 4858.56})
o2.status = "aprovado"; salvar_lancamento(o2)
checar("transporte: novembro herda só o prejuízo operacional remanescente (-2.337,50)",
       prox(get_saldo_entrada(UID2, "2026-11"), -2337.50))
print()

# ═══ 4. demonstração no Fechamento (tela) e no PDF ═══════════════════════════
print("=" * 70, "\n4. Fechamento (memória de cálculo) e PDF\n" + "=" * 70)
rows = dict(fch._dre_rows_unit(r_exc))
chaves = list(rows)
checar("tela: saldo histórico anterior, recebida, aplicada, excedente pendente, saldo após e final",
       rows["Saldo histórico anterior (prejuízo acumulado)"] == fch._fmt(E)
       and rows["(+) Quitação recebida"] == fch._fmt(6000.0)
       and rows["(+) Quitação aplicada ao saldo histórico"] == fch._fmt(4858.56)
       and rows["Excedente PENDENTE DE CONCILIAÇÃO (fora de receita, repasse e saldo futuro)"] == fch._fmt(1141.44)
       and rows["Saldo histórico após quitação"] == fch._fmt(0.0)
       and rows["(+/-) Prejuízo Acumulado — saldo final a transportar"] == fch._fmt(0.0))
checar("tela: quitação aparece depois do Resultado e antes do Repasse",
       chaves.index("Resultado") < chaves.index("(+) Quitação recebida") < chaves.index("Repasse / Aluguel"))
checar("tela: sem quitação nenhuma linha nova (competência comum idêntica)",
       not any("uitação" in k for k in dict(fch._dre_rows_unit(base_pos))))
checar("tela: sem excedente não mostra a linha de pendência",
       not any("PENDENTE" in k for k in dict(fch._dre_rows_unit(r))))

# PDF: unidade real do seed com layout de COM_ALIQUOTA_CUMUL + 'prejuizo'
from app.reporter import build_report_data, _prestacao_padrao
from app.renderer import render_html, ASSETS_DIR
import app.reporter as reporter
G.congelar_data()
salvar_parametros("dom_pedro", "2026-10", {"tem_quitacao_prejuizo": True}, alterado_por="teste")
engine.load_units(force=True)
cfg_dp = engine.get_unit_com_params("dom_pedro", "2026-10")
rq = engine.calcular("dom_pedro", "2026-10", faturamento=120000.0, saldo_override=-8000.0,
                     custos_extras={"quitacao_prejuizo": 8000.0})
rs = engine.calcular("dom_pedro", "2026-10", faturamento=120000.0, saldo_override=-8000.0)
desc_q = [(l.descricao, l.valor) for l in _prestacao_padrao(rq, cfg_dp).linhas]
desc_s = [(l.descricao, l.valor) for l in _prestacao_padrao(rs, cfg_dp).linhas]
checar("PDF: saldo anterior (-8.000), quitação (+8.000) e saldo final nesta ordem",
       ("(+/-) Prejuízo Acumulado — Saldo Anterior", -8000.0) in desc_q and ("(+) Quitação de Prejuízo Acumulado", 8000.0) in desc_q
       and [d for d, _ in desc_q].index("(+/-) Prejuízo Acumulado — Saldo Anterior")
       < [d for d, _ in desc_q].index("(+) Quitação de Prejuízo Acumulado")
       < [d for d, _ in desc_q].index("(+/-) Prejuízo Acumulado — Saldo Final"))
checar("PDF: Resultado e Receita/Impostos idênticos com e sem quitação",
       [x for x in desc_q if x[0] in ("Resultado", "Receita Bruta", "Receita Líquida") or x[0].startswith("(-)")]
       == [x for x in desc_s if x[0] in ("Resultado", "Receita Bruta", "Receita Líquida") or x[0].startswith("(-)")])
checar("PDF sem quitação: só a linha única '(+/-) Prejuízo Acumulado' (layout atual preservado)",
       ("(+/-) Prejuízo Acumulado", rs.prejuizo_acumulado_saida) in desc_s and not any("Quitação" in d for d, _ in desc_s))
html_q = render_html(build_report_data(rq, "2026-10"))
html_s = render_html(build_report_data(rs, "2026-10"))
checar("HTML do PDF contém as 3 linhas e o valor 8.000,00", "Saldo Anterior" in html_q and "Quitação de Prejuízo Acumulado" in html_q
       and "Saldo Final" in html_q and "8.000,00" in html_q)
checar("HTML do PDF sem quitação não contém a palavra Quitação", "Quitação" not in html_s)
try:
    from weasyprint import HTML as _WP                   # PDF real em diretório temporário (nunca em output/)
    caminho = os.path.join(_SCRATCH, "teste_quitacao.pdf")
    _WP(string=html_q, base_url=ASSETS_DIR).write_pdf(caminho)
    ok_pdf = os.path.exists(caminho) and open(caminho, "rb").read(5) == b"%PDF-"
    checar("PDF real gerado pelo WeasyPrint com as linhas da quitação", ok_pdf)
except Exception as e:                                   # ambiente sem libs nativas
    print(f"[PULADO] geração do PDF binário indisponível neste ambiente: {type(e).__name__}")
print()

print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print("  -", f)
    sys.exit(1)
print("=== TODOS OS TESTES DA QUITAÇÃO DE PREJUÍZO ACUMULADO PASSARAM ===")
