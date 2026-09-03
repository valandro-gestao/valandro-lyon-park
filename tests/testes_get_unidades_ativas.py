"""
Cobertura permanente da regra de 4 condições de app.engine.
get_unidades_ativas() (v1.2.0, "fechar o ciclo de ativação da unidade"):

    uma unidade só é oferecida no Fechamento de uma competência quando
    (1) está operacionalmente ativa (ativo=1);
    (2) a competência é >= início;
    (3) possui configuração efetiva válida naquela competência
        (app.models.validar_configuracao_unidade, via
        app.engine.get_parametros_efetivos) OU
    (4) já existe lançamento gravado naquela competência.

Deliberadamente sem dependência de date.today(): as 4 condições valem do
mesmo jeito para qualquer competência, passada, presente ou futura — ver
o cenário 8 abaixo, que prova isso explicitamente.

Roda em banco SQLite isolado (tempfile), nunca em data/seed.db ou
data/db.sqlite. Chama a implementação real de get_unidades_ativas() em
todos os cenários — não reimplementa a regra em Python para comparar.

Execução: python3 tests/testes_get_unidades_ativas.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_gua_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import engine
from app.models import (
    init_db, criar_unidade, unidade_id_existe, salvar_parametros,
    atualizar_unidade, salvar_lancamento, unidade_possui_lancamento_no_mes,
    get_db, ResultadoUnidade,
)

init_db()
_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


def aparece(uid, mes):
    ativas = engine.get_unidades_ativas(mes) if mes is not None else engine.get_unidades_ativas()
    return uid in {u["id"] for u in ativas}


def cria(uid, inicio, tipo_calculo="PERCENTUAL_SIMPLES"):
    if not unidade_id_existe(uid):
        criar_unidade(id=uid, nome=uid, contratante="Teste", inicio=inicio, tipo_calculo=tipo_calculo)
        engine.load_units(force=True)


# 1. ativa + antes do início -> não aparece
cria("gua_antes_inicio", "2026-06-01")
salvar_parametros("gua_antes_inicio", "2026-01",
                   {"percentual_aluguel": 0.1, "ponto_equilibrio": 1000.0}, alterado_por="teste")
atualizar_unidade("gua_antes_inicio", ativo=True)
engine.load_units(force=True)
checar("1. ativa + competência antes do início -> não aparece",
       not aparece("gua_antes_inicio", "2026-03"))

# 2. ativa + configuração inválida + sem lançamento -> não aparece
cria("gua_sem_config", "2026-01-01")
atualizar_unidade("gua_sem_config", ativo=True)
engine.load_units(force=True)
checar("2. ativa + configuração inválida + sem lançamento -> não aparece",
       not aparece("gua_sem_config", "2026-05"))

# 3. ativa + configuração válida -> aparece
cria("gua_config_valida", "2026-01-01")
salvar_parametros("gua_config_valida", "2026-01",
                   {"percentual_aluguel": 0.1, "ponto_equilibrio": 1000.0}, alterado_por="teste")
atualizar_unidade("gua_config_valida", ativo=True)
engine.load_units(force=True)
checar("3. ativa + configuração válida -> aparece",
       aparece("gua_config_valida", "2026-05"))

# 4. ativa + configuração inválida + lançamento existente -> aparece
cria("gua_com_lancamento", "2026-01-01")
atualizar_unidade("gua_com_lancamento", ativo=True)
engine.load_units(force=True)
checar("4a. antes do lançamento, sem config válida -> não aparece",
       not aparece("gua_com_lancamento", "2026-02"))
salvar_lancamento(ResultadoUnidade(
    unidade_id="gua_com_lancamento", mes_referencia="2026-02",
    faturamento=50000.0, status="rascunho",
))
checar("4b. com lançamento gravado, mesmo sem config válida -> aparece",
       aparece("gua_com_lancamento", "2026-02"))
with get_db() as conn:
    conn.execute("DELETE FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
                 ("gua_com_lancamento", "2026-02"))
checar("4c. removido só o lançamento -> volta a não aparecer",
       not aparece("gua_com_lancamento", "2026-02"))

# 5. inativa + configuração válida -> não aparece
cria("gua_inativa_completa", "2026-01-01")
salvar_parametros("gua_inativa_completa", "2026-01",
                   {"percentual_aluguel": 0.1, "ponto_equilibrio": 1000.0}, alterado_por="teste")
# nunca ativada (ativo=0 por padrão em criar_unidade)
checar("5. inativa + configuração válida -> não aparece",
       not aparece("gua_inativa_completa", "2026-05"))

# 6. mes_referencia=None -> mantém comportamento estrutural anterior (só ativo=1)
cria("gua_sem_mes", "2099-01-01")  # início no futuro distante, config nunca preenchida
atualizar_unidade("gua_sem_mes", ativo=True)
engine.load_units(force=True)
checar("6. mes_referencia=None ignora início/config, só olha ativo=1",
       aparece("gua_sem_mes", None))

# 7. PATIO_OPERACAO ativo continua aparecendo (nao_aplicavel = sem bloqueio)
cria("gua_patio", "2026-01-01", tipo_calculo="PATIO_OPERACAO")
atualizar_unidade("gua_patio", ativo=True)
engine.load_units(force=True)
checar("7. PATIO_OPERACAO ativo (nao_aplicavel) -> aparece sem precisar de config/lançamento",
       aparece("gua_patio", "2026-05"))

# 8. primeira configuração em outubro não aparece em setembro — prova de
#    que a regra não depende de date.today() (nenhuma chamada abaixo passa
#    a data atual; "hoje" é só o rótulo do cenário, não um parâmetro).
cria("gua_out_nao_set", "2026-01-01")
salvar_parametros("gua_out_nao_set", "2026-10",
                   {"percentual_aluguel": 0.2, "ponto_equilibrio": 2000.0}, alterado_por="teste")
atualizar_unidade("gua_out_nao_set", ativo=True)
engine.load_units(force=True)
checar("8a. primeira config em 2026-10 -> 2026-09 (\"hoje\" simulado) não aparece",
       not aparece("gua_out_nao_set", "2026-09"))
checar("8b. primeira config em 2026-10 -> 2026-10 aparece",
       aparece("gua_out_nao_set", "2026-10"))

print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DE get_unidades_ativas() PASSARAM ===")
