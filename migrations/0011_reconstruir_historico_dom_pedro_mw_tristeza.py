"""
Reconstrói a cadeia de prejuízo acumulado (`prejuizo_acumulado_entrada`,
`prejuizo_acumulado_saida`) e zera `aluguel_calculado` dos lançamentos
LEGADOS (`mes_referencia < 2026-06`) de Dom Pedro e MW Tristeza — as duas
únicas unidades, entre as investigadas, em que a reconstrução determinística
é possível sem nenhum dado adicional da operadora (Viva Trindade já está
correta — 0 meses com repasse no histórico legado; W Tower não tem âncora
oficial confirmada nem os valores mensais de `fundo_recomposicao` — fica de
fora, aguardando esses dois dados).

Causa do problema (já diagnosticado e confirmado pela operadora): o
histórico legado (migrations 0002/0004) foi extraído calculando
`aluguel_calculado = max(0, percentual × resultado do mês)` — MÊS A MÊS,
isoladamente, sem nunca somar ao prejuízo acumulado real da unidade (ver
scripts/extrair_historico_lancamentos.py). Isso produz repasse positivo em
qualquer mês individualmente lucrativo, mesmo com a unidade ainda
profundamente endividada — nenhum desses repasses aconteceu de verdade.

Âncoras oficiais (saldo confirmado pela operadora, saída de maio/2026 —
mesmas usadas na migration 0008):
    dom_pedro:    -171239.32
    mw_tristeza:  -632029.12

Reconstrução (por unidade, independente):
  1. Carrega TODOS os lançamentos com mes_referencia < 2026-06, em ordem
     cronológica — nunca inventa uma competência que não exista (ver ponto
     4 abaixo).
  2. Reconstrói em memória, andando RETROATIVAMENTE a partir da âncora
     (saída de maio/2026): para cada mês, do mais recente ao mais antigo,
     entrada[mês] = saída[mês] − resultado[mês]; a saída do mês anterior
     (o próximo a processar) é essa mesma entrada. "Resultado" aqui é o
     `resultado` já gravado no lançamento (não recalculado) — é o único
     valor confiável e imutável dessa reconstrução.
  3. Valida ANTES de gravar qualquer coisa:
       a. a saída de TODO mês da cadeia reconstruída é <= 0 (dentro da
          tolerância) — nenhum mês pode implicar que um repasse real teria
          ocorrido (resultado_com_prejuízo > 0), confirmando a premissa da
          operadora ("nenhum repasse real jamais ocorreu"). Se algum mês
          violar isso, a reconstrução desta unidade é abortada inteira —
          nada é gravado.
       b. a saída reconstruída do ÚLTIMO mês legado (2026-05) bate
          exatamente (tolerância de meio centavo) com a âncora oficial. Se
          o último mês legado não for exatamente "2026-05", ou não bater
          com a âncora, aborta — nada é gravado.
     Só quando as duas validações passam para uma unidade, os UPDATEs
     dessa unidade são executados.
  4. Dom Pedro tem uma lacuna real: não existe lançamento para 2021-03
     (nunca existiu, não é este código que a criou). A lacuna PERMANECE
     lacuna — esta migração nunca insere uma linha nova, só atualiza
     linhas já existentes. O "salto" de fevereiro/2021 direto para
     abril/2021 na cadeia reconstruída é uma consequência esperada e
     documentada dessa ausência de dado, não um bug: a saída de
     fevereiro/2021 é simplesmente a entrada de abril/2021, sem nenhum mês
     de referência entre os dois.

Campos alterados por lançamento reconstruído (dentro de `resultado_json`):
  - prejuizo_acumulado_entrada
  - prejuizo_acumulado_saida
  - aluguel_calculado (sempre 0.0 — nenhum repasse real no histórico legado)
Todos os demais campos (faturamento, resultado, custos, subtotal, extras,
observacoes, status etc.) são preservados exatamente como estavam. A coluna
`lancamentos.faturamento` (fora do JSON) também não é tocada.

Depois de corrigir `lancamentos`, reconstrói `historico_anual` — SÓ de
Dom Pedro e MW Tristeza — a partir dos lançamentos já corrigidos, com a
MESMA regra de agregação da migration 0006 (soma por ano de faturamento,
resultado e aluguel_calculado+repasse_outros, contagem de meses), para que
o cache reflita os valores corrigidos. Nenhuma outra unidade tem seu
`historico_anual` tocado.

Idempotente: cada execução recalcula a cadeia do zero e só grava as linhas
de `lancamentos` cujo valor atual difere do reconstruído (dentro da
tolerância) — uma segunda execução sobre dados já corrigidos não altera
nada em `lancamentos` (0 atualizações) e recalcula `historico_anual` para
o mesmo resultado (mesmo padrão de idempotência-por-reconstrução já usado
pela migration 0006 — upsert sempre, mas para o mesmo valor).

Não toca Viva Trindade, W Tower, nem nenhuma outra unidade. Não toca
`parametros_vigentes`, `saldos_acumulados`, nem `schema_migrations` (além
do próprio registro do runner). Não recalcula junho/2026 em diante — a
cadeia real (>= CADEIA_SALDO_DESDE) já ignora todo lançamento legado (ver
app.models.get_saldo_entrada) e não é afetada por esta migração.
"""
import json
from collections import defaultdict

CADEIA_SALDO_DESDE = "2026-06"
ULTIMO_MES_LEGADO_ESPERADO = "2026-05"
TOLERANCIA = 0.005  # meio centavo — margem de arredondamento de float

ANCORAS_MAIO_2026 = {
    "dom_pedro": -171239.32,
    "mw_tristeza": -632029.12,
}


def _reconstruir_cadeia_unidade(conn, unidade_id: str, ancora_maio: float) -> None:
    linhas = conn.execute(
        "SELECT id, mes_referencia, resultado_json FROM lancamentos "
        "WHERE unidade_id=? AND mes_referencia < ? ORDER BY mes_referencia",
        (unidade_id, CADEIA_SALDO_DESDE),
    ).fetchall()

    if not linhas:
        print(f"  {unidade_id}: nenhum lançamento legado (< {CADEIA_SALDO_DESDE}) encontrado — nada a fazer.")
        return

    registros = [(r["id"], r["mes_referencia"], json.loads(r["resultado_json"])) for r in linhas]

    ultimo_mes = registros[-1][1]
    if ultimo_mes != ULTIMO_MES_LEGADO_ESPERADO:
        print(f"  {unidade_id}: último mês legado é {ultimo_mes!r}, esperado "
              f"{ULTIMO_MES_LEGADO_ESPERADO!r} — divergência do desenho validado, abortando "
              f"reconstrução desta unidade (nada gravado).")
        return

    # ── 1/2: reconstrução em memória, retroativa a partir da âncora ────────
    reconstruido = {}  # id -> (entrada, saida)
    saida_atual = ancora_maio
    cadeia_consistente = True
    for id_, mes, dados in reversed(registros):
        if saida_atual > TOLERANCIA:
            cadeia_consistente = False
        resultado_mes = dados.get("resultado") or 0.0
        entrada = round(saida_atual - resultado_mes, 2)
        reconstruido[id_] = (entrada, round(saida_atual, 2))
        saida_atual = entrada

    # ── 3a: nenhum mês pode implicar repasse real ──────────────────────────
    if not cadeia_consistente:
        print(f"  {unidade_id}: a cadeia reconstruída implica repasse real em algum mês "
              f"(saída > 0 em algum ponto) — contradiz a premissa de que nenhum repasse "
              f"legado é real. Validação falhou, NADA foi gravado para esta unidade.")
        return

    # ── 3b: saída reconstruída de maio/2026 deve bater com a âncora oficial ─
    id_maio = registros[-1][0]
    saida_maio_reconstruida = reconstruido[id_maio][1]
    if abs(saida_maio_reconstruida - ancora_maio) >= TOLERANCIA:
        print(f"  {unidade_id}: saída reconstruída de {ULTIMO_MES_LEGADO_ESPERADO} "
              f"({saida_maio_reconstruida}) não bate com a âncora oficial ({ancora_maio}) — "
              f"validação falhou, NADA foi gravado para esta unidade.")
        return

    # ── 4: só agora grava — e só o que realmente muda ───────────────────────
    atualizados, ja_corretos = 0, 0
    for id_, mes, dados in registros:
        entrada, saida = reconstruido[id_]
        entrada_atual = dados.get("prejuizo_acumulado_entrada")
        saida_atual_db = dados.get("prejuizo_acumulado_saida")
        aluguel_atual = dados.get("aluguel_calculado")

        ja_bate = (
            entrada_atual is not None and abs(entrada_atual - entrada) < TOLERANCIA
            and saida_atual_db is not None and abs(saida_atual_db - saida) < TOLERANCIA
            and aluguel_atual is not None and abs(aluguel_atual - 0.0) < TOLERANCIA
        )
        if ja_bate:
            ja_corretos += 1
            continue

        novo = dict(dados)
        novo["prejuizo_acumulado_entrada"] = entrada
        novo["prejuizo_acumulado_saida"] = saida
        novo["aluguel_calculado"] = 0.0
        conn.execute(
            "UPDATE lancamentos SET resultado_json=? WHERE id=?",
            (json.dumps(novo, ensure_ascii=False), id_),
        )
        atualizados += 1

    print(f"  {unidade_id}: cadeia validada (saída de {ULTIMO_MES_LEGADO_ESPERADO} = "
          f"{ancora_maio}, nenhum mês com repasse implícito) — {atualizados} mês(es) "
          f"corrigido(s), {ja_corretos} já correto(s), de {len(registros)} legados.")


def _reconstruir_historico_anual_unidade(conn, unidade_id: str) -> None:
    """Mesma regra de agregação de migrations/0006_reconstruir_historico_anual.py,
    escopada a uma única unidade — nunca toca o historico_anual de outra."""
    rows = conn.execute(
        "SELECT mes_referencia, resultado_json FROM lancamentos "
        "WHERE unidade_id=? ORDER BY mes_referencia",
        (unidade_id,),
    ).fetchall()
    if not rows:
        return

    anos = defaultdict(lambda: {
        "faturamento": 0.0, "resultado": 0.0, "aluguel_calculado": 0.0,
        "quantidade_meses": 0,
    })
    for r in rows:
        dados = json.loads(r["resultado_json"])
        ano = int(r["mes_referencia"].split("-")[0])
        extras = dados.get("extras") or {}
        repasse_outros = extras.get("repasse_outros") or 0.0

        anos[ano]["faturamento"] += dados.get("faturamento") or 0.0
        anos[ano]["resultado"] += dados.get("resultado") or 0.0
        anos[ano]["aluguel_calculado"] += (dados.get("aluguel_calculado") or 0.0) + repasse_outros
        anos[ano]["quantidade_meses"] += 1

    for ano in sorted(anos):
        agregado = anos[ano]
        agregado["faturamento"] = round(agregado["faturamento"], 2)
        agregado["resultado"] = round(agregado["resultado"], 2)
        agregado["aluguel_calculado"] = round(agregado["aluguel_calculado"], 2)
        conn.execute("""
            INSERT INTO historico_anual (unidade_id, ano, dados_json)
            VALUES (?, ?, ?)
            ON CONFLICT(unidade_id, ano)
            DO UPDATE SET dados_json=excluded.dados_json
        """, (unidade_id, ano, json.dumps(agregado, ensure_ascii=False)))

    print(f"  historico_anual recalculado para {unidade_id}: {len(anos)} ano(s).")


def apply(conn):
    print("  reconstruir_historico_dom_pedro_mw_tristeza: reconstruindo cadeia de lançamentos...")
    for unidade_id, ancora in ANCORAS_MAIO_2026.items():
        _reconstruir_cadeia_unidade(conn, unidade_id, ancora)

    print("  reconstruir_historico_dom_pedro_mw_tristeza: recalculando historico_anual...")
    for unidade_id in ANCORAS_MAIO_2026:
        _reconstruir_historico_anual_unidade(conn, unidade_id)
