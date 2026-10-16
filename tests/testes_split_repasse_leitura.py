"""
Cobertura permanente da leitura/apresentação de Repasse ao Contratante x
Parcela Fixa x Saldo a Pagar das unidades RESULTADO_SPLIT (Medcenter e Viva Open
Mall) — app/split_repasse.py, app/reporter.py, templates/relatorio.html e a tela
"Competências anteriores".

Contexto: a calculadora grava o SALDO A PAGAR em `aluguel_calculado`; o card, o
comparativo e o histórico anual liam esse campo como "Repasse". Esta correção é
só de leitura/apresentação — nenhum lançamento, saldo, parâmetro ou vigência é
alterado, e nenhum PDF aprovado é reemitido.

Expectativas calculadas de forma INDEPENDENTE do código sob teste (SQL direto
no banco isolado e os valores de contrato conhecidos: Medcenter 75% até
2026-06 e 85% depois, parcela R$ 80.000,00; Viva 85%, parcela R$ 30.000,00 até
2025-02 e R$ 32.533,36 depois).

Roda em banco SQLite isolado (tempfile) a partir do data/seed.db versionado + todas
as migrations. Jun-Ago/2026 são SIMULADOS no banco temporário (mesmo faturamento de
mai/2026) só para exercitar o caminho "com extras" junto do histórico legado.

Execução: python3 tests/testes_split_repasse_leitura.py
"""
import copy, hashlib, json, os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_split_leitura_")
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
from app import split_repasse as sr
from app import run_manager as rm
from app.engine import calcular, load_units
from app.models import ResultadoUnidade, criar_unidade, salvar_lancamento, get_db
from app.paths import RUNS_DIR
from app.renderer import render_html
from app.reporter import build_report_data

VIVA, MED = "viva_open_mall", "medcenter"
PCT_MED = lambda mes: 0.75 if mes <= "2026-06" else 0.85      # contrato (vigências do banco)
PCT = {VIVA: lambda mes: 0.85, MED: PCT_MED}
FAT_VIVA_SET = round((124540.20 + 26626.96) / (1 - 0.1425), 2)   # resultado 124.540,20 (exemplo da operação)
FAT_MED_SET = 560000.00
FAT_SIM = {VIVA: 261227.17, MED: 563101.18}


def brl(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def lanc_json(uid, mes):
    with get_db() as c:
        r = c.execute("SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?", (uid, mes)).fetchone()
    return {"mes": mes, **json.loads(r["resultado_json"])} if r else None


def esperado_repasse(l, uid):
    """Independente do módulo: persistido se houver; senão resultado x percentual do contrato."""
    ex = l.get("extras") or {}
    if ex.get("resultado_contratante") is not None:
        return ex["resultado_contratante"]
    return round(l["resultado"] * PCT[uid](l["mes"]), 2)


def aprovar(uid, mes, fat):
    r = calcular(uid, mes, fat)
    r.status, r.mes_referencia = "aprovado", mes
    salvar_lancamento(r)
    return r


# ── fixture: Jun-Ago simulados + Setembro/2026 (mesmo fluxo da aprovação: persiste) ──
load_units(force=True)
SET = {}
for uid in (VIVA, MED):
    for mes in ("2026-06", "2026-07", "2026-08"):
        aprovar(uid, mes, FAT_SIM[uid])
SET[VIVA] = aprovar(VIVA, "2026-09", FAT_VIVA_SET)
SET[MED] = aprovar(MED, "2026-09", FAT_MED_SET)


def historico_ano(uid, ano, ate):
    """Soma independente das competências do ano até `ate`: (meses, fat, res, repasse, saldo)."""
    with get_db() as c:
        rows = c.execute("SELECT mes_referencia FROM lancamentos WHERE unidade_id=? AND mes_referencia LIKE ? AND mes_referencia<=? "
                         "AND status='aprovado' ORDER BY 1", (uid, f"{ano}-%", ate)).fetchall()
    ls = [lanc_json(uid, r["mes_referencia"]) for r in rows]
    return (len(ls), round(sum(l["faturamento"] for l in ls), 2), round(sum(l["resultado"] for l in ls), 2),
            round(sum(esperado_repasse(l, uid) for l in ls), 2), round(sum(l["aluguel_calculado"] for l in ls), 2))


def linha_ano(rep, ano):
    return next(l for l in rep.historico.linhas if l.ano == ano)


def linha_comp(rep, mes):
    return next((m for m in rep.comparativo_12m if m.competencia == mes), None)


# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1 — Resolvedor de percentual e leitor (unidades)")
print("=" * 70)
rm_med, rm_viva = sr.PercentualContratante(MED), sr.PercentualContratante(VIVA)
checar("1a. Medcenter 2023-07 = 75% (vigência histórica)", rm_med.na_competencia("2023-07") == 0.75)
checar("1b. Medcenter 2026-06 = 75% (último mês antigo)", rm_med.na_competencia("2026-06") == 0.75)
checar("1c. Medcenter 2026-07 = 85% (virada de percentual respeitada)", rm_med.na_competencia("2026-07") == 0.85)
checar("1d. Viva 2023-04 = 85%", rm_viva.na_competencia("2023-04") == 0.85)
checar("1e. Competência sem vigência que a cubra (2019-01) = None, sem reserva no YAML",
       rm_med.na_competencia("2019-01") is None)
checar("1f. Unidade inexistente = None", sr.PercentualContratante("nao_existe").na_competencia("2026-09") is None)

base = {"mes": "2026-09", "resultado": 100000.0, "aluguel_calculado": 40000.0, "faturamento": 200000.0}
v = sr.valores_split({**base, "extras": {"resultado_contratante": 1.23, "parcela_fixa": 4.56, "saldo_a_pagar": 7.89,
                                         "percentual_contratante": 0.5}}, rm_viva)
checar("1g. Com extras: usa os valores PERSISTIDOS, sem recalcular (1,23 / 4,56 / 7,89)",
       (v.repasse, v.parcela, v.saldo, v.percentual, v.origem) == (1.23, 4.56, 7.89, 0.5, sr.ORIGEM_PERSISTIDO))
v = sr.valores_split({**base, "extras": {"resultado_contratante": 85000.0}}, rm_viva)
checar("1h. Extras sem saldo_a_pagar: saldo cai para aluguel_calculado", v.saldo == 40000.0 and v.origem == sr.ORIGEM_PERSISTIDO)
v = sr.valores_split({**base, "extras": {}}, rm_viva)
checar("1i. Sem extras: repasse = round(resultado x pct), saldo = aluguel_calculado, parcela derivada",
       (v.repasse, v.saldo, v.parcela, v.origem) == (85000.0, 40000.0, 45000.0, sr.ORIGEM_RECONSTRUIDO))
v = sr.valores_split({**base, "extras": {"parcela_fixa": 1.0}}, rm_viva)
checar("1j. Extras PARCIAIS (sem resultado_contratante) são tratados como legado, não como persistido",
       v.origem == sr.ORIGEM_RECONSTRUIDO and v.repasse == 85000.0)
v = sr.valores_split({**base, "extras": None}, rm_viva)
checar("1k. extras=None (calculadoras sem extras) não quebra", v.origem == sr.ORIGEM_RECONSTRUIDO)
v = sr.valores_split({**base, "mes": "2019-01"}, rm_med)
checar("1l. Percentual sem vigência: repasse e parcela None ('—'), saldo preservado, origem indisponível",
       (v.repasse, v.parcela, v.saldo, v.origem) == (None, None, 40000.0, sr.ORIGEM_INDISPONIVEL))
v = sr.valores_split({**base, "aluguel_calculado": 0.0}, rm_viva)
checar("1m. Saldo <= 0: repasse válido, parcela NÃO derivada (extração legada usou max(0, valor))",
       v.repasse == 85000.0 and v.parcela is None)
entrada = {**base, "extras": {"x": 1}}
copia = copy.deepcopy(entrada)
sr.valores_split(entrada, rm_viva)
checar("1n. O dicionário do lançamento não é alterado pela leitura", entrada == copia)
checar("1o. rotulo_percentual: 0,85→'85'; 0,825→'82,5'; 0,1425→'14,25'; None→'—'",
       [sr.rotulo_percentual(p) for p in (0.85, 0.825, 0.1425, None)] == ["85", "82,5", "14,25", "—"])

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2 — Histórico real (seed): saldo preservado, exceções conhecidas, mudanças de regime")
print("=" * 70)
with get_db() as c:
    meses_med = [r[0] for r in c.execute("SELECT mes_referencia FROM lancamentos WHERE unidade_id=? AND mes_referencia<='2026-05' ORDER BY 1", (MED,))]
    meses_viva = [r[0] for r in c.execute("SELECT mes_referencia FROM lancamentos WHERE unidade_id=? AND mes_referencia<='2026-05' ORDER BY 1", (VIVA,))]
checar("2a. Seed: 35 lançamentos do Medcenter e 38 do Viva até 2026-05", (len(meses_med), len(meses_viva)) == (35, 38))
ok_saldo = ok_origem = ok_rep = True
for uid, meses in ((MED, meses_med), (VIVA, meses_viva)):
    R = sr.PercentualContratante(uid)
    for mes in meses:
        l = lanc_json(uid, mes)
        v = sr.valores_split(l, R)
        ok_saldo &= v.saldo == l["aluguel_calculado"]
        ok_origem &= v.origem == sr.ORIGEM_RECONSTRUIDO
        ok_rep &= v.repasse == round(l["resultado"] * PCT[uid](mes), 2)
checar("2b. Todos os 73 meses legados: saldo == aluguel_calculado persistido (intocado)", ok_saldo)
checar("2c. Todos os 73 meses legados: origem 'reconstruído'", ok_origem)
checar("2d. Todos os 73 meses legados: repasse = round(resultado x percentual do contrato, 2)", ok_rep)

v = sr.valores_split(lanc_json(MED, "2026-02"), rm_med)
checar("2e. Medcenter 2026-02: saldo ORIGINAL 103.317,43 preservado; nada corrigido", v.saldo == 103317.43)
checar("2f. Medcenter 2026-02: parcela derivada 79.999,92 (diferença de R$ 0,08 visível, não corrigida)",
       v.parcela == 79999.92 and v.repasse == 183317.35)
v = sr.valores_split(lanc_json(VIVA, "2023-04"), rm_viva)
checar("2g. Viva 2023-04: saldo 34.007,92 preservado; parcela atípica 33.870,97 visível", v.saldo == 34007.92 and v.parcela == 33870.97)
checar("2h. Viva até 2025-02: parcela derivada R$ 30.000,00 (±0,01)",
       abs(sr.valores_split(lanc_json(VIVA, "2025-02"), rm_viva).parcela - 30000.0) <= 0.011)
checar("2i. Viva a partir de 2025-03: parcela derivada R$ 32.533,36 (±0,01) — mudança respeitada",
       abs(sr.valores_split(lanc_json(VIVA, "2025-03"), rm_viva).parcela - 32533.36) <= 0.011)
checar("2j. Medcenter: toda a parcela derivada em R$ 80.000,00 (±0,08) nos 35 meses",
       all(abs(sr.valores_split(lanc_json(MED, m), rm_med).parcela - 80000.0) <= 0.081 for m in meses_med))
v = sr.valores_split(lanc_json(MED, "2026-06"), rm_med)
checar("2k. Medcenter 2026-06 (calculado pelo sistema): origem persistido, percentual 75%",
       v.origem == sr.ORIGEM_PERSISTIDO and v.percentual == 0.75)
v = sr.valores_split(lanc_json(MED, "2026-07"), rm_med)
checar("2l. Medcenter 2026-07: origem persistido, percentual 85%", v.origem == sr.ORIGEM_PERSISTIDO and v.percentual == 0.85)

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3 — Setembro/2026: card, comparativo, demonstrativo e histórico anual")
print("=" * 70)
r = SET[VIVA]
checar("3a. Cálculo (inalterado): resultado 124.540,20 / repasse 105.859,17 / parcela 32.533,36 / saldo 73.325,81",
       (r.resultado, r.extras["resultado_contratante"], r.extras["parcela_fixa"], r.extras["saldo_a_pagar"])
       == (124540.20, 105859.17, 32533.36, 73325.81))
checar("3b. aluguel_calculado continua sendo o saldo (73.325,81)", r.aluguel_calculado == 73325.81)
rep = build_report_data(r, "2026-09")
checar("3c. Card principal: rótulo 'Saldo a Pagar', valor 73.325,81 (inalterado)",
       rep.cards.repasse_label == "Saldo a Pagar" and rep.cards.repasse == 73325.81)
checar("3d. Comparativo com as duas colunas: 'Repasse ao Contratante' e saldo",
       rep.comparativo_com_saldo and rep.comparativo_repasse_label == "Repasse ao Contratante")
m = linha_comp(rep, "2026-09")
checar("3e. Comparativo Set/26: repasse 105.859,17 e saldo 73.325,81", (m.repasse, m.saldo_a_pagar) == (105859.17, 73325.81))
m = linha_comp(rep, "2026-05")
checar("3f. Comparativo Mai/26 (legado): repasse 132.609,06 (reconstruído) e saldo 100.075,70 (persistido)",
       (m.repasse, m.saldo_a_pagar) == (132609.06, 100075.70))
m = linha_comp(rep, "2025-03")
checar("3g. Comparativo Mar/25: saldo persistido preservado (54.539,40)", m is None or m.saldo_a_pagar == lanc_json(VIVA, "2025-03")["aluguel_calculado"])
rotulos = [(l.descricao, l.valor) for l in rep.prestacao.linhas]
checar("3h. Demonstrativo: 'Repasse ao Contratante (85%)' = 105.859,17, parcela e 'Saldo a Pagar' mantidos",
       ("Repasse ao Contratante (85%)", 105859.17) in rotulos and ("(-) Parcela Fixa Mensal", -32533.36) in rotulos
       and ("Saldo a Pagar", 73325.81) in rotulos)
checar("3i. Demonstrativo: não restou 'Resultado Contratante'", not any("Resultado Contratante" in d for d, _ in rotulos))
checar("3j. Histórico: colunas Faturamento, Resultado, Repasse ao Contratante, Saldo a Pagar",
       rep.historico.colunas == ["Faturamento", "Resultado", "Repasse ao Contratante", "Saldo a Pagar"])
n, fat, res, repasse, saldo = historico_ano(VIVA, 2026, "2026-09")
la = linha_ano(rep, 2026)
checar("3k. Histórico 2026: '(9 meses)' (jan-mai legado + jun-set)", la.ano_label == "2026 (9 meses)" and n == 9)
checar("3l. Histórico 2026: faturamento e resultado = soma das competências aprovadas",
       (la.valores["Faturamento"], la.valores["Resultado"]) == (fat, res))
checar("3m. Histórico 2026: repasse e saldo acumulados corretos (soma independente)",
       (la.valores["Repasse ao Contratante"], la.valores["Saldo a Pagar"]) == (repasse, saldo))
checar("3n. Histórico 2026: repasse - saldo = soma das parcelas (9 x 32.533,36 ±0,09)",
       abs((repasse - saldo) - 9 * 32533.36) <= 0.09)
for ano in (2023, 2024, 2025):
    n, fat, res, repasse, saldo = historico_ano(VIVA, ano, f"{ano}-12")
    la = linha_ano(rep, ano)
    checar(f"3o. Histórico {ano}: valores = soma independente dos lançamentos",
           (la.valores["Faturamento"], la.valores["Repasse ao Contratante"], la.valores["Saldo a Pagar"]) == (fat, repasse, saldo))
checar("3p. Histórico 2024: rótulo sem sufixo (12 meses)", linha_ano(rep, 2024).ano_label == "2024")

repm = build_report_data(SET[MED], "2026-09")
rotulos_m = [(l.descricao, l.valor) for l in repm.prestacao.linhas]
checar("3q. Medcenter set/26: demonstrativo 'Repasse ao Contratante (85%)'", any(d == "Repasse ao Contratante (85%)" for d, _ in rotulos_m))
m = linha_comp(repm, "2026-06")
checar("3r. Medcenter jun/26: repasse a 75% (persistido), saldo = repasse - 80.000,00",
       m.repasse == round(lanc_json(MED, "2026-06")["resultado"] * 0.75, 2) and round(m.repasse - m.saldo_a_pagar, 2) == 80000.0)
m = linha_comp(repm, "2026-07")
checar("3s. Medcenter jul/26: repasse a 85% — virada de percentual respeitada",
       m.repasse == round(lanc_json(MED, "2026-07")["resultado"] * 0.85, 2))
m = linha_comp(repm, "2026-02")
checar("3t. Medcenter fev/26: saldo ORIGINAL 103.317,43 no comparativo (R$ 0,08 não corrigido)", m.saldo_a_pagar == 103317.43)
n, fat, res, repasse, saldo = historico_ano(MED, 2026, "2026-09")
checar("3u. Medcenter histórico 2026 (9 meses): repasse e saldo = soma independente",
       linha_ano(repm, 2026).valores["Repasse ao Contratante"] == repasse and linha_ano(repm, 2026).valores["Saldo a Pagar"] == saldo)

print("-- PDF de conferência: competência ainda NÃO persistida (gerado antes da aprovação) --")
r_conf = calcular(VIVA, "2026-10", FAT_VIVA_SET)         # não persistido
with get_db() as c:
    antes = c.execute("SELECT COUNT(*) FROM lancamentos WHERE unidade_id=? AND mes_referencia='2026-10'", (VIVA,)).fetchone()[0]
rep_c = build_report_data(r_conf, "2026-10")
mc = linha_comp(rep_c, "2026-10")
checar("3v. Conferência: a competência do próprio PDF aparece no comparativo (memória)",
       mc is not None and mc.repasse == r_conf.extras["resultado_contratante"] and mc.saldo_a_pagar == r_conf.extras["saldo_a_pagar"])
checar("3w. Conferência: histórico 2026 '(10 meses)' somando a competência uma única vez",
       linha_ano(rep_c, 2026).ano_label == "2026 (10 meses)"
       and linha_ano(rep_c, 2026).valores["Saldo a Pagar"] == round(historico_ano(VIVA, 2026, "2026-12")[4] + r_conf.extras["saldo_a_pagar"], 2))
with get_db() as c:
    depois = c.execute("SELECT COUNT(*) FROM lancamentos WHERE unidade_id=? AND mes_referencia='2026-10'", (VIVA,)).fetchone()[0]
checar("3x. Conferência não grava nada em lancamentos", antes == depois == 0)

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4 — Histórico só com competências APROVADAS (+ a do próprio PDF)")
print("=" * 70)


def set_wf(mes, uid, status):
    rm._update_unit(mes, uid, status=status)


def limpar_wf():
    shutil.rmtree(RUNS_DIR, ignore_errors=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def set_lanc(uid, mes, status):
    with get_db() as c:
        c.execute("UPDATE lancamentos SET status=? WHERE unidade_id=? AND mes_referencia=?", (status, uid, mes))


def rel_med(mes="2026-09", r=None):
    return build_report_data(r or SET[MED], mes)


limpar_wf()
base_rep = rel_med()
checar("4a. Referência: jul e ago presentes (aprovados, sem status.json)",
       linha_comp(base_rep, "2026-07") is not None and linha_comp(base_rep, "2026-08") is not None
       and linha_ano(base_rep, 2026).ano_label == "2026 (9 meses)")

set_lanc(MED, "2026-07", "rascunho")
rp = rel_med()
checar("4b. lancamentos.status='rascunho' (em elaboração): jul fora do comparativo e do anual",
       linha_comp(rp, "2026-07") is None and linha_ano(rp, 2026).ano_label == "2026 (8 meses)")
n8, fat8, res8, rep8, sal8 = historico_ano(MED, 2026, "2026-09")
checar("4c. ...e o anual soma só as aprovadas", linha_ano(rp, 2026).valores["Saldo a Pagar"] == sal8)
set_lanc(MED, "2026-07", "aprovado")

set_wf("2026-08", MED, "reaberto")
rp = rel_med()
checar("4d. Workflow 'reaberto': ago fora do comparativo e do anual", linha_comp(rp, "2026-08") is None
       and linha_ano(rp, 2026).ano_label == "2026 (8 meses)")
set_wf("2026-08", MED, "gerado")
checar("4e. Workflow 'gerado' (em elaboração): ago também fora", linha_comp(rel_med(), "2026-08") is None)
set_wf("2026-08", MED, "erro")
checar("4f. Workflow 'erro': ago também fora", linha_comp(rel_med(), "2026-08") is None)
set_wf("2026-08", MED, "aprovado")
checar("4g. Workflow 'aprovado' + lançamento aprovado: ago volta", linha_comp(rel_med(), "2026-08") is not None)
limpar_wf()
checar("4h. Sem status.json (histórico legado/restaurado): vale pelo lançamento aprovado",
       linha_comp(rel_med(), "2026-08") is not None and linha_comp(rel_med(), "2026-02") is not None)
(RUNS_DIR / "2026-08").mkdir(parents=True, exist_ok=True)
(RUNS_DIR / "2026-08" / "status.json").write_text("{ ilegível", encoding="utf-8")
checar("4i. status.json ilegível: sem informação de workflow — vale pelo lançamento (não quebra)",
       linha_comp(rel_med(), "2026-08") is not None)
limpar_wf()
set_wf("2026-07", VIVA, "reaberto")
checar("4j. O workflow é por unidade: Medcenter jul não é afetado pelo Viva reaberto", linha_comp(rel_med(), "2026-07") is not None)
limpar_wf()

# a competência do PRÓPRIO PDF entra sempre, mesmo reaberta / lançamento não aprovado
set_lanc(MED, "2026-09", "rascunho")
set_wf("2026-09", MED, "reaberto")
rp = rel_med()
checar("4k. Competência do próprio PDF (lançamento rascunho + workflow reaberto): SEMPRE incluída (PDF de conferência)",
       linha_comp(rp, "2026-09") is not None and linha_ano(rp, 2026).ano_label == "2026 (9 meses)")
set_lanc(MED, "2026-09", "aprovado")
limpar_wf()

# PDF de uma competência anterior: histórico só até ela
rp = build_report_data(calcular(MED, "2026-07", FAT_SIM[MED]), "2026-07")
checar("4l. PDF de jul/2026: histórico anual só até jul ('2026 (7 meses)'), sem ago/set",
       linha_ano(rp, 2026).ano_label == "2026 (7 meses)" and linha_comp(rp, "2026-08") is None and linha_comp(rp, "2026-09") is None)

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5 — O cache historico_anual NÃO é lido nem alterado")
print("=" * 70)
with get_db() as c:
    c.execute("UPDATE historico_anual SET dados_json=? WHERE unidade_id IN (?,?)",
              (json.dumps({"faturamento": 1.0, "resultado": 2.0, "aluguel_calculado": 3.0, "quantidade_meses": 1}), MED, VIVA))
    cache_antes = [tuple(x) for x in c.execute("SELECT * FROM historico_anual ORDER BY 1")]
rp = rel_med()
n, fat, res, repasse, saldo = historico_ano(MED, 2026, "2026-09")
checar("5a. Com o cache adulterado (valores 1/2/3), o histórico anual segue igual à soma de lancamentos",
       linha_ano(rp, 2026).valores["Faturamento"] == fat and linha_ano(rp, 2026).valores["Saldo a Pagar"] == saldo)
with get_db() as c:
    cache_depois = [tuple(x) for x in c.execute("SELECT * FROM historico_anual ORDER BY 1")]
checar("5b. A tabela historico_anual não foi alterada pela geração do relatório", cache_antes == cache_depois)

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("6 — Percentual indisponível: '—' (sem reserva no YAML) e saldo preservado")
print("=" * 70)
UID_SEM = "split_sem_percentual"
criar_unidade(UID_SEM, "Split Sem Percentual", "Contratante X", "2020-01-01", "RESULTADO_SPLIT")
load_units(force=True)
for mes in ("2026-07", "2026-08"):
    leg = ResultadoUnidade(unidade_id=UID_SEM, mes_referencia=mes, faturamento=100000.0, resultado=50000.0,
                           aluguel_calculado=20000.0, extras={}, status="aprovado")
    salvar_lancamento(leg)
atual = ResultadoUnidade(unidade_id=UID_SEM, mes_referencia="2026-09", faturamento=110000.0, resultado=55000.0,
                         aluguel_calculado=22000.0, extras={}, status="aprovado")
rs = build_report_data(atual, "2026-09")
checar("6a. Comparativo: repasse None ('—') e saldo preservado em todas as linhas",
       all(m.repasse is None for m in rs.comparativo_12m) and [m.saldo_a_pagar for m in rs.comparativo_12m] == [22000.0, 20000.0, 20000.0])
la = linha_ano(rs, 2026)
checar("6b. Histórico anual: repasse '—' (nunca soma parcial); saldo somado (62.000,00)",
       la.valores["Repasse ao Contratante"] is None and la.valores["Saldo a Pagar"] == 62000.0)
html_s = render_html(rs)
checar("6c. HTML mostra '—' no repasse e o saldo", "—" in html_s and "22.000,00" in html_s)

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("7 — HTML do PDF (Viva e Medcenter) e ausência de efeito nas demais calculadoras")
print("=" * 70)
html = render_html(rep)
checar("7a. Card: 'Saldo a Pagar' e nenhum 'Valor do Repasse'", "Saldo a Pagar</div>" in html and "Valor do Repasse" not in html)
checar("7b. Comparativo: <th>Repasse ao Contratante</th> e <th>Saldo a Pagar</th>",
       html.count("<th>Repasse ao Contratante</th>") == 2 and html.count("<th>Saldo a Pagar</th>") == 2)   # comparativo + histórico
checar("7c. 7 colunas no cabeçalho do comparativo",
       html.split('class="table-comp"')[1].split("</thead>")[0].count("<th>") == 7)
checar("7d. Histórico: 5 colunas (Ano + 4 indicadores)", html.split('class="table-hist"')[1].split("</thead>")[0].count("<th>") == 5)
checar("7e. Demonstrativo: 'Repasse ao Contratante (85%)'", "Repasse ao Contratante (85%)" in html)
vasco = render_html(build_report_data(rm.load_resultado_from_db("2026-05", "vasco"), "2026-05"))
checar("7f. Outra calculadora (Vasco): continua 'Valor do Repasse', coluna 'Repasse' e sem 'Saldo a Pagar'",
       "Valor do Repasse" in vasco and "<th>Repasse</th>" in vasco and "Saldo a Pagar" not in vasco
       and vasco.split('class="table-comp"')[1].split("</thead>")[0].count("<th>") == 6)

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("8 — Tela 'Competências anteriores'")
print("=" * 70)
_PROBES = []
atexit.register(lambda: [os.remove(p) for p in _PROBES if os.path.exists(p)])


def abrir_unidade(uid, mes_ref="2026-09"):
    path = os.path.join(_REPO_ROOT, "tests", f"_probe_split_{len(_PROBES)}.py")
    with open(path, "w") as f:
        f.write(f'''
import os
os.environ["DATA_DIR"] = {_SCRATCH!r}
import sys
sys.path.insert(0, {_REPO_ROOT!r})
import streamlit as st
st.session_state.selected_unit = {uid!r}
from app.ui.fechamento import tela_fechamento
tela_fechamento({mes_ref!r})
''')
    _PROBES.append(path)
    at = AppTest.from_file(path, default_timeout=90)
    at.run()
    return at


import app.ui.fechamento as fech


def df_historico(at):
    """A tabela de 'Competências anteriores' (índice 'Indicador'), não a memória de cálculo atual."""
    return next(d.value for d in at.dataframe if d.value.index.name == "Indicador")


for uid in (MED, VIVA):
    at = abrir_unidade(uid)
    df = df_historico(at)
    idx = list(df.index)
    checar(f"8a. {uid}: sem exceção e com as linhas Repasse ao Contratante / (-) Parcela Fixa / Saldo a Pagar / Origem",
           len(at.exception) == 0 and all(x in idx for x in ("Repasse ao Contratante", "(-) Parcela Fixa", "Saldo a Pagar", "Origem do repasse")))
    checar(f"8b. {uid}: a linha 'Aluguel/Repasse' (que mostrava o saldo) não existe mais", "Aluguel/Repasse" not in idx)
    col_set, col_mai = fech._mes_label("2026-09"), fech._mes_label("2026-05")
    checar(f"8c. {uid}: Set/26 'persistido' e Mai/26 'reconstruído'",
           df.loc["Origem do repasse", col_set] == "persistido" and df.loc["Origem do repasse", col_mai] == "reconstruído")
    esp_saldo = lanc_json(uid, "2026-05")["aluguel_calculado"]
    checar(f"8d. {uid}: Saldo a Pagar de Mai/26 = saldo persistido ({brl(esp_saldo)})",
           df.loc["Saldo a Pagar", col_mai] == f"R$ {brl(esp_saldo)}")
    esp_rep = esperado_repasse(lanc_json(uid, "2026-05"), uid)
    checar(f"8e. {uid}: Repasse ao Contratante de Mai/26 reconstruído ({brl(esp_rep)})",
           df.loc["Repasse ao Contratante", col_mai] == f"R$ {brl(esp_rep)}")
    checar(f"8f. {uid}: parcela fixa exibida como dedução",
           df.loc["(-) Parcela Fixa", col_set].startswith("(R$ "))
at = abrir_unidade("vasco", "2026-05")
idx = list(df_historico(at).index)
checar("8g. Outra unidade (Vasco): continua 'Aluguel/Repasse', sem as linhas novas",
       "Aluguel/Repasse" in idx and "Repasse ao Contratante" not in idx and "Origem do repasse" not in idx)

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("9 — Somente leitura: nada é alterado, nenhum PDF é reemitido")
print("=" * 70)


def snapshot():
    snap = {}
    with get_db() as c:
        for tabela, filtro in (("lancamentos", ""), ("saldos_acumulados", ""), ("historico_anual", ""),
                               ("parametros_vigentes", f"WHERE unidade_id IN ('{MED}','{VIVA}')")):
            snap[tabela] = hashlib.sha256(json.dumps([tuple(x) for x in c.execute(f"SELECT * FROM {tabela} {filtro} ORDER BY 1,2")],
                                                      default=str).encode()).hexdigest()
    arquivos = {}
    for raiz, _, nomes in os.walk(RUNS_DIR):
        for n in nomes:
            p = os.path.join(raiz, n)
            arquivos[os.path.relpath(p, RUNS_DIR)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    snap["runs"] = arquivos
    return snap


# um PDF aprovado "pré-existente" que não pode ser tocado
(RUNS_DIR / "2026-08" / "reports").mkdir(parents=True, exist_ok=True)
(RUNS_DIR / "2026-08" / "reports" / "medcenter.pdf").write_bytes(b"%PDF-1.4 aprovado anterior")
set_wf("2026-08", MED, "aprovado")
S0 = snapshot()
for uid in (MED, VIVA):
    for mes in ("2026-09", "2026-05", "2023-07"):
        rr = SET.get(uid) if mes == "2026-09" else calcular(uid, mes, 300000.0)
        render_html(build_report_data(rr, mes))
abrir_unidade(MED)
abrir_unidade(VIVA)
S1 = snapshot()
checar("9a. lancamentos, saldos_acumulados, historico_anual e parametros_vigentes (Medcenter/Viva) idênticos",
       all(S0[t] == S1[t] for t in ("lancamentos", "saldos_acumulados", "historico_anual", "parametros_vigentes")))
checar("9b. runs/ (status.json e PDFs) idêntico — nenhum PDF aprovado reemitido nem criado", S0["runs"] == S1["runs"])
checar("9c. O PDF aprovado pré-existente continua byte a byte igual",
       (RUNS_DIR / "2026-08" / "reports" / "medcenter.pdf").read_bytes() == b"%PDF-1.4 aprovado anterior")

# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("10 — Reabrir / regerar PDF (run_manager REAL) e a competência do próprio PDF contada uma única vez")
print("=" * 70)
limpar_wf()
AGO = "2026-08"


def aprovar_workflow(mes, uid=MED):
    """Fluxo real de aprovação: gera o PDF e marca o workflow aprovado."""
    rm.generate_report(mes, uid, rm.load_resultado_from_db(mes, uid))
    rm.mark_approved(mes, uid)


def hist_set():
    rp = rel_med()
    return sorted(m.competencia for m in rp.comparativo_12m if m.competencia >= "2026-06"), linha_ano(rp, 2026).ano_label


TODOS = ["2026-06", "2026-07", "2026-08", "2026-09"]
for mes in ("2026-06", "2026-07", AGO):
    aprovar_workflow(mes)
checar("10a. Tudo aprovado pelo fluxo real: jun-set no comparativo e '2026 (9 meses)'", hist_set() == (TODOS, "2026 (9 meses)"))

# "Gerar PDF" numa competência JÁ aprovada: o run_manager devolve o status a 'gerado'
rm.generate_report(AGO, MED, rm.load_resultado_from_db(AGO, MED))
u = rm.get_unit_run(AGO, MED)
checar("10b. (pré-condição) 'Gerar PDF' numa aprovada deixa o workflow em 'gerado', com aprovação registrada e sem reabertura",
       u["status"] == "gerado" and u["last_approved_at"] and not u["reopened_at"])
checar("10c. ...e a competência CONTINUA nos históricos seguintes (nada voltou a ser elaborado): 9 meses", hist_set() == (TODOS, "2026 (9 meses)"))

rm.mark_error(AGO, MED, "falha ao regerar")
checar("10d. Regeração que falhou ('erro') numa competência aprovada e nunca reaberta: continua incluída", hist_set() == (TODOS, "2026 (9 meses)"))

rm.generate_report(AGO, MED, rm.load_resultado_from_db(AGO, MED))
rm.mark_approved(AGO, MED)
rm.reopen(AGO, MED)
checar("10e. Reaberta: sai dos históricos seguintes (8 meses)", hist_set() == (["2026-06", "2026-07", "2026-09"], "2026 (8 meses)"))
rm.generate_report(AGO, MED, rm.load_resultado_from_db(AGO, MED))
checar("10f. Reaberta + 'Gerar PDF' (gerado, aprovação ANTERIOR à reabertura): continua de fora",
       rm.get_unit_run(AGO, MED)["status"] == "gerado" and hist_set()[1] == "2026 (8 meses)")
rm.mark_error(AGO, MED, "falha")
checar("10g. Reaberta + erro: continua de fora", hist_set()[1] == "2026 (8 meses)")
rm.generate_report(AGO, MED, rm.load_resultado_from_db(AGO, MED))
rm.mark_approved(AGO, MED)
checar("10h. Reaprovada: volta aos históricos (9 meses)", hist_set() == (TODOS, "2026 (9 meses)"))

# precedência cronológica de last_approved_at x reopened_at (timestamps explícitos, sem depender do relógio)
rm._update_unit(AGO, MED, status="gerado", last_approved_at="2026-09-01T10:00:00", reopened_at="2026-09-02T10:00:00")
checar("10i. gerado: aprovação (01/09) ANTERIOR à reabertura (02/09) → fora", hist_set()[1] == "2026 (8 meses)")
rm._update_unit(AGO, MED, status="gerado", last_approved_at="2026-09-03T10:00:00", reopened_at="2026-09-02T10:00:00")
checar("10j. gerado: reaprovada (03/09) DEPOIS da reabertura (02/09) e regerada → dentro", hist_set()[1] == "2026 (9 meses)")
rm._update_unit(AGO, MED, status="gerado", last_approved_at=None, reopened_at=None)
checar("10k. gerado e NUNCA aprovado pelo workflow → fora", hist_set()[1] == "2026 (8 meses)")
rm._update_unit(AGO, MED, status="pendente", last_approved_at="2026-09-01T10:00:00", reopened_at=None)
checar("10l. 'pendente' → fora", hist_set()[1] == "2026 (8 meses)")
rm._update_unit(AGO, MED, status="aprovado", last_approved_at="2026-09-03T10:00:00", reopened_at="2026-09-05T10:00:00")
checar("10m. 'aprovado' sempre entra (mesmo com reopened_at antigo no registro)", hist_set()[1] == "2026 (9 meses)")

# ── a competência do PRÓPRIO PDF entra uma única vez ──────────────────────
print("-- competência do próprio PDF: uma única vez nos totais anuais --")
limpar_wf()
n0, fat0, res0, rep0, sal0 = historico_ano(MED, 2026, "2026-09")
fat_set_banco = lanc_json(MED, "2026-09")["faturamento"]
novo = calcular(MED, "2026-09", FAT_MED_SET + 25000.0)        # recalculada com OUTRO faturamento; ainda NÃO reaprovada
rp = build_report_data(novo, "2026-09")
la = linha_ano(rp, 2026)
checar("10n. Banco já tem set/26 (valor antigo) e o PDF traz o recálculo: a competência conta UMA vez ('2026 (9 meses)', não 10)",
       la.ano_label == "2026 (9 meses)")
checar("10o. O total anual usa o valor da MEMÓRIA, não o antigo do banco (faturamento = demais meses + novo)",
       la.valores["Faturamento"] == round(fat0 - fat_set_banco + novo.faturamento, 2))
checar("10p. O saldo anual idem (demais meses + saldo recalculado)",
       la.valores["Saldo a Pagar"] == round(sal0 - SET[MED].aluguel_calculado + novo.aluguel_calculado, 2))
checar("10q. O comparativo tem exatamente UMA linha de set/26, com os valores do recálculo",
       [m.competencia for m in rp.comparativo_12m].count("2026-09") == 1
       and linha_comp(rp, "2026-09").saldo_a_pagar == novo.extras["saldo_a_pagar"])
rp2 = build_report_data(SET[MED], "2026-09")
checar("10r. Sem recálculo (memória == banco): continua '2026 (9 meses)' e o mesmo total do banco",
       linha_ano(rp2, 2026).ano_label == "2026 (9 meses)" and linha_ano(rp2, 2026).valores["Faturamento"] == fat0)
set_wf("2026-09", MED, "reaberto")
rp3 = build_report_data(novo, "2026-09")
checar("10s. Competência do PDF reaberta (workflow) e com lançamento antigo no banco: ainda UMA vez, valor da memória",
       linha_ano(rp3, 2026).ano_label == "2026 (9 meses)" and linha_ano(rp3, 2026).valores["Faturamento"] == round(fat0 - fat_set_banco + novo.faturamento, 2))
limpar_wf()

print()
if _falhas:
    print(f"{len(_falhas)} FALHA(S):")
    for n in _falhas:
        print("  -", n)
    sys.exit(1)
print("Todas as verificações passaram.")
