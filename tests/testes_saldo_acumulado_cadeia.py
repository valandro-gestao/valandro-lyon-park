"""
Cobertura permanente da cadeia temporal de saldo acumulado (v1.2.0 —
substitui saldos_acumulados como fonte de entrada do cálculo para
COM_ALIQUOTA_CUMUL e PATIO_MANUTENCAO).

Causa raiz resolvida: saldos_acumulados é um valor único e corrente por
unidade, sem competência — reprocessar um mês passado depois que meses
mais recentes já foram aprovados lia o saldo do mês MAIS RECENTE, não o
que realmente precedia a competência sendo recalculada (bug real de
produção). A cadeia nova (app.models.get_saldo_entrada) resolve a
entrada de uma competência pela saída congelada do último lançamento
aprovado ESTRITAMENTE ANTERIOR a ela, dentro da janela confiável
(>= CADEIA_SALDO_DESDE = "2026-06" — antes disso é bootstrap histórico
com entrada/saída zeradas artificialmente, migration 0002), com
fallback a uma âncora explícita por unidade (parâmetro
"saldo_acumulado_inicial", vigência via a infraestrutura já existente
de parametros_vigentes) e por fim a 0.0.

Escopo desta etapa: só a cadeia de saldo acumulado (get_saldo_entrada +
os dois calculators que a usam) e a proteção de saldos_acumulados contra
retrocesso. Não cobre Axis, Pátio Operação, Medcenter ou histórico —
etapas separadas.

Execução: python3 tests/testes_saldo_acumulado_cadeia.py
"""
import os, sys, tempfile, shutil, atexit, json

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_saldo_cadeia_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import engine
from app.models import (
    init_db, criar_unidade, unidade_id_existe, salvar_parametros,
    salvar_lancamento, get_saldo_entrada, get_saldo_acumulado, get_db,
    CADEIA_SALDO_DESDE,
)

init_db()
_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


def cria_unidade(uid, tipo="COM_ALIQUOTA_CUMUL"):
    if not unidade_id_existe(uid):
        criar_unidade(id=uid, nome=uid, contratante="Teste", inicio="2020-01-01", tipo_calculo=tipo)
        engine.load_units(force=True)


def aprova(uid, mes, faturamento, saldo_override=None):
    r = engine.calcular(uid, mes, faturamento=faturamento, saldo_override=saldo_override)
    r.status = "aprovado"
    salvar_lancamento(r)
    return r


def bootstrap_legado(uid, mes, resultado, aluguel):
    """Insere um lançamento no formato exato da migration 0002: aprovado,
    mas com prejuizo_acumulado_entrada/saida zerados artificialmente."""
    d = {
        "unidade_id": uid, "mes_referencia": mes, "faturamento": 0.0,
        "aliquota_imposto": 0.0, "subtotal": 0.0, "ponto_equilibrio": 0.0,
        "custos": {}, "resultado": resultado,
        "prejuizo_acumulado_entrada": 0.0, "prejuizo_acumulado_saida": 0.0,
        "aluguel_calculado": aluguel, "splits": {}, "extras": {},
        "observacoes": "Restaurado do histórico anterior ao Lyon Reports (migration 0002).",
        "status": "aprovado",
    }
    with get_db() as conn:
        conn.execute(
            "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
            "VALUES (?, ?, 0.0, ?, 'aprovado')",
            (uid, mes, json.dumps(d, ensure_ascii=False)),
        )


# ═══════════════════════════════════════════════════════════════════════
# 1/2/3 — junho sem anterior usa âncora; julho usa saída de junho;
#          agosto usa saída de julho
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1-3. Junho (âncora) -> Julho (saída de junho) -> Agosto (saída de julho)")
print("=" * 70)
uid1 = "cadeia_dom_pedro_like"
cria_unidade(uid1)
salvar_parametros(uid1, "2020-01", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "percentual_aluguel": 0.8,
}, alterado_por="teste")
salvar_parametros(uid1, CADEIA_SALDO_DESDE, {"saldo_acumulado_inicial": -1000.0}, alterado_por="teste")

checar("junho (sem lançamento anterior) usa a âncora (-1000.0)",
       get_saldo_entrada(uid1, "2026-06") == -1000.0)

r_jun = aprova(uid1, "2026-06", faturamento=0.0)
checar("junho calculado usa -1000.0 como entrada", r_jun.prejuizo_acumulado_entrada == -1000.0)
checar("julho usa a SAÍDA de junho, não a âncora de novo",
       get_saldo_entrada(uid1, "2026-07") == r_jun.prejuizo_acumulado_saida)

r_jul = aprova(uid1, "2026-07", faturamento=200.0)
checar("agosto usa a SAÍDA de julho",
       get_saldo_entrada(uid1, "2026-08") == r_jul.prejuizo_acumulado_saida)
print()


# ═══════════════════════════════════════════════════════════════════════
# 4 — reprocessar julho depois de agosto continua usando a saída de
#     junho, nunca a de agosto (o bug original)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Reprocessar julho depois de agosto -> continua usando saída de junho")
print("=" * 70)
r_ago = aprova(uid1, "2026-08", faturamento=5000.0)
checar("agosto fechou com saída bem diferente da entrada de julho",
       r_ago.prejuizo_acumulado_saida != r_jun.prejuizo_acumulado_saida)

entrada_julho_reprocessado = get_saldo_entrada(uid1, "2026-07")
checar("julho REPROCESSADO (mesmo depois de agosto existir) ainda usa a saída de junho",
       entrada_julho_reprocessado == r_jun.prejuizo_acumulado_saida)
checar("...e definitivamente NÃO usa a saída de agosto",
       entrada_julho_reprocessado != r_ago.prejuizo_acumulado_saida)
print()


# ═══════════════════════════════════════════════════════════════════════
# 5 — mês faltante usa o último lançamento anterior válido (não precisa
#     ser o mês calendário imediatamente anterior)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5. Mês faltante -> usa o último lançamento anterior válido")
print("=" * 70)
uid5 = "cadeia_mes_faltante"
cria_unidade(uid5)
salvar_parametros(uid5, "2020-01", {"aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "percentual_aluguel": 0.8}, alterado_por="teste")
salvar_parametros(uid5, CADEIA_SALDO_DESDE, {"saldo_acumulado_inicial": -500.0}, alterado_por="teste")
r5_jun = aprova(uid5, "2026-06", faturamento=100.0)
# 2026-07 nunca é calculado/aprovado -- pula direto para agosto
checar("agosto usa a saída de junho quando julho nunca existiu",
       get_saldo_entrada(uid5, "2026-08") == r5_jun.prejuizo_acumulado_saida)
print()


# ═══════════════════════════════════════════════════════════════════════
# 6 — histórico bootstrapado (< CADEIA_SALDO_DESDE) com saída=0 é
#     ignorado pela cadeia, mesmo sendo o lançamento aprovado mais
#     recente antes da competência pedida
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("6. Histórico bootstrapado (saída=0 artificial) é ignorado pela cadeia")
print("=" * 70)
uid6 = "cadeia_bootstrap_ignorado"
cria_unidade(uid6)
for mes, resultado in [("2026-01", -20000.0), ("2026-02", -18000.0), ("2026-03", -16000.0),
                        ("2026-04", -14000.0), ("2026-05", -12000.0)]:
    bootstrap_legado(uid6, mes, resultado, 0.0)
salvar_parametros(uid6, CADEIA_SALDO_DESDE, {"saldo_acumulado_inicial": -662556.13}, alterado_por="teste")

entrada_junho = get_saldo_entrada(uid6, "2026-06")
checar("junho usa a ÂNCORA (-662556.13), não o 0.0 congelado de maio (bootstrap)",
       entrada_junho == -662556.13)
with get_db() as _conn:
    _row_maio = _conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia='2026-05'",
        (uid6,)
    ).fetchone()
checar("maio (bootstrap) realmente tem saída=0.0 artificial, para não sobrar dúvida",
       json.loads(_row_maio["resultado_json"])["prejuizo_acumulado_saida"] == 0.0)
print()


# ═══════════════════════════════════════════════════════════════════════
# 7 — unidade sem âncora e sem lançamento anterior -> 0.0
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("7. Unidade sem âncora e sem lançamento anterior -> 0.0")
print("=" * 70)
uid7 = "cadeia_sem_ancora"
cria_unidade(uid7)
checar("sem âncora configurada e sem lançamento anterior, entrada = 0.0",
       get_saldo_entrada(uid7, "2026-06") == 0.0)
print()


# ═══════════════════════════════════════════════════════════════════════
# 8 — saldo_override vence tudo (âncora e cadeia)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("8. saldo_override vence âncora e cadeia")
print("=" * 70)
uid8 = "cadeia_override_vence"
cria_unidade(uid8)
salvar_parametros(uid8, "2020-01", {"aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "percentual_aluguel": 0.8}, alterado_por="teste")
salvar_parametros(uid8, CADEIA_SALDO_DESDE, {"saldo_acumulado_inicial": -999.0}, alterado_por="teste")
r8 = engine.calcular(uid8, "2026-06", faturamento=100.0, saldo_override=-1.0)
checar("saldo_override (-1.0) prevaleceu sobre a âncora (-999.0)",
       r8.prejuizo_acumulado_entrada == -1.0)
print()


# ═══════════════════════════════════════════════════════════════════════
# 9 — Dom Pedro-like, âncora negativa (dívida)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("9. Dom Pedro-like: âncora negativa bloqueia repasse até compensar")
print("=" * 70)
uid9 = "cadeia_dom_pedro_negativa"
cria_unidade(uid9)
salvar_parametros(uid9, "2020-01", {"aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "percentual_aluguel": 0.8}, alterado_por="teste")
salvar_parametros(uid9, CADEIA_SALDO_DESDE, {"saldo_acumulado_inicial": -171239.32}, alterado_por="teste")
r9 = engine.calcular(uid9, "2026-06", faturamento=5000.0)
checar("entrada = âncora oficial de Dom Pedro (-171239.32)", r9.prejuizo_acumulado_entrada == -171239.32)
checar("aluguel = 0 (prejuízo não compensado por R$5.000 de faturamento)", r9.aluguel_calculado == 0.0)
checar("saída ficou mais próxima de zero, mas ainda negativa", -171239.32 < r9.prejuizo_acumulado_saida < 0)
print()


# ═══════════════════════════════════════════════════════════════════════
# 10 — Pátio Manutenções-like, âncora POSITIVA (memorando, nunca bloqueia
#      cobrança — PATIO_MANUTENCAO sempre cobra o resultado do mês)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("10. Pátio Manutenções-like: âncora positiva, nunca bloqueia cobrança")
print("=" * 70)
uid10 = "cadeia_patio_manutencao_positiva"
cria_unidade(uid10, tipo="PATIO_MANUTENCAO")
salvar_parametros(uid10, "2020-01", {"retencao_iss": 0.05}, alterado_por="teste")
salvar_parametros(uid10, CADEIA_SALDO_DESDE, {"saldo_acumulado_inicial": 42223.85}, alterado_por="teste")

checar("entrada de junho = âncora oficial (42223.85)", get_saldo_entrada(uid10, "2026-06") == 42223.85)
r10 = engine.calcular(uid10, "2026-06", faturamento=1000.0)
checar("PATIO_MANUTENCAO cobra o resultado do mês mesmo com saldo positivo (nunca bloqueia)",
       r10.aluguel_calculado == r10.resultado)
checar("saldo acumulado (memorando) = âncora + resultado do mês",
       r10.prejuizo_acumulado_saida == round(42223.85 + r10.resultado, 2))
print()


# ═══════════════════════════════════════════════════════════════════════
# 11 — aprovação/reaprovação fora de ordem não contamina a entrada dos
#      demais meses (prova mais ampla, com 3 unidades e uma reaprovação
#      de um mês ANTIGO depois de vários mais novos já existirem)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("11. Reaprovação fora de ordem não contamina os demais meses")
print("=" * 70)
uid11 = "cadeia_fora_de_ordem"
cria_unidade(uid11)
salvar_parametros(uid11, "2020-01", {"aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "percentual_aluguel": 0.8}, alterado_por="teste")
salvar_parametros(uid11, CADEIA_SALDO_DESDE, {"saldo_acumulado_inicial": -300.0}, alterado_por="teste")

aprova(uid11, "2026-06", faturamento=0.0)     # entrada -300, resultado 0 -> saída -300
r_jul_1a = aprova(uid11, "2026-07", faturamento=100.0)   # entrada -300 -> saída -200
r_ago_1a = aprova(uid11, "2026-08", faturamento=100.0)   # entrada -200 -> saída -100
r_set_1a = aprova(uid11, "2026-09", faturamento=100.0)   # entrada -100 -> saída 0 (ou perto)

# Reabre e reaprova JULHO com um faturamento diferente (fora de ordem —
# setembro já existe e já foi aprovado).
r_jul_2a = aprova(uid11, "2026-07", faturamento=250.0)
checar("julho reaprovado ainda usa a saída de JUNHO como entrada (-300.0), não a de agosto/setembro",
       r_jul_2a.prejuizo_acumulado_entrada == -300.0)

checar("agosto (nunca recalculado) continua exatamente como estava",
       get_saldo_entrada(uid11, "2026-09") == r_ago_1a.prejuizo_acumulado_saida)
print("  nota: agosto e setembro ficam com uma entrada 'desatualizada' em relação ao julho novo —")
print("  esperado nesta etapa (reprocessamento em cascata é decisão operacional futura,")
print("  não algo que a cadeia deva fazer sozinha e silenciosamente).")
print()


# ═══════════════════════════════════════════════════════════════════════
# EXTRA — prova direta de que o cálculo não lê mais saldos_acumulados
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("EXTRA. saldos_acumulados com valor errado não afeta o cálculo")
print("=" * 70)
uid_extra = "cadeia_ignora_tabela_antiga"
cria_unidade(uid_extra)
salvar_parametros(uid_extra, "2020-01", {"aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "percentual_aluguel": 0.8}, alterado_por="teste")
salvar_parametros(uid_extra, CADEIA_SALDO_DESDE, {"saldo_acumulado_inicial": -50.0}, alterado_por="teste")
with get_db() as conn:
    conn.execute(
        "INSERT INTO saldos_acumulados (unidade_id, prejuizo_acumulado) VALUES (?, ?) "
        "ON CONFLICT(unidade_id) DO UPDATE SET prejuizo_acumulado=excluded.prejuizo_acumulado",
        (uid_extra, -999999.99),
    )
checar("saldos_acumulados (tabela antiga) tem um valor absurdo, de propósito",
       get_saldo_acumulado(uid_extra) == -999999.99)
r_extra = engine.calcular(uid_extra, "2026-06", faturamento=100.0)
checar("o CÁLCULO ignora completamente saldos_acumulados e usa a âncora real (-50.0)",
       r_extra.prejuizo_acumulado_entrada == -50.0)
print()


# ═══════════════════════════════════════════════════════════════════════
# EXTRA — saldos_acumulados não retrocede quando um mês antigo é reaprovado
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("EXTRA. saldos_acumulados (compatibilidade) não retrocede em reprocessamento fora de ordem")
print("=" * 70)
uid_comp = "cadeia_compat_nao_retrocede"
cria_unidade(uid_comp)
salvar_parametros(uid_comp, "2020-01", {"aliquota_imposto": 0.0, "ponto_equilibrio": 0.0, "percentual_aluguel": 0.8}, alterado_por="teste")
salvar_parametros(uid_comp, CADEIA_SALDO_DESDE, {"saldo_acumulado_inicial": -300.0}, alterado_por="teste")
aprova(uid_comp, "2026-06", faturamento=0.0)
aprova(uid_comp, "2026-07", faturamento=100.0)
r_ago_comp = aprova(uid_comp, "2026-08", faturamento=100.0)
valor_apos_agosto = get_saldo_acumulado(uid_comp)
checar("saldos_acumulados reflete a saída de agosto (o mais recente aprovado)",
       valor_apos_agosto == r_ago_comp.prejuizo_acumulado_saida)

# Reabre e reaprova JUNHO (mais antigo que agosto) com um valor diferente
aprova(uid_comp, "2026-06", faturamento=999.0)
valor_apos_reaprovar_junho = get_saldo_acumulado(uid_comp)
checar("saldos_acumulados NÃO retrocedeu para o valor de junho — continua com o de agosto",
       valor_apos_reaprovar_junho == valor_apos_agosto)
print()


print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DA CADEIA DE SALDO ACUMULADO PASSARAM ===")
