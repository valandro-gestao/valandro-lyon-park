"""
Cobertura de app.calculadora_schema / app.models.validar_configuracao_unidade
através de vários tipos de cálculo (RESULTADO_SPLIT, COM_ALIQUOTA_SPLIT,
COM_ALIQUOTA_CUMUL, COM_FAIXAS, PATIO_MANUTENCAO), das flags booleanas
vigentes (tem_base_taxa_cobranca) e da retrocompatibilidade do YAML legado
via app.engine.get_parametros_efetivos.

Roda em banco SQLite isolado (tempfile), nunca em data/seed.db ou
data/db.sqlite (só LÊ o data/seed.db do repositório, via seed_db_if_missing,
para reproduzir o estado real das unidades cadastradas).

Execução: python3 tests/testes_schema.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_schema_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import engine
from app.models import (
    init_db, validar_configuracao_unidade, get_parametros_vigentes,
    salvar_parametros, criar_unidade, unidade_id_existe,
)
from app.calculadora_schema import SCHEMAS_POR_TIPO, campo_por_chave

init_db()
MES = "2026-09"

_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


# ── 1a. Estado exatamente como está hoje em data/seed.db (sem tocar nada) ─
print("=== 1a. Retrocompatibilidade — estado ATUAL de data/seed.db, sem tocar nada ===")
todas = engine.load_units()
completas, incompletas = [], []
for uid in sorted(todas):
    tipo = todas[uid]["tipo_calculo"]
    if tipo not in SCHEMAS_POR_TIPO:
        continue
    erros = validar_configuracao_unidade(uid, MES)
    (incompletas if erros else completas).append((uid, tipo, erros))

print(f"  completas: {len(completas)} -> {[u for u,_,_ in completas]}")
print(f"  incompletas: {len(incompletas)}")
for uid, tipo, erros in incompletas:
    print(f"    ! {uid} ({tipo}): {erros[0]}{'  (+' + str(len(erros)-1) + ' outra(s))' if len(erros) > 1 else ''}")
print()


# ── 1b. Ekos/OKA — parâmetros efetivos (YAML) resolvem completo mesmo sem
#    nunca terem sido "tocadas" por get_unit_com_params (lazy seed) ───────
#    Correção desta subetapa (v1.2.0, "fechar o ciclo de ativação"):
#    validar_configuracao_unidade passou a usar app.engine.get_parametros_
#    efetivos (YAML + banco, sem side-effect) em vez de get_parametros_
#    vigentes (banco puro). Antes, Ekos/OKA/Terreno OKA (ativo=False, nunca
#    calculadas em produção) apareciam "incompletas" só por nunca terem
#    disparado o lazy seed — não porque faltasse conteúdo de verdade: o
#    bloco YAML de ambas já tem faixas/aliquota_imposto/ponto_equilibrio
#    válidos. Isso NÃO é um dado a corrigir — é a expectativa antiga do
#    teste que estava errada.
print("=== 1b. Ekos/OKA/Terreno OKA já são COMPLETAS via parâmetros efetivos, sem serem tocadas ===")
uids_incompletas_1a = {uid for uid, _, _ in incompletas}
checar("ekos não precisa mais ser tocada para ficar completa (YAML já é válido)",
       "ekos" not in uids_incompletas_1a)
checar("oka idem", "oka" not in uids_incompletas_1a)
checar("terreno_oka idem (o bloco 'repasses' mora só no YAML, nunca foi migrado para o banco)",
       "terreno_oka" not in uids_incompletas_1a)
print()


# ── 1c. Simulando uso operacional real (unidades ativas tocadas uma vez) ──
print("=== 1c. Retrocompatibilidade — simulando uso operacional real (unidades ativas) ===")
ativas = engine.get_unidades_ativas()  # sem mes_referencia => só ativo=True
for u in ativas:
    engine.get_unit_com_params(u["id"], MES)

completas, incompletas = [], []
for uid in sorted(todas):
    tipo = todas[uid]["tipo_calculo"]
    if tipo not in SCHEMAS_POR_TIPO:
        continue
    erros = validar_configuracao_unidade(uid, MES)
    (incompletas if erros else completas).append((uid, tipo, erros))

print(f"  completas: {len(completas)}")
print(f"  incompletas: {len(incompletas)}")
for uid, tipo, erros in incompletas:
    print(f"    ! {uid} ({tipo}): {erros}")

uids_incompletas = {uid for uid, _, _ in incompletas}
checar("todas as unidades ativas ficam completas ao serem tocadas uma vez",
       uids_incompletas.isdisjoint({u["id"] for u in ativas}))
checar("tocar as unidades ativas não muda o veredito de ekos/oka/terreno_oka "
       "(elas já eram completas antes de qualquer lazy seed)",
       uids_incompletas == uids_incompletas_1a)
print()


# ── 2. Cenários isolados ─────────────────────────────────────────────────
print("=== 2. Cenários isolados ===")

def unidade_fake(tipo_calculo, sufixo):
    uid = f"teste_{sufixo}"
    if not unidade_id_existe(uid):
        criar_unidade(id=uid, nome=f"Teste {sufixo}", contratante="Teste",
                       inicio="2026-01-01", tipo_calculo=tipo_calculo)
        engine.load_units(force=True)
    return uid


# RESULTADO_SPLIT 15% + 85% -> válido
uid = unidade_fake("RESULTADO_SPLIT", "rs_valido")
salvar_parametros(uid, "2026-01", {
    "aliquota_imposto": 0.1425, "despesas_fixas": 1000.0,
    "percentual_operador": 0.15, "percentual_contratante": 0.85,
}, alterado_por="teste")
erros = validar_configuracao_unidade(uid, MES)
checar("RESULTADO_SPLIT 15%+85% -> válido (sem erros)", erros == [])

# RESULTADO_SPLIT 20% + 85% -> inválido (soma 105%)
uid = unidade_fake("RESULTADO_SPLIT", "rs_invalido")
salvar_parametros(uid, "2026-01", {
    "aliquota_imposto": 0.1425, "despesas_fixas": 1000.0,
    "percentual_operador": 0.20, "percentual_contratante": 0.85,
}, alterado_por="teste")
erros = validar_configuracao_unidade(uid, MES)
checar("RESULTADO_SPLIT 20%+85% -> inválido", any("somar 100%" in e for e in erros))

# COM_ALIQUOTA_SPLIT somando 100% -> válido
uid = unidade_fake("COM_ALIQUOTA_SPLIT", "split_valido")
salvar_parametros(uid, "2026-01", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 1000.0,
    "splits": [
        {"id": "a", "nome": "A", "percentual_split": 0.6, "percentual_aluguel": 0.7},
        {"id": "b", "nome": "B", "percentual_split": 0.4, "percentual_aluguel": 0.7},
    ],
}, alterado_por="teste")
erros = validar_configuracao_unidade(uid, MES)
checar("COM_ALIQUOTA_SPLIT somando 100% -> válido", erros == [])

# splits somando diferente de 100% -> inválido
uid = unidade_fake("COM_ALIQUOTA_SPLIT", "split_invalido")
salvar_parametros(uid, "2026-01", {
    "aliquota_imposto": 0.0, "ponto_equilibrio": 1000.0,
    "splits": [
        {"id": "a", "nome": "A", "percentual_split": 0.6, "percentual_aluguel": 0.7},
        {"id": "b", "nome": "B", "percentual_split": 0.3, "percentual_aluguel": 0.7},
    ],
}, alterado_por="teste")
erros = validar_configuracao_unidade(uid, MES)
checar("splits somando 90% -> inválido", any("somar 100%" in e for e in erros))

# COM_ALIQUOTA_CUMUL só com percentual -> válido
uid = unidade_fake("COM_ALIQUOTA_CUMUL", "cumul_pct")
salvar_parametros(uid, "2026-01", {
    "aliquota_imposto": 0.1425, "ponto_equilibrio": 1000.0,
    "percentual_aluguel": 0.75,
}, alterado_por="teste")
erros = validar_configuracao_unidade(uid, MES)
checar("COM_ALIQUOTA_CUMUL só com percentual_aluguel -> válido", erros == [])

# só com faixas -> válido
uid = unidade_fake("COM_ALIQUOTA_CUMUL", "cumul_faixas")
salvar_parametros(uid, "2026-01", {
    "aliquota_imposto": 0.1425, "ponto_equilibrio": 1000.0,
    "faixas_aluguel": [{"ate": 50000.0, "percentual": 0.4}, {"ate": None, "percentual": 0.7}],
}, alterado_por="teste")
erros = validar_configuracao_unidade(uid, MES)
checar("COM_ALIQUOTA_CUMUL só com faixas_aluguel -> válido", erros == [])

# sem nenhum dos dois -> inválido
uid = unidade_fake("COM_ALIQUOTA_CUMUL", "cumul_nenhum")
salvar_parametros(uid, "2026-01", {
    "aliquota_imposto": 0.1425, "ponto_equilibrio": 1000.0,
}, alterado_por="teste")
erros = validar_configuracao_unidade(uid, MES)
checar("COM_ALIQUOTA_CUMUL sem percentual nem faixas -> inválido",
       any("faixas de aluguel" in e for e in erros))

# COM_FAIXAS sem faixas -> inválido
uid = unidade_fake("COM_FAIXAS", "faixas_vazio")
salvar_parametros(uid, "2026-01", {
    "aliquota_imposto": 0.1425, "ponto_equilibrio": 1000.0,
}, alterado_por="teste")
erros = validar_configuracao_unidade(uid, MES)
checar("COM_FAIXAS sem faixas -> inválido", any("Faixas de Cálculo" in e for e in erros))

# PATIO_MANUTENCAO sem retencao_iss explícita em unidade NOVA -> incompleto
uid = unidade_fake("PATIO_MANUTENCAO", "manut_sem_iss")
erros = validar_configuracao_unidade(uid, MES)
checar("PATIO_MANUTENCAO nova, sem retencao_iss -> incompleto (mesmo com default técnico 0.05)",
       any("Retenção de ISS" in e for e in erros))

# ... e com retencao_iss explícita -> completo
salvar_parametros(uid, "2026-01", {"retencao_iss": 0.05}, alterado_por="teste")
erros = validar_configuracao_unidade(uid, MES)
checar("PATIO_MANUTENCAO com retencao_iss explícita -> completo", erros == [])
print()


# ── 3. Booleano vigente mudando entre competências ──────────────────────
print("=== 3. Booleano vigente mudando entre competências ===")
uid = unidade_fake("COM_FAIXAS", "bool_vigencia")
salvar_parametros(uid, "2026-01", {
    "faixas": [{"ate": None, "percentual": 0.8}],
    "aliquota_imposto": 0.1, "ponto_equilibrio": 0.0,
    "tem_base_taxa_cobranca": False,
}, alterado_por="teste")
antes = get_parametros_vigentes(uid, "2026-03")
checar("tem_base_taxa_cobranca=False em 2026-03", antes.get("tem_base_taxa_cobranca") is False)

salvar_parametros(uid, "2026-06", {"tem_base_taxa_cobranca": True, "taxa_cobranca": 0.02}, alterado_por="teste")
depois_antiga = get_parametros_vigentes(uid, "2026-03")
depois_nova = get_parametros_vigentes(uid, "2026-06")
checar("competência antiga (2026-03) preserva False — vigência não reescreve o passado",
       depois_antiga.get("tem_base_taxa_cobranca") is False)
checar("competência nova (2026-06) reflete True", depois_nova.get("tem_base_taxa_cobranca") is True)
checar("tipo Python é bool de verdade (não 0/1/string)", isinstance(depois_nova.get("tem_base_taxa_cobranca"), bool))

uid2 = unidade_fake("COM_FAIXAS", "bool_condicional")
salvar_parametros(uid2, "2026-01", {
    "faixas": [{"ate": None, "percentual": 0.8}],
    "aliquota_imposto": 0.1, "ponto_equilibrio": 0.0,
}, alterado_por="teste")
erros_antes = validar_configuracao_unidade(uid2, MES)
checar("sem tem_base_taxa_cobranca definido -> taxa_cobranca não é exigida", erros_antes == [])
salvar_parametros(uid2, "2026-01", {"tem_base_taxa_cobranca": True}, alterado_por="teste")
erros_depois = validar_configuracao_unidade(uid2, MES)
checar("com tem_base_taxa_cobranca=True e taxa_cobranca ausente -> incompleto (obrigatorio_se)",
       any("Taxa de Cobrança" in e for e in erros_depois))
print()


# ── 4. Flag existente no YAML mantendo exatamente o comportamento atual ──
print("=== 4. Flag existente do YAML (Fiergs) — comportamento inalterado ===")
u_fiergs_antes = engine.get_unit("fiergs")
cfg_fiergs = engine.get_unit_com_params("fiergs", MES)
checar("get_unit() continua lendo do YAML (True) — fechamento.py não muda de comportamento",
       u_fiergs_antes.get("tem_receita_selos") is True)
checar("get_unit_com_params() também reflete True (banco já seedou o mesmo valor do YAML)",
       cfg_fiergs.get("tem_receita_selos") is True)

params_fiergs = get_parametros_vigentes("fiergs", MES)
checar("tem_receita_selos foi seedado em parametros_vigentes pelo get_unit_com_params acima",
       "tem_receita_selos" in params_fiergs)
checar("tem_base_taxa_cobranca também persistido para fiergs",
       "tem_base_taxa_cobranca" in params_fiergs)
print()

# ── 5. Ajuda de ordenação nas faixas (v1.2.0 — melhoria de UX, sem tocar
#    validação) — texto precisa estar na descrição exibida na Administração
#    dos dois únicos campos com estrutura_ordenada ────────────────────────
print("=== 5. Texto de ajuda sobre ordem das faixas presente na descrição ===")
_ORIENTACAO_FAIXAS = "As faixas devem estar em ordem crescente. A última pode ficar sem limite."
campo_faixas_aluguel = campo_por_chave("COM_ALIQUOTA_CUMUL", "faixas_aluguel")
campo_faixas = campo_por_chave("COM_FAIXAS", "faixas")
checar("COM_ALIQUOTA_CUMUL.faixas_aluguel tem a orientação de ordem na descrição",
       _ORIENTACAO_FAIXAS in (campo_faixas_aluguel or {}).get("descricao", ""))
checar("COM_FAIXAS.faixas tem a orientação de ordem na descrição",
       _ORIENTACAO_FAIXAS in (campo_faixas or {}).get("descricao", ""))
print()

if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES PASSARAM ===")
