"""
Corrige o sinal da âncora de saldo acumulado de Pátio Manutenções, gravada
errada (positiva) pela migration 0008.

A operadora confirmou o valor oficial do saldo até maio/2026 como NEGATIVO
(-42223.85) — a migration 0008 recebeu o valor já com o sinal trocado
(+42223.85) e, como não havia nenhuma linha anterior para esse parâmetro
nesta unidade, inseriu sem detectar divergência (não há bug em 0008: ela
faz exatamente o que se propõe — comparar contra o que já existe no
banco, não contra um valor oficial externo que ela mesma não conhece
estar errado).

Estado encontrado em produção (já aplicado, migration 0008 já rodou):
    parametro=saldo_acumulado_inicial, unidade=patio_manutencao,
    competencia_inicio=2026-06, competencia_fim=NULL,
    valor=42223.85, alterado_por=migration_0008

Estado corrigido:
    valor=-42223.85 (mesma linha, mesmo id — só o valor e os metadados de
    alteração mudam; não fecha/cria vigência nova, porque a 0008 já é a
    única e correta abertura da cadeia real para esta unidade a partir de
    2026-06 — só o número dela estava errado).

Reconhece a assinatura EXATA desse estado (não é um corretor genérico de
âncoras):
  1. unidade_id='patio_manutencao', parametro='saldo_acumulado_inicial';
  2. competencia_inicio='2026-06';
  3. valor numericamente igual a +42223.85 (dentro de meio centavo).

Comportamento:
  - assinatura exata encontrada -> corrige o valor para -42223.85, reporta
    a correção;
  - valor já é -42223.85 -> reporta "já correta", não faz nada (idempotente
    em uma segunda execução, inclusive após a própria correção desta
    migração);
  - qualquer outro estado (linha ausente, competencia_inicio diferente,
    valor diferente de +42223.85 e de -42223.85, mais de uma linha) ->
    reporta divergência e NÃO altera nada — decisão manual.

Não toca `lancamentos`. Não recalcula nada — não reprocessa junho de Pátio
Manutenções automaticamente; isso continua sendo feito depois, pelo fluxo
normal do sistema (reabrir/recalcular/reaprovar), já que junho já existe
como lançamento aprovado com a entrada errada (0.0, porque a âncora ainda
não existia quando foi calculado) e precisa ser recalculado para herdar a
entrada correta (-42223.85) e a saída correta (-37533.33, dado o resultado
de junho já aprovado, 4690.52).
"""
import json

UNIDADE = "patio_manutencao"
PARAMETRO = "saldo_acumulado_inicial"
COMPETENCIA = "2026-06"
VALOR_ERRADO = 42223.85
VALOR_OFICIAL = -42223.85
TOLERANCIA = 0.005  # meio centavo — margem de arredondamento de float


def apply(conn):
    linhas = conn.execute(
        "SELECT id, valor, competencia_inicio, competencia_fim "
        "FROM parametros_vigentes WHERE unidade_id=? AND parametro=?",
        (UNIDADE, PARAMETRO),
    ).fetchall()

    if len(linhas) != 1:
        print(f"  corrigir_sinal_ancora_patio_manutencao: esperada exatamente 1 linha "
              f"para {UNIDADE}/{PARAMETRO}, encontrada(s) {len(linhas)} — "
              f"divergência, nada alterado.")
        return

    linha = linhas[0]
    if linha["competencia_inicio"] != COMPETENCIA:
        print(f"  corrigir_sinal_ancora_patio_manutencao: competencia_inicio inesperada "
              f"(encontrada={linha['competencia_inicio']!r}, esperada={COMPETENCIA!r}) — "
              f"divergência, nada alterado.")
        return

    try:
        valor_atual = float(json.loads(linha["valor"]))
    except (json.JSONDecodeError, TypeError, ValueError):
        print(f"  corrigir_sinal_ancora_patio_manutencao: valor ilegível "
              f"({linha['valor']!r}) — divergência, nada alterado.")
        return

    if abs(valor_atual - VALOR_OFICIAL) < TOLERANCIA:
        print("  corrigir_sinal_ancora_patio_manutencao: já correta "
              f"({VALOR_OFICIAL}) — nada a fazer.")
        return

    if abs(valor_atual - VALOR_ERRADO) >= TOLERANCIA:
        print(f"  corrigir_sinal_ancora_patio_manutencao: valor encontrado "
              f"({valor_atual!r}) não corresponde à assinatura conhecida "
              f"(nem {VALOR_OFICIAL}, nem {VALOR_ERRADO}) — divergência, nada alterado.")
        return

    conn.execute(
        "UPDATE parametros_vigentes "
        "SET valor=?, alterado_em=datetime('now'), alterado_por=? "
        "WHERE id=?",
        (json.dumps(VALOR_OFICIAL), "migration_0010", linha["id"]),
    )
    print(f"  corrigir_sinal_ancora_patio_manutencao: corrigido {VALOR_ERRADO} -> "
          f"{VALOR_OFICIAL} (id={linha['id']}, competencia_inicio={COMPETENCIA}).")
