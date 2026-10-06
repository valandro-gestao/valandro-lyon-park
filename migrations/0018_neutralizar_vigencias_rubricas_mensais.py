"""
Neutraliza vigências LEGADAS de rubricas mensais (`custos_variaveis.
outras_despesas` e `custos_variaveis.investimentos`) criadas pelas
aprovações anteriores a a7ab174 — homologação set/2026, 4ª rodada.

Problema: antes de a7ab174, toda aprovação no Fechamento varria o valor
digitado dessas duas rubricas para `parametros_vigentes` como uma
vigência nova e ABERTA (`alterado_por='aprovacao'`). Caso real (Viva
Trindade): outras_despesas = 2.400 / início 2026-08 / sem fim — o valor de
Agosto passou a valer para toda competência seguinte. O calculator já foi
corrigido (app.rubricas.valor_rubrica_mensal: a rubrica mensal vem só da
entrada da própria competência, e 0.0 é zero), então essa linha deixou de
afetar o cálculo; esta migration limpa o dado para que a Administração/
histórico também não a mostrem como valor vigente em meses futuros.

Regra, por linha candidata — `alterado_por='aprovacao'`, valor != 0,
parâmetro em (outras_despesas, investimentos), unidade cujo
`tipo_calculo` declara esses campos como escalares reservados
(COM_ALIQUOTA_CUMUL e COM_ALIQUOTA — nos demais tipos, `custos_variaveis`
é um mapa de rubricas e um `investimentos` ali pode ser uma rubrica
genuína, então NÃO é tocado):
  1. a linha é limitada ao seu PRÓPRIO mês (`competencia_fim =
     competencia_inicio`) — o valor continua registrado, e auditável, na
     competência em que realmente foi digitado;
  2. o restante do período que ela cobria (do mês seguinte até o fim
     original, ou aberto) passa a ser coberto por uma linha 0.0
     (`alterado_por='migration_0018'`). A chave precisa continuar
     existindo em `cfg["custos_variaveis"]`: o campo do Fechamento é gerado
     a partir das chaves presentes (mesmo motivo da migration 0015).

NÃO toca `lancamentos` (Agosto, e qualquer outra competência já aprovada,
continua exatamente como foi calculado — comparação byte-a-byte nos
testes), `rascunhos_unidade`, `saldos_acumulados` nem `historico_anual`.
Não apaga nenhuma linha de `parametros_vigentes`. Linhas fora do critério
(outro `alterado_por`, outro tipo de cálculo) só são REPORTADAS no log,
nunca alteradas.

Idempotente: depois da primeira execução a linha candidata já tem
`competencia_fim = competencia_inicio` e é ignorada; a linha 0.0 só é
inserida se nenhuma outra linha do mesmo parâmetro cobrir o mês.
"""
import json

PARAMETROS = ("custos_variaveis.outras_despesas", "custos_variaveis.investimentos")
TIPOS_CALCULO = ("COM_ALIQUOTA_CUMUL", "COM_ALIQUOTA")
ORIGEM_VAZAMENTO = "aprovacao"
ORIGEM_MIGRATION = "migration_0018"


def _mes_seguinte(mes_ref: str) -> str:
    ano, mes = int(mes_ref[:4]), int(mes_ref[5:7])
    return f"{ano + 1}-01" if mes == 12 else f"{ano}-{mes + 1:02d}"


def _valor(raw) -> float:
    try:
        return float(json.loads(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def apply(conn):
    candidatas = conn.execute(
        """
        SELECT p.id, p.unidade_id, p.parametro, p.valor,
               p.competencia_inicio, p.competencia_fim
        FROM parametros_vigentes p
        JOIN unidades u ON u.id = p.unidade_id
        WHERE p.parametro IN (?, ?)
          AND p.alterado_por = ?
          AND u.tipo_calculo IN (?, ?)
        ORDER BY p.unidade_id, p.parametro, p.competencia_inicio
        """,
        (*PARAMETROS, ORIGEM_VAZAMENTO, *TIPOS_CALCULO),
    ).fetchall()

    neutralizadas, ja_limitadas = [], []
    for r in candidatas:
        valor = _valor(r["valor"])
        if valor == 0.0:
            continue
        inicio, fim = r["competencia_inicio"], r["competencia_fim"]
        rotulo = f"{r['unidade_id']} {r['parametro']}={valor:g} ({inicio}→{fim or 'aberta'})"
        if fim is not None and fim <= inicio:
            ja_limitadas.append(rotulo)
            continue

        conn.execute(
            "UPDATE parametros_vigentes SET competencia_fim=? WHERE id=?",
            (inicio, r["id"]),
        )
        proximo = _mes_seguinte(inicio)
        coberto = conn.execute(
            """
            SELECT 1 FROM parametros_vigentes
            WHERE unidade_id=? AND parametro=? AND id!=?
              AND competencia_inicio <= ?
              AND (competencia_fim IS NULL OR competencia_fim >= ?)
            """,
            (r["unidade_id"], r["parametro"], r["id"], proximo, proximo),
        ).fetchone()
        if coberto is None:
            conn.execute(
                "INSERT INTO parametros_vigentes "
                "(unidade_id, parametro, valor, tipo_dado, descricao, "
                " competencia_inicio, competencia_fim, alterado_por) "
                "VALUES (?, ?, ?, 'moeda', "
                "'Rubrica mensal — sem valor herdado (neutraliza vigência legada de aprovação, a7ab174)', "
                "?, ?, ?)",
                (r["unidade_id"], r["parametro"], json.dumps(0.0), proximo, fim, ORIGEM_MIGRATION),
            )
        neutralizadas.append(rotulo)

    print(f"  neutralizar_vigencias_rubricas_mensais: {len(neutralizadas)} vigência(s) legada(s) "
          f"limitada(s) ao próprio mês {neutralizadas}; {len(ja_limitadas)} já limitada(s) {ja_limitadas}.")

    # Só relatório — nada além do critério acima é alterado.
    fora = conn.execute(
        """
        SELECT p.unidade_id, p.parametro, p.valor, p.competencia_inicio,
               p.competencia_fim, p.alterado_por, u.tipo_calculo
        FROM parametros_vigentes p
        LEFT JOIN unidades u ON u.id = p.unidade_id
        WHERE p.parametro IN (?, ?)
          AND NOT (p.alterado_por = ? AND u.tipo_calculo IN (?, ?))
        """,
        (*PARAMETROS, ORIGEM_VAZAMENTO, *TIPOS_CALCULO),
    ).fetchall()
    suspeitas = [
        f"{x['unidade_id']} {x['parametro']}={_valor(x['valor']):g} "
        f"({x['competencia_inicio']}→{x['competencia_fim'] or 'aberta'}, "
        f"por {x['alterado_por']}, tipo {x['tipo_calculo']})"
        for x in fora
        if _valor(x["valor"]) != 0.0 and x["alterado_por"] != ORIGEM_MIGRATION
    ]
    print(f"  neutralizar_vigencias_rubricas_mensais: {len(suspeitas)} linha(s) não-zero FORA do "
          f"critério (não alteradas, só reportadas): {suspeitas}")
