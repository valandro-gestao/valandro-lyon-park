"""
Registra as âncoras oficiais de saldo/prejuízo acumulado (v1.2.0 — cadeia
temporal de saldo acumulado, ver app.models.get_saldo_entrada e
CADEIA_SALDO_DESDE), confirmadas pela operadora como o saldo real até
maio/2026 — ou seja, a entrada correta do primeiro elo real da cadeia,
junho/2026.

Usa exclusivamente a infraestrutura já existente de `parametros_vigentes`
(parâmetro "saldo_acumulado_inicial", vigência a partir de 2026-06) —
nenhuma tabela nem coluna nova. Não toca `lancamentos` nem
`saldos_acumulados` (essa não é mais fonte de entrada de cálculo desde a
Etapa 2 — ver app.models.salvar_lancamento) e não recalcula nada — só
prepara o dado para o que acontece depois, pelo fluxo normal do sistema,
e o "depois" não é igual para todas as unidades:
  - Dom Pedro já tem junho E julho aprovados — ambos precisam ser
    reprocessados nessa ordem (reabrir/recalcular/reaprovar cada um),
    para que julho herde a entrada correta que sai do junho recalculado;
  - MW Tristeza, Viva Trindade e Pátio Manutenções têm só junho
    aprovado — junho precisa ser reprocessado, mas julho ainda não foi
    fechado: quando for, o cálculo já nasce correto, usando a saída do
    junho reprocessado, sem precisar de nenhum "reabrir".

Idempotente: para cada unidade, se já existir uma linha vigente para
"saldo_acumulado_inicial" a partir de 2026-06:
  - com o MESMO valor oficial -> não faz nada, reporta "já correta";
  - com um valor DIFERENTE -> NÃO sobrescreve silenciosamente; reporta
    como divergência e para a decisão manual — corrigir um valor real de
    negócio não deve acontecer silenciosamente dentro de uma migration
    de infraestrutura.
Se não existir nenhuma linha para a unidade, insere.
"""
import json

PARAMETRO = "saldo_acumulado_inicial"
COMPETENCIA = "2026-06"
TOLERANCIA = 0.005  # meio centavo — margem de arredondamento de float

ANCORAS_OFICIAIS = {
    "dom_pedro": -171239.32,
    "mw_tristeza": -632029.12,
    "viva_trindade": -149050.05,
    "patio_manutencao": 42223.85,
}


def apply(conn):
    inseridas, ja_corretas, divergentes = [], [], []

    for unidade_id, valor_oficial in ANCORAS_OFICIAIS.items():
        row = conn.execute(
            "SELECT valor FROM parametros_vigentes "
            "WHERE unidade_id=? AND parametro=? AND competencia_inicio=?",
            (unidade_id, PARAMETRO, COMPETENCIA),
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO parametros_vigentes "
                "(unidade_id, parametro, valor, tipo_dado, descricao, "
                " competencia_inicio, alterado_por) "
                "VALUES (?, ?, ?, 'moeda', "
                "'Saldo Acumulado Inicial (âncora da cadeia real, v1.2.0)', ?, 'migration_0008')",
                (unidade_id, PARAMETRO, json.dumps(valor_oficial), COMPETENCIA),
            )
            inseridas.append(unidade_id)
            continue

        try:
            valor_existente = float(json.loads(row["valor"]))
        except (json.JSONDecodeError, TypeError, ValueError):
            valor_existente = None

        if valor_existente is not None and abs(valor_existente - valor_oficial) < TOLERANCIA:
            ja_corretas.append(unidade_id)
        else:
            divergentes.append((unidade_id, row["valor"], valor_oficial))

    print(f"  ancoras_saldo_acumulado: {len(inseridas)} inserida(s) {inseridas}, "
          f"{len(ja_corretas)} já correta(s) {ja_corretas}, "
          f"{len(divergentes)} divergente(s).")
    if divergentes:
        print("  ATENÇÃO — valor(es) divergente(s) do oficial, NÃO sobrescrito(s) automaticamente:")
        for unidade_id, existente, oficial in divergentes:
            print(f"    {unidade_id}: banco tem {existente!r}, oficial é {oficial} — decidir manualmente.")
