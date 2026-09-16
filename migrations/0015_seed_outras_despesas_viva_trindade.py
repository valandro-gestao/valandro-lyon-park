"""
Semeia `custos_variaveis.outras_despesas` para Viva Trindade em
`parametros_vigentes` — homologação de set/2026, ponto 2: a operadora
relatou que "não aparece campo de outras despesas" no Fechamento, mesmo
a regra já estando implementada e testada no calculator
(app.calculators.cumulativo, v1.2.0).

Causa investigada (reproduzido chamando app.engine.get_unit_com_params
para viva_trindade/2026-08 antes desta migração): o campo EXISTE no
schema (app.calculadora_schema, COM_ALIQUOTA_CUMUL) como escalar
reservado `custos_variaveis.outras_despesas` — mas nunca foi
inicializado em `parametros_vigentes`, então a chave simplesmente não
aparece no dict reconstruído `cfg["custos_variaveis"]`
(app.models.get_parametros_vigentes só reconstrói chaves que TÊM alguma
linha na tabela).

Isso importa porque a tela de Fechamento (app.ui.fechamento.
_inputs_parametros) não tem nenhum código dedicado para os três campos
reservados de custos_variaveis (outras_despesas/investimentos/
fundo_recomposicao) — eles só aparecem porque `custos_variaveis`
reconstruído por unidade É, por coincidência de forma, um dict simples
{nome_tecnico: valor} — o mesmo formato "legado" que
app.rubricas.normalizar_rubricas já aceita para o editor genérico de
Custos Variáveis. É exatamente assim que "Investimentos" já aparece
editável no Fechamento da Viva Trindade hoje (tem uma linha vigente
`custos_variaveis.investimentos`, seed desde 2020-01) e "Fundo de
Recomposição" aparece no da W Tower (mesmo mecanismo, escopo do W Tower,
não tocado aqui). "Outras Despesas" nunca apareceu pela mesma razão
oposta: nunca teve uma linha vigente, então nunca existiu como chave do
dict, então normalizar_rubricas() não tinha item nenhum para gerar.

Solução (mesmo padrão já usado por investimentos/fundo_recomposicao —
"conforme o desenho das demais rubricas equivalentes"): semear a linha
que falta, com valor 0.0, vigente desde 2020-01 (mesma data de início
usada pelas outras duas). Nenhum código de app.ui.fechamento,
app.calculators.cumulativo ou app.calculadora_schema precisa mudar —
o campo passa a aparecer no Fechamento pelo MESMO mecanismo que já
funciona para Investimentos, com rótulo "Outras Despesas" (
app.rubricas.rotulo_exibicao: chave toda minúscula sem acento vira
title-case automático — "Outras Despesas", coincide exatamente com o
label do schema).

Escopo: só viva_trindade. Não toca nenhuma outra unidade (W Tower e o
mecanismo de fundo_recomposicao ficam fora, homologados, intocados) nem
nenhum outro parâmetro.

Idempotente: só insere se a linha ainda não existir (mesma checagem que
a migration 0008 já usa para âncoras).
"""
import json

UNIDADE_ID = "viva_trindade"
PARAMETRO = "custos_variaveis.outras_despesas"
COMPETENCIA_INICIO = "2020-01"
VALOR_INICIAL = 0.0


def apply(conn):
    row = conn.execute(
        "SELECT id FROM parametros_vigentes WHERE unidade_id=? AND parametro=?",
        (UNIDADE_ID, PARAMETRO),
    ).fetchone()

    if row is not None:
        print(f"  seed_outras_despesas_viva_trindade: já existe linha vigente para "
              f"{PARAMETRO!r} — nada a fazer.")
        return

    conn.execute(
        "INSERT INTO parametros_vigentes "
        "(unidade_id, parametro, valor, tipo_dado, descricao, "
        " competencia_inicio, alterado_por) "
        "VALUES (?, ?, ?, 'moeda', "
        "'Outras Despesas (dedução do Resultado, v1.2.0) — semeada para aparecer no "
        "Fechamento, mesmo mecanismo de Investimentos/Fundo de Recomposição', ?, "
        "'migration_0015')",
        (UNIDADE_ID, PARAMETRO, json.dumps(VALOR_INICIAL), COMPETENCIA_INICIO),
    )
    print(f"  seed_outras_despesas_viva_trindade: {PARAMETRO!r} semeado para "
          f"{UNIDADE_ID} (valor inicial {VALOR_INICIAL}, vigente desde {COMPETENCIA_INICIO}).")
