"""
Cobertura permanente da 5ª rodada de homologação de set/2026 (produção real
— Débora). Único achado: rubricas monetárias novas (mapa_rubricas, ex.:
FIERGS/custos_variaveis) persistiam corretamente, mas o editor da tela de
Administração não aceitava digitar ponto nem vírgula no Valor — impedindo
informar centavos.

Causa exata (comprovada ao vivo com st.data_editor de verdade, não
bypassado — reprodução em /tmp, fora deste repo, ver relatório desta
rodada): DUAS causas independentes, ambas necessárias para o bug completo:

  1. `_column_config_editor` (app/ui/administracao.py) configurava a coluna
     "moeda" do st.column_config.NumberColumn com `step=100.0`. `step`
     define a PRECISÃO DE EDIÇÃO da célula no data_editor (não é só o
     incremento das setinhas) — com um step inteiro, o próprio separador
     decimal fica bloqueado na digitação, mesmo em coluna float64.
     Confirmado ao vivo: com step=100.0, digitar "150,50" ou "150.50"
     silenciosamente vira "150" na célula, aconteça o que acontecer com o
     dtype.

  2. `_linhas_para_dataframe` construía a coluna via
     `pd.to_numeric(..., errors="coerce")`, que infere dtype int64 sempre
     que TODOS os valores atuais da coluna são inteiros (inclusive coluna
     vazia, primeiro item de um campo novo) — ex.: 100 e 200 (exatamente o
     cenário reportado: "Teste despesa A = 100", "Teste Despesa B = 200").
     Mesmo depois de corrigir (1) e conseguir digitar o ponto decimal, a
     coluna int64 TRUNCA o valor de volta para inteiro ao reconstruir o
     DataFrame editado (confirmado ao vivo: 123.45 digitado -> 123
     devolvido pelo st.data_editor).

Corrigido:
  - `_column_config_editor`: step=100.0 -> step=0.01 para "moeda" (mesma
    precisão do format "R$ %.2f").
  - `_editor_faixas_com_limite`: mesma correção no NumberColumn ad-hoc da
    coluna "Até (R$)" das faixas (usa o mesmo bug, configuração própria,
    fora de `_column_config_editor`).
  - `_linhas_para_dataframe`: adiciona `.astype("float64")` após o
    `pd.to_numeric` para as colunas "percentual"/"moeda" — garante que a
    coluna nunca vire int64, mesmo quando os valores atuais são todos
    "redondos". Sem isso, o fix do step sozinho não bastava (confirmado ao
    vivo).

Correção genérica: aplicada a QUALQUER campo mapa_rubricas/moeda que usa
`_editor_tabela_simples`/`_editor_faixas_com_limite` (splits, faixas,
custos_mensais/custos_variaveis de qualquer unidade) — não é solução
exclusiva de FIERGS. Nenhuma fórmula financeira foi alterada; a correção é
só na camada de edição/apresentação do st.data_editor.

Execução: python3 tests/testes_homologacao_set2026_v5.py
"""
import os, sys, tempfile, shutil, atexit

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_v5_")
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


# ═══════════════════════════════════════════════════════════════════════
# 1. Configuração da coluna "Valor" (step) — causa #1 do bloqueio
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. _column_config_editor / _editor_faixas_com_limite — step não é mais inteiro")
print("=" * 70)
import inspect
from app.ui.administracao import _column_config_editor

cc_moeda = _column_config_editor({"chave": "valor", "label": "Valor", "tipo_dado": "moeda"})
checar("Coluna 'moeda' usa step=0.01 (não step=100.0, que bloqueava o ponto/vírgula)",
       cc_moeda["type_config"]["step"] == 0.01)
checar("Formato de exibição continua 'R$ %.2f' (apresentação inalterada)",
       cc_moeda["type_config"]["format"] == "R$ %.2f")

cc_pct = _column_config_editor({"chave": "pct", "label": "Percentual", "tipo_dado": "percentual"})
checar("Coluna 'percentual' não foi alterada por esta correção (continua step=0.5)",
       cc_pct["type_config"]["step"] == 0.5)

_fonte_faixas = inspect.getsource(
    __import__("app.ui.administracao", fromlist=["_editor_faixas_com_limite"])._editor_faixas_com_limite
)
checar("_editor_faixas_com_limite (coluna 'Até (R$)') também usa step=0.01",
       "step=0.01" in _fonte_faixas)
checar("Nenhum step=100.0 sobrou em NumberColumn de _editor_faixas_com_limite",
       "step=100.0" not in _fonte_faixas)


# ═══════════════════════════════════════════════════════════════════════
# 2. dtype da coluna do data_editor — causa #2 (truncamento no commit)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. _linhas_para_dataframe — coluna moeda nunca mais vira int64")
print("=" * 70)
from app.ui.administracao import _linhas_para_dataframe, _dataframe_para_itens

COLUNAS = [
    {"chave": "id", "label": "Identificador", "tipo_dado": "texto",
     "obrigatorio": False, "gerado_automaticamente": True},
    {"chave": "nome", "label": "Rubrica", "tipo_dado": "texto", "obrigatorio": True},
    {"chave": "valor", "label": "Valor", "tipo_dado": "moeda", "obrigatorio": True, "minimo": 0.0},
]

# Cenário exato do relatado: todos os valores atuais são inteiros (100, 200)
# — é justamente esse caso que fazia pd.to_numeric inferir int64.
itens_iniciais = [
    {"id": "teste_despesa_a", "nome": "Teste despesa A", "valor": 100},
    {"id": "teste_despesa_b", "nome": "Teste Despesa B", "valor": 200},
]
df = _linhas_para_dataframe(itens_iniciais, COLUNAS, campo_id="id")
checar("Coluna 'Valor' é float64 mesmo com todos os valores atuais inteiros",
       df["Valor"].dtype.name == "float64")

df_vazio = _linhas_para_dataframe([], COLUNAS, campo_id="id")
checar("Coluna 'Valor' é float64 também quando o campo está vazio (primeiro item)",
       df_vazio["Valor"].dtype.name == "float64")


# ═══════════════════════════════════════════════════════════════════════
# 3. Ida e volta completa: "Teste decimal = 123,45" sem truncar/arredondar
#    (simula exatamente o que o st.data_editor corrigido devolve — mesma
#    dupla causa já eliminada nas seções 1 e 2, confirmada ao vivo no
#    browser real, ver relatório desta rodada)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Administração -> persistência -> reabertura -> cálculo, sem truncar/arredondar")
print("=" * 70)
import pandas as pd

df_editado = df.copy()
nova_linha = pd.DataFrame([{"Identificador": None, "Rubrica": "Teste decimal", "Valor": 123.45}])
df_editado = pd.concat([df_editado, nova_linha], ignore_index=True)
itens_editados = _dataframe_para_itens(df_editado, COLUNAS, campo_id="id")

item_decimal = next(i for i in itens_editados if i["nome"] == "Teste decimal")
checar("_dataframe_para_itens preserva 123.45 exatamente (não 123, não 124)",
       item_decimal["valor"] == 123.45)
checar("id técnico foi gerado a partir do nome ('teste_decimal')",
       item_decimal["id"] == "teste_decimal")
checar("Itens antigos (100 e 200) continuam intactos",
       {i["nome"]: i["valor"] for i in itens_editados if i["nome"] != "Teste decimal"}
       == {"Teste despesa A": 100, "Teste Despesa B": 200})

# --- Persistência real (salvar_parametros) + reabertura (get_unit_com_params)
from app.models import salvar_parametros
from app.engine import get_unit_com_params, calcular

UID = "fiergs"
MES = "2027-01"  # competência isolada, sem lançamento/histórico prévio

salvar_parametros(UID, MES, {"custos_variaveis": itens_editados}, alterado_por="teste_v5")
cfg_recarregado = get_unit_com_params(UID, MES)
custos_recarregados = cfg_recarregado.get("custos_variaveis") or []
item_recarregado = next((i for i in custos_recarregados if i.get("nome") == "Teste decimal"), None)

checar("Reabertura (get_unit_com_params) encontra a rubrica 'Teste decimal'",
       item_recarregado is not None)
checar("Reabertura mostra R$ 123,45 (não truncado para 123 nem arredondado para 124)",
       item_recarregado is not None and item_recarregado["valor"] == 123.45)

# --- Cálculo: deduz exatamente R$ 123,45 (delta antes/depois da rubrica) ---
FAT = 50000.0
r_com = calcular(UID, MES, FAT)

# Mesma competência, mesmos custos MENOS a rubrica de teste — isola o efeito
# exato de "Teste decimal" no resultado, sem depender de reconstruir a
# fórmula completa da calculadora aqui.
salvar_parametros(UID, MES,
                   {"custos_variaveis": [i for i in itens_editados if i["nome"] != "Teste decimal"]},
                   alterado_por="teste_v5")
r_sem = calcular(UID, MES, FAT)

delta = round(r_sem.resultado - r_com.resultado, 2)
checar("Cálculo deduz exatamente R$ 123,45 (delta de Resultado com/sem a rubrica)",
       delta == 123.45)
checar("Resultado não é um número 'redondo' por coincidência de arredondamento",
       r_com.resultado != round(r_com.resultado))


print("=" * 70)
if _falhas:
    print(f"FALHAS: {len(_falhas)}")
    for f in _falhas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 (RODADA 5) PASSARAM ===")
