"""
Cobertura permanente da correção do motor de vigências em
app.models.salvar_parametros (incidente de produção — Medcenter,
2026-07→2026-05 depois de aprovar 2026-06).

Causa raiz corrigida: a busca pela vigência a fechar/atualizar usava "a
mais recente aberta" (sem checar se seu início é <= mes_ref), então uma
vigência FUTURA já cadastrada era encontrada e corrompida ao salvar uma
competência anterior a ela. A correção busca a vigência que efetivamente
COBRE mes_ref, e limita qualquer vigência nova ao mês anterior à próxima
já cadastrada (quando houver) — nunca deixa uma vigência nova "vencer"
uma futura por ficar aberta indevidamente.

Escopo desta etapa: só o motor de vigências (salvar_parametros). Não
cobre saldos acumulados, Axis, Pátio ou histórico — isso fica para
etapas seguintes.

Execução: python3 tests/testes_vigencias_salvar_parametros.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_vigencias_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import (
    init_db, criar_unidade, unidade_id_existe, salvar_parametros,
    get_parametros_vigentes, get_db,
)
from app import engine

init_db()
_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


def linhas_de(uid, parametro):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT valor, competencia_inicio, competencia_fim, alterado_por "
            "FROM parametros_vigentes WHERE unidade_id=? AND parametro=? "
            "ORDER BY competencia_inicio",
            (uid, parametro)
        ).fetchall()
    return [dict(r) for r in rows]


def nenhuma_invertida(linhas):
    return all(
        (l["competencia_fim"] is None or l["competencia_fim"] >= l["competencia_inicio"])
        for l in linhas
    )


def nenhuma_sobreposta(linhas):
    ordenadas = sorted(linhas, key=lambda l: l["competencia_inicio"])
    for i in range(len(ordenadas) - 1):
        fim_atual = ordenadas[i]["competencia_fim"] or "9999-99"
        inicio_prox = ordenadas[i + 1]["competencia_inicio"]
        if fim_atual >= inicio_prox:
            return False
    return True


def cria_unidade(uid, tipo="RESULTADO_SPLIT"):
    if not unidade_id_existe(uid):
        criar_unidade(id=uid, nome=uid, contratante="Teste", inicio="2020-01-01", tipo_calculo=tipo)
        engine.load_units(force=True)


PARAM = "percentual_contratante"


# ═══════════════════════════════════════════════════════════════════════
# CASO DE REGRESSÃO OBRIGATÓRIO — reproduz e prova a correção do incidente
# de produção do Medcenter
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("REGRESSÃO — Medcenter: reaprovar 2026-06 não pode corromper 2026-07")
print("=" * 70)
uid_regr = "vig_regressao_medcenter"
cria_unidade(uid_regr)

salvar_parametros(uid_regr, "2020-01", {PARAM: 0.75}, alterado_por="seed")
salvar_parametros(uid_regr, "2026-07", {PARAM: 0.85}, alterado_por="migration_0001")
antes = linhas_de(uid_regr, PARAM)
print("  antes de reaprovar junho:", antes)

# Reaprova 2026-06 com o MESMO valor já vigente (0.75) — é exatamente o
# que a aprovação de Fechamento faz via _coletar_params_usados.
salvar_parametros(uid_regr, "2026-06", {PARAM: 0.75}, alterado_por="aprovacao")

depois = linhas_de(uid_regr, PARAM)
print("  depois de reaprovar junho:", depois)

checar("junho continua 0.75", get_parametros_vigentes(uid_regr, "2026-06")[PARAM] == 0.75)
checar("julho continua 0.85", get_parametros_vigentes(uid_regr, "2026-07")[PARAM] == 0.85)
checar("agosto continua 0.85", get_parametros_vigentes(uid_regr, "2026-08")[PARAM] == 0.85)
checar("nenhuma vigência invertida (fim >= início)", nenhuma_invertida(depois))
checar("nenhuma sobreposição entre vigências", nenhuma_sobreposta(depois))
checar("reaprovar com o mesmo valor não criou linha nova (no-op)", depois == antes)
print()


# ═══════════════════════════════════════════════════════════════════════
# 1. Editar uma competência dentro de uma vigência atual (sem futuro)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. Editar competência dentro da vigência atual (sem vigência futura)")
print("=" * 70)
uid1 = "vig_editar_atual"
cria_unidade(uid1)
salvar_parametros(uid1, "2020-01", {PARAM: 0.70}, alterado_por="seed")
salvar_parametros(uid1, "2026-05", {PARAM: 0.80}, alterado_por="operador")

linhas1 = linhas_de(uid1, PARAM)
print("  linhas:", linhas1)
checar("2026-04 continua com o valor antigo (0.70)", get_parametros_vigentes(uid1, "2026-04")[PARAM] == 0.70)
checar("2026-05 em diante usa o valor novo (0.80)", get_parametros_vigentes(uid1, "2026-05")[PARAM] == 0.80)
checar("2026-12 (bem no futuro) também usa 0.80 (vigência nova ficou aberta)",
       get_parametros_vigentes(uid1, "2026-12")[PARAM] == 0.80)
checar("nenhuma vigência invertida", nenhuma_invertida(linhas1))
checar("nenhuma sobreposição", nenhuma_sobreposta(linhas1))
print()


# ═══════════════════════════════════════════════════════════════════════
# 2. Cadastrar uma vigência futura
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Cadastrar vigência futura")
print("=" * 70)
uid2 = "vig_futura"
cria_unidade(uid2)
salvar_parametros(uid2, "2020-01", {PARAM: 0.60}, alterado_por="seed")
salvar_parametros(uid2, "2027-01", {PARAM: 0.90}, alterado_por="operador")

linhas2 = linhas_de(uid2, PARAM)
print("  linhas:", linhas2)
checar("competência atual (2026-09) continua com o valor antigo (0.60)",
       get_parametros_vigentes(uid2, "2026-09")[PARAM] == 0.60)
checar("2026-12 (mês antes da vigência futura) continua com 0.60",
       get_parametros_vigentes(uid2, "2026-12")[PARAM] == 0.60)
checar("2027-01 em diante usa o valor futuro (0.90)",
       get_parametros_vigentes(uid2, "2027-01")[PARAM] == 0.90)
checar("a vigência antiga foi corretamente limitada até 2026-12 (não ficou aberta por cima da futura)",
       any(l["competencia_inicio"] == "2020-01" and l["competencia_fim"] == "2026-12" for l in linhas2))
checar("nenhuma vigência invertida", nenhuma_invertida(linhas2))
checar("nenhuma sobreposição", nenhuma_sobreposta(linhas2))
print()


# ═══════════════════════════════════════════════════════════════════════
# 3. Salvar novamente uma competência anterior a uma vigência futura já
#    existente — MESMO CENÁRIO da regressão, mas com valor REALMENTE
#    diferente (força o split, não o caminho no-op)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Salvar competência anterior a uma vigência futura, com valor diferente")
print("=" * 70)
uid3 = "vig_anterior_com_futura"
cria_unidade(uid3)
salvar_parametros(uid3, "2020-01", {PARAM: 0.75}, alterado_por="seed")
salvar_parametros(uid3, "2026-07", {PARAM: 0.85}, alterado_por="migration")
# Corrige um valor de uma competência ANTERIOR a julho (ex.: erro de digitação em março)
salvar_parametros(uid3, "2026-03", {PARAM: 0.78}, alterado_por="correcao_manual")

linhas3 = linhas_de(uid3, PARAM)
print("  linhas:", linhas3)
checar("2026-02 continua com o valor original (0.75)", get_parametros_vigentes(uid3, "2026-02")[PARAM] == 0.75)
checar("2026-03 a 2026-06 usam o valor corrigido (0.78)", get_parametros_vigentes(uid3, "2026-03")[PARAM] == 0.78
       and get_parametros_vigentes(uid3, "2026-06")[PARAM] == 0.78)
checar("a vigência de 0.78 foi limitada até 2026-06 (não invadiu julho)",
       any(l["competencia_inicio"] == "2026-03" and l["competencia_fim"] == "2026-06" for l in linhas3))
checar("julho e agosto CONTINUAM com o valor futuro (0.85), intocado",
       get_parametros_vigentes(uid3, "2026-07")[PARAM] == 0.85
       and get_parametros_vigentes(uid3, "2026-08")[PARAM] == 0.85)
checar("a vigência futura (2026-07, migration) não foi tocada — mesmo alterado_por",
       any(l["competencia_inicio"] == "2026-07" and l["alterado_por"] == "migration" for l in linhas3))
checar("nenhuma vigência invertida", nenhuma_invertida(linhas3))
checar("nenhuma sobreposição", nenhuma_sobreposta(linhas3))
print()


# ═══════════════════════════════════════════════════════════════════════
# 4. Salvar valor igual não cria linhas desnecessárias
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Salvar o mesmo valor não cria linha nova")
print("=" * 70)
uid4 = "vig_valor_igual"
cria_unidade(uid4)
salvar_parametros(uid4, "2020-01", {PARAM: 0.65}, alterado_por="seed")
antes4 = linhas_de(uid4, PARAM)
salvar_parametros(uid4, "2026-06", {PARAM: 0.65}, alterado_por="aprovacao")  # mesmo valor já vigente
depois4 = linhas_de(uid4, PARAM)
checar("nenhuma linha nova foi criada", len(depois4) == len(antes4) == 1)
checar("valor continua correto em qualquer competência", get_parametros_vigentes(uid4, "2026-06")[PARAM] == 0.65)
print()


# ═══════════════════════════════════════════════════════════════════════
# 5. Duas alterações cronológicas normais (sem nenhuma vigência futura
#    envolvida — garante que o caminho comum de uso não regrediu)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5. Duas alterações cronológicas normais")
print("=" * 70)
uid5 = "vig_cronologica_normal"
cria_unidade(uid5)
salvar_parametros(uid5, "2020-01", {PARAM: 0.50}, alterado_por="seed")
salvar_parametros(uid5, "2025-01", {PARAM: 0.60}, alterado_por="reajuste_2025")
salvar_parametros(uid5, "2026-01", {PARAM: 0.70}, alterado_por="reajuste_2026")

linhas5 = linhas_de(uid5, PARAM)
print("  linhas:", linhas5)
checar("2024-12 usa 0.50", get_parametros_vigentes(uid5, "2024-12")[PARAM] == 0.50)
checar("2025-06 usa 0.60", get_parametros_vigentes(uid5, "2025-06")[PARAM] == 0.60)
checar("2026-06 usa 0.70", get_parametros_vigentes(uid5, "2026-06")[PARAM] == 0.70)
checar("3 vigências, todas fechadas corretamente em sequência", len(linhas5) == 3)
checar("nenhuma vigência invertida", nenhuma_invertida(linhas5))
checar("nenhuma sobreposição", nenhuma_sobreposta(linhas5))
print()


print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DE VIGÊNCIAS PASSARAM ===")
