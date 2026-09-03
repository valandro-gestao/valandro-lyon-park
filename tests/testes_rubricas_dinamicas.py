"""
Cobertura permanente das rubricas dinâmicas de custos_mensais/custos_variaveis
(v1.2.0 — opção A: bloco atômico versionado, ver app.rubricas).

Cobre os cenários B a H do plano de testes desta subetapa (o cenário A —
"legado intacto, resultado de cálculo não muda" — foi verificado por
comparação de snapshot antes/depois via `git stash`, não é repetível aqui
sem duplicar o estado antes da mudança; este arquivo cobre uma versão mais
leve do mesmo princípio no cenário H, e a regressão dos testes já
existentes cobre o resto):

  B. Unidade nova sem YAML: cadastro -> parâmetros -> 2 rubricas -> vigência
     -> validar completa -> ativar -> Fechamento -> calcular -> PDF.
  C. Adição de rubrica numa vigência futura.
  D. Remoção com precedência — YAML não ressuscita a rubrica removida
     (cenário principal: ILP/MW Tristeza).
  E. Rename preserva histórico (PDF já aprovado mantém o nome antigo).
  F. Precedência explícita: bloco atômico novo > dot-notation antiga > YAML.
  G. Lista vazia é representável e válida.
  H. Campos reservados (investimentos/fundo_recomposicao) inalterados.

Roda em banco SQLite isolado (tempfile), nunca em data/seed.db ou
data/db.sqlite — a cópia é semeada a partir do data/seed.db real do
repositório (scripts/migrate.py) para os cenários D/E/F/H, que precisam de
unidades reais com bloco YAML (ILP, MW Tristeza, Viva Open Mall, FK).

Execução: python3 tests/testes_rubricas_dinamicas.py
"""
import os, sys, tempfile, shutil, atexit, subprocess

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_rubricas_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# Semeia a partir do data/seed.db real (só leitura) — necessário para os
# cenários que dependem de unidades reais com bloco YAML.
subprocess.run(
    [sys.executable, os.path.join(_REPO_ROOT, "scripts", "migrate.py")],
    env={**os.environ}, check=True, capture_output=True,
)

from app import engine
from app import run_manager as rm
from app.models import (
    init_db, criar_unidade, unidade_id_existe, salvar_parametros,
    atualizar_unidade, pode_ativar_unidade, validar_configuracao_unidade,
    get_parametros_vigentes, get_db, salvar_lancamento, ResultadoUnidade,
)
from app.rubricas import normalizar_rubricas, para_persistencia

init_db()
_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


def custos_mensais_de(uid, mes):
    return {i.id: i.valor for i in normalizar_rubricas(
        engine.get_parametros_efetivos(uid, mes).get("custos_mensais"))}


def nomes_custos_mensais_de(uid, mes):
    return {i.id: i.nome for i in normalizar_rubricas(
        engine.get_parametros_efetivos(uid, mes).get("custos_mensais"))}


# ═══════════════════════════════════════════════════════════════════════
# B. Unidade nova sem YAML — ciclo completo, sem atalho de Python
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("B. Unidade DB-only: cadastro -> rubricas -> ativação -> cálculo -> PDF")
print("=" * 70)

uid_b = "unidade_db_only_rubricas"
MES_B = "2026-09"
if not unidade_id_existe(uid_b):
    criar_unidade(id=uid_b, nome="Unidade DB Only Rubricas", contratante="Teste",
                  inicio="2026-01-01", tipo_calculo="COM_ALIQUOTA_CUMUL")
    engine.load_units(force=True)
checar("1. unidade criada sem bloco YAML", engine._yaml_blocos().get(uid_b) is None)

salvar_parametros(uid_b, MES_B, {
    "aliquota_imposto": 0.1425, "ponto_equilibrio": 5000.0,
    "percentual_aluguel": 0.75,
}, alterado_por="teste_b")
checar("2. escalares obrigatórios salvos", validar_configuracao_unidade(uid_b, MES_B) == [])

# 3. adiciona 2 rubricas — mesma forma que o editor da Administração produz
# (lista de {id, nome, valor}, via _editor_lista_estruturada/normalizar).
rubricas_b = para_persistencia(normalizar_rubricas({"condominio": 1200.0, "iptu": 300.0}))
salvar_parametros(uid_b, MES_B, {"custos_mensais": rubricas_b}, alterado_por="teste_b")
checar("3. 2 rubricas salvas como bloco atômico",
       len(custos_mensais_de(uid_b, MES_B)) == 2)

checar("4. configuração completa após rubricas", validar_configuracao_unidade(uid_b, MES_B) == [])

bloqueios_b = pode_ativar_unidade(uid_b, MES_B)
checar("5. pode_ativar_unidade libera (mesma checagem que o botão Ativar usa)", bloqueios_b == [])
atualizar_unidade(uid_b, ativo=True)
engine.load_units(force=True)

checar("6. aparece no Fechamento (get_unidades_ativas)",
       uid_b in {u["id"] for u in engine.get_unidades_ativas(MES_B)})

resultado_b = engine.calcular(uid_b, MES_B, faturamento=80000.0)
checar("7. motor calcula com as rubricas só-DB",
       resultado_b.custos.get("Condomínio") == 1200.0 and resultado_b.custos.get("IPTU") == 300.0)

resultado_b.status = "aprovado"
salvar_lancamento(resultado_b)
pdf_path_b = rm.generate_report(MES_B, uid_b, resultado_b)
checar("8. PDF gerado com sucesso", os.path.isfile(pdf_path_b))
print()


# ═══════════════════════════════════════════════════════════════════════
# C. Adição de rubrica numa vigência futura
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("C. Adição de rubrica só a partir de uma competência futura")
print("=" * 70)

MES_ANTES, MES_DEPOIS = "2026-08", "2026-09"
atual = normalizar_rubricas(engine.get_parametros_efetivos(uid_b, MES_ANTES).get("custos_mensais"))
nova_lista = para_persistencia(atual) + [{"id": "seguranca_extra", "nome": "Segurança Extra", "valor": 400.0}]
salvar_parametros(uid_b, MES_DEPOIS, {"custos_mensais": nova_lista}, alterado_por="teste_c")

checar("mês anterior NÃO tem a rubrica nova",
       "seguranca_extra" not in custos_mensais_de(uid_b, MES_ANTES))
checar("mês novo TEM a rubrica nova",
       custos_mensais_de(uid_b, MES_DEPOIS).get("seguranca_extra") == 400.0)

resultado_c = engine.calcular(uid_b, MES_DEPOIS, faturamento=80000.0)
checar("entra no cálculo do mês novo", resultado_c.custos.get("Segurança Extra") == 400.0)

u_cfg_c = engine.get_unit_com_params(uid_b, MES_DEPOIS)
checar("apareceria como input no Fechamento (mesma condição do código real)",
       any(i.id == "seguranca_extra" for i in normalizar_rubricas(u_cfg_c.get("custos_mensais"))))
print()


# ═══════════════════════════════════════════════════════════════════════
# D. Remoção com precedência — cenário principal (MW Tristeza, real)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("D. Remoção de rubrica legada (MW Tristeza) — YAML não ressuscita")
print("=" * 70)

UID_D = "mw_tristeza"
MES_D_ANTIGO, MES_D_NOVO = "2026-06", "2026-09"

antes_remocao = custos_mensais_de(UID_D, MES_D_ANTIGO)
print(f"  custos_mensais efetivos ANTES da remoção (competência antiga): {antes_remocao}")
checar("MW Tristeza tem condominio real (9073.23) via YAML antes de qualquer edição",
       antes_remocao.get("condominio") == 9073.23)

# Lançamento histórico ANTES da remoção — precisa continuar mostrando Condomínio.
resultado_hist = engine.calcular(UID_D, MES_D_ANTIGO, faturamento=150000.0)
resultado_hist.status = "aprovado"
salvar_lancamento(resultado_hist)
checar("lançamento histórico (antes da remoção) inclui Condomínio",
       resultado_hist.custos.get("Condomínio") == 9073.23)

# Remove condominio a partir de MES_D_NOVO: salva a lista SEM ele.
sem_condominio = [
    item for item in para_persistencia(normalizar_rubricas(
        engine.get_parametros_efetivos(UID_D, MES_D_ANTIGO).get("custos_mensais")))
    if item["id"] != "condominio"
]
salvar_parametros(UID_D, MES_D_NOVO, {"custos_mensais": sem_condominio}, alterado_por="teste_d")

depois_remocao = custos_mensais_de(UID_D, MES_D_NOVO)
print(f"  custos_mensais efetivos DEPOIS da remoção (competência nova): {depois_remocao}")
checar("competência NOVA não tem mais Condomínio (YAML NÃO ressuscitou)",
       "condominio" not in depois_remocao)

antigo_ainda = custos_mensais_de(UID_D, MES_D_ANTIGO)
checar("competência ANTIGA continua com Condomínio (histórico intacto)",
       antigo_ainda.get("condominio") == 9073.23)

resultado_novo = engine.calcular(UID_D, MES_D_NOVO, faturamento=150000.0)
checar("cálculo NOVO não inclui mais Condomínio",
       "Condomínio" not in resultado_novo.custos)

# O lançamento histórico já aprovado (frozen) continua com Condomínio mesmo
# depois da remoção — não é recalculado nem reescrito.
with get_db() as conn:
    row = conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
        (UID_D, MES_D_ANTIGO)
    ).fetchone()
import json as _json
hist_congelado = _json.loads(row["resultado_json"])
checar("lançamento já aprovado permanece com Condomínio no JSON congelado (não reescrito)",
       hist_congelado["custos"].get("Condomínio") == 9073.23)
print()


# ═══════════════════════════════════════════════════════════════════════
# E. Rename preserva histórico — Segurança -> Vigilância (Viva Open Mall)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("E. Rename de rubrica (Segurança -> Vigilância) preserva histórico")
print("=" * 70)

UID_E = "viva_open_mall"
MES_E_ANTIGO, MES_E_NOVO = "2026-06", "2026-09"

# Aprova um lançamento ANTES do rename, com o nome antigo (via YAML).
itens_variaveis_antes = normalizar_rubricas(
    engine.get_parametros_efetivos(UID_E, MES_E_ANTIGO).get("custos_variaveis"))
nomes_variaveis_antes = {i.id: i.nome for i in itens_variaveis_antes}
checar("id técnico 'seguranca' resolve nome 'Segurança' antes do rename",
       nomes_variaveis_antes.get("seguranca") == "Segurança")

resultado_e_antigo = engine.calcular(UID_E, MES_E_ANTIGO, faturamento=300000.0)
resultado_e_antigo.status = "aprovado"
salvar_lancamento(resultado_e_antigo)
pdf_antigo = rm.generate_report(MES_E_ANTIGO, UID_E, resultado_e_antigo)
checar("PDF antigo (pré-rename) gerado", os.path.isfile(pdf_antigo))
checar("resultado.custos do lançamento aprovado usa 'Segurança' (nome vigente à época)",
       "Segurança" in resultado_e_antigo.custos)

# Rename: mesma lista, mesmo id "seguranca", só o nome muda, a partir de
# MES_E_NOVO.
lista_variaveis_renomeada = [
    {"id": i.id, "nome": ("Vigilância" if i.id == "seguranca" else i.nome), "valor": i.valor}
    for i in itens_variaveis_antes
]
salvar_parametros(UID_E, MES_E_NOVO, {"custos_variaveis": lista_variaveis_renomeada}, alterado_por="teste_e")

nomes_variaveis_depois = {
    i.id: i.nome for i in normalizar_rubricas(
        engine.get_parametros_efetivos(UID_E, MES_E_NOVO).get("custos_variaveis"))
}
checar("competência NOVA resolve 'Vigilância' para o mesmo id 'seguranca'",
       nomes_variaveis_depois.get("seguranca") == "Vigilância")

nomes_variaveis_antiga_de_novo = {
    i.id: i.nome for i in normalizar_rubricas(
        engine.get_parametros_efetivos(UID_E, MES_E_ANTIGO).get("custos_variaveis"))
}
checar("competência ANTIGA continua resolvendo 'Segurança' (não foi reescrita)",
       nomes_variaveis_antiga_de_novo.get("seguranca") == "Segurança")

resultado_e_novo = engine.calcular(UID_E, MES_E_NOVO, faturamento=300000.0)
checar("cálculo NOVO usa 'Vigilância' como chave", "Vigilância" in resultado_e_novo.custos)
checar("cálculo NOVO não usa mais 'Segurança'", "Segurança" not in resultado_e_novo.custos)

# O PDF já aprovado (antigo) não é regenerado — confere que o JSON congelado
# do lançamento antigo continua com "Segurança", intacto.
with get_db() as conn:
    row_e = conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
        (UID_E, MES_E_ANTIGO)
    ).fetchone()
hist_e = _json.loads(row_e["resultado_json"])
checar("lançamento antigo aprovado permanece com 'Segurança' no JSON congelado",
       "Segurança" in hist_e["custos"])
print()


# ═══════════════════════════════════════════════════════════════════════
# F. Precedência explícita: YAML + dot-notation antigo + bloco novo
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("F. Precedência: bloco atômico novo > dot-notation antiga > YAML")
print("=" * 70)

UID_F = "ilp"  # YAML: custos_mensais.condominio = 1880.51, nunca seedado no banco
MES_F1, MES_F2, MES_F3 = "2026-01", "2026-06", "2026-09"

checar("ILP começa só com YAML (sem nenhuma linha em parametros_vigentes p/ custos)",
       get_parametros_vigentes(UID_F, MES_F1).get("custos_mensais") is None)
checar("efetivo em 2026-01 já reflete o YAML (1880.51)",
       custos_mensais_de(UID_F, MES_F1).get("condominio") == 1880.51)

# Camada 2: dot-notation antiga (simula seed manual/legado), vigente desde
# MES_F2, valor DIFERENTE do YAML.
salvar_parametros(UID_F, MES_F2, {"custos_mensais": {"condominio": 2000.0}}, alterado_por="teste_f_dot")
checar("dot-notation antiga (2026-06+) sobrepõe o YAML", custos_mensais_de(UID_F, MES_F2).get("condominio") == 2000.0)
checar("competência anterior ao dot-notation (2026-01) ainda usa o YAML",
       custos_mensais_de(UID_F, MES_F1).get("condominio") == 1880.51)

# Camada 3: bloco atômico novo, vigente desde MES_F3, valor ainda diferente.
salvar_parametros(UID_F, MES_F3, {
    "custos_mensais": [{"id": "condominio", "nome": "Condomínio", "valor": 2500.0}]
}, alterado_por="teste_f_atomico")

# Sem a correção de precedência em get_parametros_vigentes, esta chamada
# levantaria TypeError (lista indexada por string) — é o teste de
# regressão direto do problema descrito no item 4/5 do pedido.
efetivo_f3 = custos_mensais_de(UID_F, MES_F3)
checar("bloco atômico novo (2026-09+) VENCE — não estoura TypeError, valor = 2500.0",
       efetivo_f3.get("condominio") == 2500.0)
checar("bloco atômico não tem mais nenhuma outra chave residual da dot-notation",
       set(efetivo_f3.keys()) == {"condominio"})
checar("competência do meio (2026-06, antes do bloco atômico) continua na dot-notation (2000.0)",
       custos_mensais_de(UID_F, MES_F2).get("condominio") == 2000.0)
checar("competência mais antiga (2026-01) continua no YAML puro (1880.51)",
       custos_mensais_de(UID_F, MES_F1).get("condominio") == 1880.51)
print()


# ═══════════════════════════════════════════════════════════════════════
# G. Lista vazia é representável e válida
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("G. Lista vazia de rubricas — representável, sem forçar mínimo de 1")
print("=" * 70)

MES_G = "2026-10"
salvar_parametros(UID_D, MES_G, {"custos_mensais": []}, alterado_por="teste_g")
efetivo_g = custos_mensais_de(UID_D, MES_G)
checar("lista vazia salva corretamente (nenhuma rubrica)", efetivo_g == {})
checar("YAML NÃO reaparece por trás da lista vazia",
       "condominio" not in efetivo_g and "iptu" not in efetivo_g and "energia_eletrica" not in efetivo_g)

resultado_g = engine.calcular(UID_D, MES_G, faturamento=150000.0)
checar("cálculo funciona normalmente com custo zero", resultado_g.custos == {})

checar("validação NÃO exige pelo menos 1 rubrica (mapa_rubricas é sempre opcional aqui)",
       validar_configuracao_unidade(UID_D, MES_G) == [])
print()


# ═══════════════════════════════════════════════════════════════════════
# H. Campos reservados (investimentos/fundo_recomposicao) inalterados
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("H. Campos reservados COM_ALIQUOTA/COM_ALIQUOTA_CUMUL inalterados")
print("=" * 70)

UID_H = "fk"  # COM_ALIQUOTA, custos_variaveis.investimentos
MES_H = "2026-09"

resultado_h_antes = engine.calcular(UID_H, MES_H, faturamento=100000.0)
salvar_parametros(UID_H, MES_H, {"custos_variaveis": {"investimentos": 500.0}}, alterado_por="teste_h")
resultado_h_depois = engine.calcular(UID_H, MES_H, faturamento=100000.0)

checar("investimentos aplicado (dedução -> saldo_a_pagar) exatamente como antes",
       resultado_h_depois.extras.get("investimentos") == 500.0
       and resultado_h_depois.extras.get("saldo_a_pagar") ==
           round(resultado_h_depois.aluguel_calculado - 500.0, 2))
checar("aluguel_calculado (bruto, antes da dedução) não muda por causa da dedução",
       resultado_h_antes.aluguel_calculado == resultado_h_depois.aluguel_calculado)

campos_fk = engine.get_unit("fk")
from app.calculadora_schema import campos_do_tipo as _campos_do_tipo
campo_investimentos = next(
    c for c in _campos_do_tipo("COM_ALIQUOTA") if c["chave"] == "custos_variaveis.investimentos")
checar("campo 'investimentos' continua natureza=escalar (nunca mapa_rubricas)",
       campo_investimentos["natureza"] == "escalar")
checar("nenhum campo mapa_rubricas em COM_ALIQUOTA contém 'investimentos' na lista de custos_mensais",
       not any(c["chave"] == "custos_mensais" for c in _campos_do_tipo("COM_ALIQUOTA")))
print()


print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DE RUBRICAS DINÂMICAS PASSARAM (B-H) ===")
