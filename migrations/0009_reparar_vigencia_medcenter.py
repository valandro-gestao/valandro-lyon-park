"""
Repara a corrupção conhecida em produção de `medcenter.percentual_contratante`,
causada por um bug em `app.models.salvar_parametros` (já corrigido na
Etapa 1 desta subetapa): reaprovar uma competência anterior a uma
vigência futura já cadastrada corrompia essa vigência futura, gravando
`competencia_fim < competencia_inicio` nela e criando uma vigência nova
espúria que a "vencia" por ficar aberta.

Estado corrompido encontrado em produção:
    0.75: 2020-01 → 2026-06   (migration_0001, correta, intocada)
    0.75: 2026-06 → aberto    (alterado_por='aprovacao', ESPÚRIA — criada pelo bug)
    0.85: 2026-07 → 2026-05   (migration_0001, INVERTIDA pelo bug — fim < início)

Estado restaurado:
    0.75: 2020-01 → 2026-06   (inalterada)
    0.85: 2026-07 → aberto    (competencia_fim corrigido; era o valor certo, só a
                               data de fim estava corrompida)

Reconhece a assinatura ESPECÍFICA desta corrupção (não é um reparador
genérico de vigências):
  1. uma linha com `competencia_fim < competencia_inicio` — sinal
     inequívoco de inversão, nunca ocorre num estado saudável;
  2. opcionalmente, uma segunda linha `alterado_por='aprovacao'`, aberta,
     com `competencia_inicio` anterior à linha invertida e valor
     DIFERENTE do dela — a linha espúria que a sombreava.

Não toca em nenhum outro parâmetro nem unidade. Não toca `lancamentos`.
Não recalcula nada — só corrige `parametros_vigentes`. Julho de Medcenter
ainda não existe como lançamento (nunca foi aprovado) — depois deste
reparo, será calculado normalmente pelo fluxo do sistema, pela primeira
vez, já usando 85% corretamente. Não é um "reprocessamento": não há
nada para reabrir nesta unidade/competência.

Idempotente: se nenhuma linha com `competencia_fim < competencia_inicio`
for encontrada para este parâmetro (já corrigido, ou nunca corrompido),
não faz nada.
"""

UNIDADE = "medcenter"
PARAMETRO = "percentual_contratante"


def apply(conn):
    linhas = conn.execute(
        "SELECT id, valor, competencia_inicio, competencia_fim, alterado_por "
        "FROM parametros_vigentes WHERE unidade_id=? AND parametro=? "
        "ORDER BY competencia_inicio",
        (UNIDADE, PARAMETRO),
    ).fetchall()

    invertida = next(
        (l for l in linhas
         if l["competencia_fim"] is not None and l["competencia_fim"] < l["competencia_inicio"]),
        None,
    )

    if invertida is None:
        print("  reparar_vigencia_medcenter: nenhuma vigência invertida encontrada — nada a fazer.")
        return

    print(f"  reparar_vigencia_medcenter: vigência invertida encontrada "
          f"(id={invertida['id']}, inicio={invertida['competencia_inicio']}, "
          f"fim={invertida['competencia_fim']}, valor={invertida['valor']}).")

    conn.execute(
        "UPDATE parametros_vigentes SET competencia_fim=NULL WHERE id=?",
        (invertida["id"],),
    )
    print(f"    -> corrigida: competencia_fim removido "
          f"(volta a ficar aberta a partir de {invertida['competencia_inicio']}, valor {invertida['valor']}).")

    espuria = next(
        (l for l in linhas
         if l["id"] != invertida["id"]
         and l["alterado_por"] == "aprovacao"
         and l["competencia_fim"] is None
         and l["competencia_inicio"] < invertida["competencia_inicio"]
         and l["valor"] != invertida["valor"]),
        None,
    )

    if espuria is not None:
        print(f"    -> linha espúria encontrada (id={espuria['id']}, "
              f"inicio={espuria['competencia_inicio']}, valor={espuria['valor']}, "
              f"alterado_por={espuria['alterado_por']}) — removendo.")
        conn.execute("DELETE FROM parametros_vigentes WHERE id=?", (espuria["id"],))
    else:
        print("    -> nenhuma linha espúria correspondente encontrada (estado parcialmente "
              "diferente do esperado) — revisar manualmente se o resultado final não bater.")
