"""
Cobertura permanente do bloco de correções pós-1º-reprocessamento (feedback
real da operadora após o fechamento de julho/2026, já com Medcenter e a
cadeia temporal validados em produção).

Cobre, nesta ordem:
  1. PDF das unidades COM_ALIQUOTA_CUMUL — a linha de prejuízo acumulado
     mostrava a ENTRADA do mês, não a SAÍDA (app.reporter._prestacao_padrao).
  2. MW Tristeza — remoção de `taxa_admin_fixa` de COM_ALIQUOTA_CUMUL
     (schema, calculator, YAML) — a operadora confirmou que esse campo era
     só controle da planilha antiga, sem correspondência na regra
     contratual real. `taxa_admin_fixa` de PERCENTUAL_SIMPLES (Vasco) tem
     semântica diferente e não foi tocado.
  3. Pátio Manutenções — migration 0010, que corrige o sinal da âncora
     `saldo_acumulado_inicial` gravada errada (positiva) pela migration
     0008 já aplicada em produção.
  4. Pátio Manutenções — a linha final "Repasse / Aluguel" (redundante com
     Resultado) não deve mais aparecer na tela de cálculo dessa unidade.
  5. Pátio Operação — os dois Pontos de Equilíbrio (REAL, MAIOJAMA) agora
     são editáveis e versionados por competência via parametros_vigentes
     (bloco atômico "splits", DB vence YAML, calculator inalterado).

Não cobre (fora de escopo desta etapa, ver retorno da investigação):
histórico anual/mensal do Pátio Manutenções, reconstrução histórica de
Dom Pedro/MW, Axis/FK/IN, IPCA do MW, W Tower.

Execução: python3 tests/testes_correcoes_pos_reprocessamento.py
"""
import os, sys, tempfile, shutil, atexit, subprocess, json, importlib.util

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_pos_reprocessamento_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from app.models import init_db, get_db, ResultadoUnidade, salvar_parametros
from app.calculadora_schema import SCHEMAS_POR_TIPO
from app.calculators.cumulativo import calcular_com_aliquota_cumul
from app.reporter import _prestacao_padrao

init_db()
_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


# ═══════════════════════════════════════════════════════════════════════
# 1. PDF das unidades COM_ALIQUOTA_CUMUL — prejuízo acumulado = SAÍDA
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. PDF COM_ALIQUOTA_CUMUL — linha de prejuízo mostra a SAÍDA")
print("=" * 70)

r_dom_pedro = ResultadoUnidade(
    unidade_id="dom_pedro", mes_referencia="2026-06", faturamento=12000.0,
    aliquota_imposto=0.0, subtotal=12000.0, ponto_equilibrio=0.0, custos={},
    resultado=-425.28,
    prejuizo_acumulado_entrada=-171239.32,
    prejuizo_acumulado_saida=-171664.60,
    aluguel_calculado=0.0, extras={},
)
cfg_cumul = {"relatorio": {"linhas": ["resultado", "prejuizo", "aluguel"]}}

prestacao = _prestacao_padrao(r_dom_pedro, cfg_cumul)
linha_prejuizo = next(l for l in prestacao.linhas if l.descricao == "(+/-) Prejuízo Acumulado")

checar("linha de prejuízo usa prejuizo_acumulado_SAÍDA, não a entrada",
       linha_prejuizo.valor == r_dom_pedro.prejuizo_acumulado_saida)
checar("saída != entrada neste caso (garante que o teste testa algo real)",
       r_dom_pedro.prejuizo_acumulado_saida != r_dom_pedro.prejuizo_acumulado_entrada)
checar("valor exibido é -171664.60 (o caso real relatado pela operadora)",
       linha_prejuizo.valor == -171664.60)
print()


# ═══════════════════════════════════════════════════════════════════════
# 2. MW Tristeza — remoção de taxa_admin_fixa de COM_ALIQUOTA_CUMUL
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. MW Tristeza — taxa_admin_fixa removida de COM_ALIQUOTA_CUMUL")
print("=" * 70)

chaves_cumul = [c["chave"] for c in SCHEMAS_POR_TIPO["COM_ALIQUOTA_CUMUL"]["campos"]]
chaves_simples = [c["chave"] for c in SCHEMAS_POR_TIPO["PERCENTUAL_SIMPLES"]["campos"]]

checar("taxa_admin_fixa não existe mais no schema de COM_ALIQUOTA_CUMUL",
       "taxa_admin_fixa" not in chaves_cumul)
checar("taxa_admin_fixa continua no schema de PERCENTUAL_SIMPLES (Vasco)",
       "taxa_admin_fixa" in chaves_simples)

# Calculator: mesmo que um cfg legado ainda tenha taxa_admin_fixa (ex.:
# resquício de config antiga não migrada), o calculator não deve mais
# aplicar nenhum piso nem gerar extras["taxa_admin"].
cfg_mw = {
    "id": "mw_like", "aliquota_imposto": 0.0, "percentual_aluguel": 0.5,
    "taxa_admin_fixa": 4350.0,  # resquício — não deve ter mais efeito
}
resultado_mw = calcular_com_aliquota_cumul(cfg_mw, "2026-06", faturamento=100.0, saldo_override=0.0)

checar("repasse = 50% do resultado disponível (50.0), sem piso de 4350",
       resultado_mw.aluguel_calculado == 50.0)
checar("extras não contém mais 'taxa_admin'",
       "taxa_admin" not in resultado_mw.extras)

# YAML real: mw_tristeza não tem mais o campo, Vasco continua com o dele.
with open(os.path.join(_REPO_ROOT, "data", "units.yaml"), encoding="utf-8") as f:
    _yaml_texto = f.read()
import re as _re
_bloco_mw = _re.search(r"  - id: mw_tristeza\n(?:.*\n)+?(?=  - id: |\Z)", _yaml_texto).group(0)
_bloco_vasco = _re.search(r"  - id: vasco\n(?:.*\n)+?(?=  - id: |\Z)", _yaml_texto).group(0)

checar("bloco YAML de mw_tristeza não tem mais taxa_admin_fixa",
       "taxa_admin_fixa" not in _bloco_mw)
checar("bloco YAML de mw_tristeza não lista mais 'taxa_admin' em relatorio.linhas",
       "taxa_admin" not in _re.search(r"linhas: \[(.*?)\]", _bloco_mw).group(1))
checar("bloco YAML de vasco (PERCENTUAL_SIMPLES) continua com taxa_admin_fixa",
       "taxa_admin_fixa" in _bloco_vasco)
print()


# ═══════════════════════════════════════════════════════════════════════
# 3. Migration 0010 — correção do sinal da âncora de Pátio Manutenções
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Migration 0010 — sinal da âncora de Pátio Manutenções")
print("=" * 70)

_spec = importlib.util.spec_from_file_location(
    "migration_0010_teste",
    os.path.join(_REPO_ROOT, "migrations", "0010_corrigir_sinal_ancora_patio_manutencao.py"),
)
_mod_0010 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod_0010)

UID_PATIO_MAN = "patio_manutencao"
PARAM_ANCORA = "saldo_acumulado_inicial"


def _inserir_ancora(uid, valor, competencia="2026-06", alterado_por="migration_0008"):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO parametros_vigentes "
            "(unidade_id, parametro, valor, tipo_dado, descricao, competencia_inicio, alterado_por) "
            "VALUES (?, ?, ?, 'moeda', 'teste', ?, ?)",
            (uid, PARAM_ANCORA, json.dumps(valor), competencia, alterado_por),
        )


def _valor_ancora(uid):
    with get_db() as conn:
        row = conn.execute(
            "SELECT valor FROM parametros_vigentes WHERE unidade_id=? AND parametro=?",
            (uid, PARAM_ANCORA),
        ).fetchone()
    return json.loads(row["valor"]) if row else None


def _contagem_lancamentos():
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM lancamentos").fetchone()["n"]


# 3a. Assinatura exata da produção: +42223.85 -> corrige para -42223.85
_inserir_ancora(UID_PATIO_MAN, 42223.85)
antes_lancamentos = _contagem_lancamentos()
with get_db() as conn:
    _mod_0010.apply(conn)
checar("3a. valor corrigido de +42223.85 para -42223.85",
       _valor_ancora(UID_PATIO_MAN) == -42223.85)
checar("3a. não tocou em lancamentos", _contagem_lancamentos() == antes_lancamentos)

# 3b. Idempotência: rodar de novo não altera nada nem levanta exceção
with get_db() as conn:
    _mod_0010.apply(conn)
checar("3b. segunda execução — valor continua -42223.85 (idempotente)",
       _valor_ancora(UID_PATIO_MAN) == -42223.85)

with get_db() as conn:
    conn.execute("DELETE FROM parametros_vigentes WHERE unidade_id=?", (UID_PATIO_MAN,))

# 3c. Já correta desde o início -> não altera, não levanta exceção
_inserir_ancora(UID_PATIO_MAN, -42223.85)
with get_db() as conn:
    _mod_0010.apply(conn)
checar("3c. valor já correto (-42223.85) permanece inalterado",
       _valor_ancora(UID_PATIO_MAN) == -42223.85)

with get_db() as conn:
    conn.execute("DELETE FROM parametros_vigentes WHERE unidade_id=?", (UID_PATIO_MAN,))

# 3d. Divergência inesperada (nem +42223.85 nem -42223.85) -> não altera
_inserir_ancora(UID_PATIO_MAN, -999.0)
with get_db() as conn:
    _mod_0010.apply(conn)
checar("3d. valor divergente inesperado (-999.0) não é sobrescrito",
       _valor_ancora(UID_PATIO_MAN) == -999.0)

with get_db() as conn:
    conn.execute("DELETE FROM parametros_vigentes WHERE unidade_id=?", (UID_PATIO_MAN,))

# 3e. Linha ausente -> não cria nada, não levanta exceção
with get_db() as conn:
    _mod_0010.apply(conn)
checar("3e. sem linha nenhuma — não cria âncora nova", _valor_ancora(UID_PATIO_MAN) is None)

# 3f. Mais de uma linha para o mesmo parâmetro -> divergência, nenhuma alterada
_inserir_ancora(UID_PATIO_MAN, 42223.85, competencia="2026-06")
_inserir_ancora(UID_PATIO_MAN, 42223.85, competencia="2026-07")
with get_db() as conn:
    valores_antes = [json.loads(r["valor"]) for r in conn.execute(
        "SELECT valor FROM parametros_vigentes WHERE unidade_id=? ORDER BY competencia_inicio",
        (UID_PATIO_MAN,)).fetchall()]
    _mod_0010.apply(conn)
    valores_depois = [json.loads(r["valor"]) for r in conn.execute(
        "SELECT valor FROM parametros_vigentes WHERE unidade_id=? ORDER BY competencia_inicio",
        (UID_PATIO_MAN,)).fetchall()]
checar("3f. mais de uma linha -> nenhuma é alterada (divergência)",
       valores_antes == valores_depois == [42223.85, 42223.85])

with get_db() as conn:
    conn.execute("DELETE FROM parametros_vigentes WHERE unidade_id=?", (UID_PATIO_MAN,))
print()


# ═══════════════════════════════════════════════════════════════════════
# 4. Pátio Manutenções — linha "Repasse / Aluguel" some da tela de cálculo
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Pátio Manutenções — linha 'Repasse / Aluguel' removida da tela")
print("=" * 70)

import app.ui.fechamento as fechamento

_capturado = {}


def _fake_dataframe(df, *a, **kw):
    _capturado["labels"] = list(df.iloc[:, 0])


_dataframe_original = fechamento.st.dataframe
fechamento.st.dataframe = _fake_dataframe

r_patio_man = ResultadoUnidade(
    unidade_id="patio_manutencao", mes_referencia="2026-06", faturamento=5481.26,
    aliquota_imposto=0.05, subtotal=5207.20, ponto_equilibrio=0.0, custos={},
    resultado=4690.52, prejuizo_acumulado_entrada=-42223.85,
    prejuizo_acumulado_saida=-37533.33, aluguel_calculado=4690.52,
    extras={"retencao_iss": 274.06, "saldo_acumulado": -37533.33},
)
fechamento._mostrar_resultado_unit(r_patio_man)
labels_patio_man = _capturado.get("labels", [])

checar("Pátio Manutenções: 'Repasse / Aluguel' não aparece",
       "Repasse / Aluguel" not in labels_patio_man)
checar("Pátio Manutenções: 'Saldo a Pagar' também não aparece",
       "Saldo a Pagar" not in labels_patio_man)
checar("Pátio Manutenções: 'Resultado' continua aparecendo",
       "Resultado" in labels_patio_man)

# Outra unidade (não Pátio Manutenções) continua mostrando a linha —
# garante que a mudança é escopada, não uma regressão global.
r_outra = ResultadoUnidade(
    unidade_id="outra_unidade_generica", mes_referencia="2026-06", faturamento=10000.0,
    aliquota_imposto=0.0, subtotal=10000.0, ponto_equilibrio=0.0, custos={},
    resultado=1000.0, prejuizo_acumulado_entrada=0.0, prejuizo_acumulado_saida=0.0,
    aluguel_calculado=750.0, extras={},
)
fechamento._mostrar_resultado_unit(r_outra)
labels_outra = _capturado.get("labels", [])

checar("outra unidade: 'Repasse / Aluguel' continua aparecendo (sem regressão)",
       "Repasse / Aluguel" in labels_outra)

fechamento.st.dataframe = _dataframe_original
print()


# ═══════════════════════════════════════════════════════════════════════
# 5. Pátio Operação — PE editável e versionado por competência
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("5. Pátio Operação — Ponto de Equilíbrio versionado (splits atômico)")
print("=" * 70)

# Precisa da unidade real "patio" com o bloco YAML de splits — semeia a
# partir do data/seed.db real (só leitura) + todas as migrations
# rastreadas, igual ao padrão já usado por outras suítes desta etapa.
subprocess.run(
    [sys.executable, os.path.join(_REPO_ROOT, "scripts", "migrate.py")],
    env={**os.environ}, check=True, capture_output=True,
)

from app.engine import get_unit_com_params, load_units
from app.calculators.patio import calcular_patio

load_units(force=True)

splits_julho_antes = {s["id"]: s for s in get_unit_com_params("patio", "2026-07")["splits"]}
pe_real_yaml = splits_julho_antes["real"]["ponto_equilibrio"]
pe_maiojama_yaml = splits_julho_antes["maiojama"]["ponto_equilibrio"]

checar("YAML real: PE do REAL é o valor conhecido (22675.67)", pe_real_yaml == 22675.67)
checar("YAML real: PE do MAIOJAMA é o valor conhecido (19692.37)", pe_maiojama_yaml == 19692.37)

# Simula exatamente o que o botão "Salvar Ponto de Equilíbrio" faz:
# regrava o array splits inteiro, só troca o PE do REAL, para agosto/2026.
novo_pe_real = 30000.0
novo_splits_ago = []
for s in get_unit_com_params("patio", "2026-08")["splits"]:
    s = dict(s)
    if s["id"] == "real":
        s["ponto_equilibrio"] = novo_pe_real
    novo_splits_ago.append(s)
salvar_parametros("patio", "2026-08", {"splits": novo_splits_ago}, alterado_por="operador")

splits_agosto = {s["id"]: s for s in get_unit_com_params("patio", "2026-08")["splits"]}
splits_julho_depois = {s["id"]: s for s in get_unit_com_params("patio", "2026-07")["splits"]}

checar("agosto: PE do REAL foi atualizado para 30000.0",
       splits_agosto["real"]["ponto_equilibrio"] == 30000.0)
checar("agosto: PE do MAIOJAMA preservado (não editado)",
       splits_agosto["maiojama"]["ponto_equilibrio"] == pe_maiojama_yaml)
checar("agosto: demais campos do REAL preservados (percentual_split)",
       splits_agosto["real"]["percentual_split"] == splits_julho_antes["real"]["percentual_split"])
checar("agosto: demais campos do REAL preservados (custos_mensais)",
       splits_agosto["real"]["custos_mensais"] == splits_julho_antes["real"]["custos_mensais"])

checar("julho NÃO foi alterado pela mudança de agosto (PE do REAL continua YAML)",
       splits_julho_depois["real"]["ponto_equilibrio"] == pe_real_yaml)
checar("julho NÃO foi alterado pela mudança de agosto (MAIOJAMA continua YAML)",
       splits_julho_depois["maiojama"]["ponto_equilibrio"] == pe_maiojama_yaml)

# Fim a fim: o calculator realmente usa o novo PE quando calcula agosto.
cfg_patio_ago = get_unit_com_params("patio", "2026-08")
resultado_patio_ago = calcular_patio(cfg_patio_ago, "2026-08", fat_total=200000.0)
checar("calculator usa o novo PE do REAL ao calcular agosto",
       resultado_patio_ago.real.ponto_equilibrio == 30000.0)

cfg_patio_jul = get_unit_com_params("patio", "2026-07")
resultado_patio_jul = calcular_patio(cfg_patio_jul, "2026-07", fat_total=200000.0)
checar("calculator continua usando o PE do YAML ao calcular julho",
       resultado_patio_jul.real.ponto_equilibrio == pe_real_yaml)
print()


print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DO BLOCO PÓS-REPROCESSAMENTO PASSARAM ===")
