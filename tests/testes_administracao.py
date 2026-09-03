"""
Cobertura de app.models (CRUD de unidades, status_operacional/
status_configuracao, imutabilidade de id, bloqueio de tipo_calculo após
lançamento) e do ciclo de vida completo de uma unidade nova criada pela
tela de Administração.

Roda em banco SQLite isolado (tempfile), nunca em data/seed.db ou
data/db.sqlite.

Execução: python3 tests/testes_administracao.py
"""
import os, sys, tempfile, shutil, atexit, inspect

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_admin_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import (
    listar_unidades_admin, get_unidade, criar_unidade, atualizar_unidade,
    unidade_id_existe, unidade_possui_lancamentos, status_operacional,
    status_configuracao, pode_ativar_unidade, salvar_lancamento, init_db,
    ResultadoUnidade,
)
from app.engine import load_units, get_unidades_ativas, get_unit
from app.ui.administracao import _gerar_id_sugerido

init_db()
MES = "2026-09"

_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


print("=== 1. lista das 23 unidades atuais ===")
todas = listar_unidades_admin()
checar("23 unidades no banco", len(todas) == 23)

print()
print("=== 2. status operacional x status de configuração — dois eixos independentes ===")
distrib = {}
for u in todas:
    chave = (status_operacional(u), status_configuracao(u, MES))
    distrib[chave] = distrib.get(chave, 0) + 1
print("  distribuição (operacional, configuração):", distrib)
checar("todas as 23 têm os dois status calculados", sum(distrib.values()) == 23)

# v1.2.0 (correção de parâmetros efetivos): Ekos, OKA e Terreno OKA são
# ativo=0 (nunca foram ativadas) MAS têm configuração efetiva completa —
# seus blocos YAML legados (faixas/aliquota_imposto/repasses) já são
# válidos, mesmo nunca tendo passado por get_unit_com_params. Antes desta
# correção, a validação lia só o banco (parametros_vigentes) e as 3
# apareciam incompletas por omissão de uso, não por falta de conteúdo real
# — essa era a expectativa antiga deste teste, e estava errada.
for uid in ("ekos", "oka", "terreno_oka"):
    u = get_unidade(uid)
    checar(f"{uid}: operacional = inativa", status_operacional(u) == "inativa")
    checar(f"{uid}: configuração = completa (via parâmetros efetivos, sem precisar de lazy seed)",
           status_configuracao(u, MES) == "completa")

print()
print("=== 3/4. criação de unidade teste + geração/unicidade do ID ===")
nome_teste = "Shopping Teste Administração"
id_gerado = _gerar_id_sugerido(nome_teste)
print("  nome:", nome_teste, "-> id gerado:", id_gerado)
checar("id gerado é snake_case sem acento", id_gerado == "shopping_teste_administracao")
checar("id não existe antes de criar", not unidade_id_existe(id_gerado))

criar_unidade(
    id=id_gerado, nome=nome_teste, contratante="Contratante Teste",
    inicio="2026-09-01", tipo_calculo="COM_ALIQUOTA", tipo_relatorio="padrao",
)
load_units(force=True)
checar("id existe depois de criar", unidade_id_existe(id_gerado))

try:
    criar_unidade(id=id_gerado, nome="Duplicata", contratante="X", inicio="2026-09-01",
                   tipo_calculo="COM_ALIQUOTA")
    checar("criar_unidade com id duplicado levanta ValueError", False)
except ValueError as e:
    checar(f"criar_unidade duplicado bloqueado: {e}", True)

print()
print("=== 5. nova unidade nasce Inativa + Incompleta ===")
u_nova = get_unidade(id_gerado)
checar("ativo=0 ao nascer", u_nova["ativo"] == 0)
checar("operacional = inativa", status_operacional(u_nova) == "inativa")
checar("configuração = incompleta (COM_ALIQUOTA exige parâmetros nunca preenchidos)",
       status_configuracao(u_nova, MES) == "incompleta")

print()
print("=== 6. nova unidade não aparece no Fechamento (get_unidades_ativas) ===")
ativas = get_unidades_ativas()
ids_ativas = [a["id"] for a in ativas]
checar("unidade nova NÃO está em get_unidades_ativas()", id_gerado not in ids_ativas)

print()
print("=== 7. tentativa de ativação sem parâmetros é bloqueada por pode_ativar_unidade ===")
# v1.2.0: a UI sempre renderiza o botão "Ativar unidade" (não o esconde),
# mas desabilitado + com as mensagens de pode_ativar_unidade quando há
# bloqueio (ver app.ui.administracao._secao_status_ativacao). A proteção
# real de produto é pode_ativar_unidade() != [], não mais um estado
# "em_configuracao" que a tela interpretava para ocultar o controle.
bloqueios = pode_ativar_unidade(id_gerado, MES)
checar("pode_ativar_unidade aponta bloqueio (configuração incompleta)", bloqueios != [])
print(f"    bloqueios: {bloqueios}")
checar("status_configuracao ainda incompleta (consistente com o bloqueio acima)",
       status_configuracao(get_unidade(id_gerado), MES) == "incompleta")

print()
print("=== 8. edição de nome/contratante/início/relatório ===")
atualizar_unidade(id_gerado, nome="Shopping Teste Editado", contratante="Novo Contratante",
                   inicio="2026-10-01", tipo_relatorio="com_eventos")
load_units(force=True)
u_editada = get_unidade(id_gerado)
checar("nome atualizado", u_editada["nome"] == "Shopping Teste Editado")
checar("contratante atualizado", u_editada["contratante"] == "Novo Contratante")
checar("início atualizado", u_editada["inicio"] == "2026-10-01")
checar("tipo_relatorio atualizado", u_editada["tipo_relatorio"] == "com_eventos")

print()
print("=== 9. ID imutável ===")
assinatura = inspect.signature(atualizar_unidade)
checar("atualizar_unidade não tem parâmetro 'id' editável (só posicional de busca)",
       "id" not in [p for p in assinatura.parameters if p != "unidade_id"])
checar("id continua o mesmo após todas as edições", get_unidade(id_gerado)["id"] == id_gerado)

print()
print("=== 10. modelo editável antes de lançamentos ===")
checar("sem lançamentos ainda", not unidade_possui_lancamentos(id_gerado))
atualizar_unidade(id_gerado, tipo_calculo="COM_FAIXAS")
checar("tipo_calculo alterado com sucesso (sem lançamentos)", get_unidade(id_gerado)["tipo_calculo"] == "COM_FAIXAS")

print()
print("=== 11. modelo bloqueado depois de lançamento ===")
resultado_fake = ResultadoUnidade(
    unidade_id=id_gerado, mes_referencia="2026-09", faturamento=1000.0, resultado=500.0,
)
salvar_lancamento(resultado_fake)
checar("agora possui lançamento", unidade_possui_lancamentos(id_gerado))
# A tela desabilita o campo nesse caso (ver tem_lancamentos em
# _tela_editar_unidade) — atualizar_unidade em si não impede escrita (por
# design: a regra vive na UI, não duplicada no model), então validamos que
# a condição que a UI usa para bloquear está correta:
checar("UI bloquearia edição do modelo (possui lançamento = True)", unidade_possui_lancamentos(id_gerado) is True)

print()
print("=== 12. inativar/reativar unidade existente com configuração completa (Medcenter) ===")
checar("Medcenter: configuração completa", status_configuracao(get_unidade("medcenter"), MES) == "completa")
checar("Medcenter está ativa hoje", status_operacional(get_unidade("medcenter")) == "ativa")
atualizar_unidade("medcenter", ativo=False)
load_units(force=True)
checar("Medcenter agora inativa", status_operacional(get_unidade("medcenter")) == "inativa")
checar("Medcenter continua com configuração completa (eixo independente do operacional)",
       status_configuracao(get_unidade("medcenter"), MES) == "completa")
checar("Medcenter some de get_unidades_ativas()", "medcenter" not in [a["id"] for a in get_unidades_ativas()])
atualizar_unidade("medcenter", ativo=True)
load_units(force=True)
checar("Medcenter reativada", status_operacional(get_unidade("medcenter")) == "ativa")
checar("Medcenter volta a aparecer em get_unidades_ativas()", "medcenter" in [a["id"] for a in get_unidades_ativas()])

print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DE LÓGICA PASSARAM ===")
