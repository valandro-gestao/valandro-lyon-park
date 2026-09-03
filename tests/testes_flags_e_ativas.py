"""
Cobertura de (1) precedência banco > YAML para flags booleanas vigentes,
via o resolver centralizado usado pelo fluxo real (get_unit_com_params);
(2) app.engine.get_unidades_ativas() — regra de 4 condições (ativo +
início + configuração efetiva válida OU lançamento existente); e
(3) independência dos dois eixos de status (status_operacional x
status_configuracao).

Roda em banco SQLite isolado (tempfile), nunca em data/seed.db ou
data/db.sqlite.

Execução: python3 tests/testes_flags_e_ativas.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_flags_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import engine
from app.models import (
    init_db, salvar_parametros, criar_unidade, unidade_id_existe,
    validar_configuracao_unidade, status_operacional, status_configuracao,
    get_unidade, atualizar_unidade,
)
from app.calculadora_schema import SCHEMAS_POR_TIPO

init_db()
MES = "2026-09"

_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


# ═══════════════════════════════════════════════════════════════════════
# PARTE 1 — precedência banco > YAML para as 3 flags booleanas, via o
# resolver centralizado JÁ usado pelo fluxo real (get_unit_com_params,
# exatamente o que app.ui.fechamento._tela_detalhe chama na linha
# "u = get_unit_com_params(uid, mes_ref)").
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("PARTE 1 — flags booleanas no fluxo operacional")
print("=" * 70)

cfg = engine.get_unit_com_params("fiergs", MES)
checar("Fiergs: tem_receita_selos = True (igual ao YAML, sem override)",
       cfg.get("tem_receita_selos") is True)
checar("Fiergs: tem_base_taxa_cobranca = True (igual ao YAML)",
       cfg.get("tem_base_taxa_cobranca") is True)

cfg_vasco = engine.get_unit_com_params("vasco", MES)
checar("Vasco: nenhuma das 3 flags presente (nunca teve no YAML) -> None/False, igual sempre",
       not cfg_vasco.get("tem_faturamento_carregadores")
       and not cfg_vasco.get("tem_receita_selos")
       and not cfg_vasco.get("tem_base_taxa_cobranca"))

salvar_parametros("vasco", "2026-01", {"tem_faturamento_carregadores": True}, alterado_por="teste")
cfg_vasco2 = engine.get_unit_com_params("vasco", MES)
checar("Vasco com override True no banco -> passa a valer True (era ausente/False)",
       cfg_vasco2.get("tem_faturamento_carregadores") is True)

salvar_parametros("fiergs", "2026-01", {"tem_receita_selos": False}, alterado_por="teste")
cfg_fiergs2 = engine.get_unit_com_params("fiergs", MES)
checar("Fiergs com override False no banco -> passa a valer False (era True no YAML)",
       cfg_fiergs2.get("tem_receita_selos") is False)
checar("tipo é bool de verdade", isinstance(cfg_fiergs2.get("tem_receita_selos"), bool))

salvar_parametros("fiergs", "2026-07", {"tem_receita_selos": True}, alterado_por="teste")
cfg_antes_jul = engine.get_unit_com_params("fiergs", "2026-06")
cfg_dps_jul = engine.get_unit_com_params("fiergs", "2026-07")
checar("Fiergs em 2026-06 (antes da mudança de vigência): False",
       cfg_antes_jul.get("tem_receita_selos") is False)
checar("Fiergs em 2026-07 (nova vigência): True",
       cfg_dps_jul.get("tem_receita_selos") is True)

uid = "unidade_so_banco_flags"
if not unidade_id_existe(uid):
    criar_unidade(id=uid, nome="Unidade Só Banco", contratante="X",
                   inicio="2026-01-01", tipo_calculo="COM_FAIXAS")
    engine.load_units(force=True)
cfg_novo_antes = engine.get_unit_com_params(uid, MES)
checar("unidade só-banco, sem configurar: tem_base_taxa_cobranca ausente/False",
       not cfg_novo_antes.get("tem_base_taxa_cobranca"))
salvar_parametros(uid, "2026-01", {"tem_base_taxa_cobranca": True, "taxa_cobranca": 0.02}, alterado_por="teste")
cfg_novo_depois = engine.get_unit_com_params(uid, MES)
checar("unidade só-banco, após configurar: tem_base_taxa_cobranca = True",
       cfg_novo_depois.get("tem_base_taxa_cobranca") is True)
print()


# ═══════════════════════════════════════════════════════════════════════
# PARTE 2 — get_unidades_ativas(): regra de 4 condições (v1.2.0)
# ativo=1 E competência >= início E (config efetiva válida OU lançamento
# já existe naquela competência). Deliberadamente sem dependência de
# date.today() — ver app.engine.get_unidades_ativas.
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("PARTE 2 — get_unidades_ativas()")
print("=" * 70)

ids_ativas_sem_mes = {u["id"] for u in engine.get_unidades_ativas()}
print(f"  Sem mes_referencia: {len(ids_ativas_sem_mes)} unidades")
checar("sem mes_referencia, comportamento estrutural anterior: só ativo=1 (20 unidades)",
       len(ids_ativas_sem_mes) == 20)

# Ekos/OKA/Terreno OKA são ativo=0 (nunca foram ativadas) — por isso NUNCA
# aparecem em get_unidades_ativas, independentemente de sua configuração
# efetiva ser completa (confirmado em tests/testes_administracao.py). O
# filtro de `ativo` é sempre a primeira condição, incondicional.
for mes in ("2026-06", "2026-07", "2026-09"):
    ids = {u["id"] for u in engine.get_unidades_ativas(mes)}
    print(f"  {mes}: {len(ids)} unidades — Ekos/OKA/Terreno OKA presentes? "
          f"{[u for u in ('ekos','oka','terreno_oka') if u in ids]}")
    checar(f"{mes}: Ekos ausente (ativo=0)", "ekos" not in ids)
    checar(f"{mes}: OKA ausente (ativo=0)", "oka" not in ids)
    checar(f"{mes}: Terreno OKA ausente (ativo=0)", "terreno_oka" not in ids)

# 2026-07 e 2026-09: as 20 unidades ativas reais têm configuração efetiva
# válida (ou nao_aplicavel, como Pátio) nessas competências.
checar("2026-07: exatamente 20 unidades", len({u["id"] for u in engine.get_unidades_ativas("2026-07")}) == 20)
checar("2026-09: exatamente 20 unidades", len({u["id"] for u in engine.get_unidades_ativas("2026-09")}) == 20)

# 2026-06: achado real, não um bug — Medcenter tem uma vigência de splits
# (percentual_operador/percentual_contratante) que só passa a somar 100%
# a partir de 2026-07; antes disso a config efetiva soma 90% e é inválida.
# Este data/seed.db local não tem lançamento gravado para medcenter em
# 2026-06 (só até 2025-12 — ver NOTA em tests/testes_schema.py sobre o
# fixture local não refletir o histórico completo da produção real), então
# a condição 4 (lançamento existente) também não a resgata aqui. Por isso
# são 19, não 20, nesta competência especificamente — o resultado correto
# dado os dados deste fixture, não um valor arbitrário.
ids_2026_06 = {u["id"] for u in engine.get_unidades_ativas("2026-06")}
checar("2026-06: exatamente 19 unidades (medcenter ainda com splits somando 90% "
       "nesta competência, sem lançamento local que a resgate)",
       len(ids_2026_06) == 19)
checar("2026-06: medcenter especificamente ausente (splits somam 90%, não 100%)",
       "medcenter" not in ids_2026_06)
checar("2026-06: medcenter fica inválida por causa da regra de soma 100%",
       any("somar 100%" in e for e in validar_configuracao_unidade("medcenter", "2026-06")))
checar("2026-07: medcenter volta a aparecer (vigência nova dos splits já vale)",
       "medcenter" in {u["id"] for u in engine.get_unidades_ativas("2026-07")})

# Competência histórica: FK (ativo=1, inicio 2024-07) não deveria aparecer
# antes do seu início.
ids_2022 = {u["id"] for u in engine.get_unidades_ativas("2022-01")}
checar("FK ausente em 2022-01 (antes do seu início real, 2024-07)", "fk" not in ids_2022)
ids_2024_08 = {u["id"] for u in engine.get_unidades_ativas("2024-08")}
checar("FK presente em 2024-08 (depois do seu início; YAML legado não é vigência-aware, "
       "então a config efetiva de FK já é válida mesmo tão cedo)", "fk" in ids_2024_08)

# Unidade ativa com início futuro E configuração válida: prova o limite de
# início isoladamente (sem a configuração ser o fator bloqueante).
uid_futura = "unidade_ativa_futura"
if not unidade_id_existe(uid_futura):
    criar_unidade(id=uid_futura, nome="Unidade Futura", contratante="X",
                   inicio="2027-01-01", tipo_calculo="COM_FAIXAS")
    engine.load_units(force=True)
salvar_parametros(uid_futura, "2027-01", {
    "faixas": [{"ate": None, "percentual": 0.8}],
    "aliquota_imposto": 0.1, "ponto_equilibrio": 1000.0,
}, alterado_por="teste")
atualizar_unidade(uid_futura, ativo=True)
engine.load_units(force=True)
checar("unidade futura tem configuração válida (isolando a variável 'início')",
       validar_configuracao_unidade(uid_futura, "2027-02") == [])
ids_2026_09 = {u["id"] for u in engine.get_unidades_ativas("2026-09")}
ids_2027_02 = {u["id"] for u in engine.get_unidades_ativas("2027-02")}
checar("unidade ativa com início em 2027 NÃO aparece em 2026-09 (antes do início)",
       uid_futura not in ids_2026_09)
checar("a mesma unidade aparece em 2027-02 (depois do início, com config válida)",
       uid_futura in ids_2027_02)

# Contraprova: a MESMA unidade, se não tivesse configuração válida, também
# não apareceria em 2027-02 (a condição de config OU lançamento é real,
# não um placeholder) — usamos uma segunda unidade idêntica sem parâmetros.
uid_futura_sem_config = "unidade_ativa_futura_sem_config"
if not unidade_id_existe(uid_futura_sem_config):
    criar_unidade(id=uid_futura_sem_config, nome="Unidade Futura Sem Config", contratante="X",
                   inicio="2027-01-01", tipo_calculo="COM_FAIXAS")
    engine.load_units(force=True)
atualizar_unidade(uid_futura_sem_config, ativo=True)
engine.load_units(force=True)
ids_2027_02_v2 = {u["id"] for u in engine.get_unidades_ativas("2027-02")}
checar("mesma unidade, mas SEM configuração válida -> não aparece nem depois do início",
       uid_futura_sem_config not in ids_2027_02_v2)
print()


# ═══════════════════════════════════════════════════════════════════════
# PARTE 3 — status estrutural (Ativa/Inativa) x status de configuração
# (Completa/Incompleta/Não aplicável) — dimensões independentes
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("PARTE 3 — status estrutural x status de configuração")
print("=" * 70)

for u in engine.get_unidades_ativas():
    engine.get_unit_com_params(u["id"], MES)

todas = engine.load_units()
tabela = []
for uid_i in sorted(todas):
    u = get_unidade(uid_i)
    estrutural = status_operacional(u)
    config = status_configuracao(u, MES)
    tabela.append((uid_i, estrutural, config))
    print(f"  {uid_i:26s} estrutural={estrutural:8s} configuracao={config}")

# Prova sintética de "Inativa + Completa": Ekos/OKA/Terreno OKA já cobrem
# esse caso com dados reais (ver tests/testes_administracao.py); aqui
# construímos mais uma unidade sintética para o mesmo propósito original
# do teste — demonstrar que a combinação é representável pelo modelo.
uid_inativa_completa = "unidade_inativa_completa"
if not unidade_id_existe(uid_inativa_completa):
    criar_unidade(id=uid_inativa_completa, nome="Unidade Inativa Completa", contratante="X",
                   inicio="2020-01-01", tipo_calculo="PERCENTUAL_SIMPLES")
    engine.load_units(force=True)
salvar_parametros(uid_inativa_completa, "2020-01", {
    "percentual_aluguel": 0.7, "ponto_equilibrio": 1000.0,
}, alterado_por="teste")
# ativo permanece False (default de criar_unidade) — nunca foi ativada
todas = engine.load_units(force=True)
u_ic = get_unidade(uid_inativa_completa)
checar("unidade sintética: estrutural = inativa (tem parâmetro, nunca foi ativada)",
       status_operacional(u_ic) == "inativa")
checar("unidade sintética: configuração completa mesmo sendo inativa",
       status_configuracao(u_ic, MES) == "completa")
tabela.append((uid_inativa_completa, "inativa", "completa"))

# Prova sintética de "Inativa + Incompleta": com a correção de parâmetros
# efetivos, nenhuma unidade REAL do seed atual está mais nesse estado
# (Ekos/OKA/Terreno OKA viraram Inativa+Completa) — o que é o resultado
# correto, não uma lacuna de cobertura. Criamos uma unidade sintética
# dedicada para continuar provando que o estado Inativa+Incompleta
# também é representável pelo modelo.
uid_inativa_incompleta = "unidade_inativa_incompleta"
if not unidade_id_existe(uid_inativa_incompleta):
    criar_unidade(id=uid_inativa_incompleta, nome="Unidade Inativa Incompleta", contratante="X",
                   inicio="2020-01-01", tipo_calculo="PERCENTUAL_SIMPLES")
    engine.load_units(force=True)
# nenhum parâmetro salvo, ativo permanece False
u_ii = get_unidade(uid_inativa_incompleta)
checar("unidade sintética: estrutural = inativa", status_operacional(u_ii) == "inativa")
checar("unidade sintética: configuração incompleta (nunca configurada)",
       status_configuracao(u_ii, MES) == "incompleta")
tabela.append((uid_inativa_incompleta, "inativa", "incompleta"))

inativas_completas = [r for r in tabela if r[1] == "inativa" and r[2] == "completa"]
inativas_incompletas = [r for r in tabela if r[1] == "inativa" and r[2] == "incompleta"]
print()
print("  Inativa + Completa:", [r[0] for r in inativas_completas])
print("  Inativa + Incompleta:", [r[0] for r in inativas_incompletas])
checar("existem casos reais de Inativa+Completa (ekos, oka, terreno_oka, além da sintética)",
       {"ekos", "oka", "terreno_oka"}.issubset({r[0] for r in inativas_completas}))
checar("existe pelo menos um caso Inativa+Incompleta (sintética — nenhuma unidade real "
       "do seed atual está mais neste estado após a correção de parâmetros efetivos)",
       any(r[0] == uid_inativa_incompleta for r in inativas_incompletas))

print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES PASSARAM ===")
