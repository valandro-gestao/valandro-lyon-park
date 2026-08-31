"""
Reconstrói `historico_anual` inteiramente a partir de `lancamentos`.

Contexto: `historico_anual` estava vazia em produção (0 linhas) — a
importação original (scripts/importar_historico.py, a partir da planilha
histórica, com índices de coluna fixos e sem verificação de cabeçalho)
nunca chegou a rodar contra o banco operacional. O conteúdo do
`historico_anual` do seed.db tem erros já identificados e documentados:
  - Medcenter: Repasse usava "Resultado Operador" (25%) em vez de "Saldo a
    pagar" (o conceito de Repasse usado por todo o resto do sistema).
  - Viva Open Mall: Resultado e Repasse nunca foram extraídos (None).
  - W-Tower Caxias: Repasse usava a coluna errada da planilha (bug corrigido
    à parte pela migration 0003, mas só quando havia linha para corrigir —
    com a tabela vazia em produção, 0003 sempre encontrou 0 anos).
  - W-Tower Caxias também tem um segundo bug, não corrigido antes, no
    próprio Resultado (2021: +193.930,00 no importador antigo vs. -89.480,14
    somando os lançamentos mensais, que batem individualmente com o
    histórico restaurado pela migration 0002).

Por isso esta migração não lê o `historico_anual` antigo, não roda
scripts/importar_historico.py e não usa nenhum índice fixo de planilha.
`lancamentos` passa a ser a única fonte: cada linha já foi restaurada (2021
a mai/2026, migrations 0002/0004/0005 — extração com verificação de
cabeçalho contra a planilha original) ou é um lançamento real do próprio
Lyon Reports (jun/2026 em diante). `historico_anual` deixa de ser uma
segunda fonte de verdade e passa a ser um cache/agregado derivado de
`lancamentos`, recalculado por esta migração.

Regra temporal (decisão de produto, não estrutural — não há campo que
distinga lançamento "legado" de "operacional" em `lancamentos`; a única
diferença é a própria `mes_referencia` e já está embutida nos dados): até
2026-05 inclusive é histórico legado (migrations 0002/0004/0005), a partir
de 2026-06 inclusive é lançamento real do Lyon Reports. Esta migração não
filtra por `status` — um lançamento real a partir de 2026-06 conta mesmo
que ainda não esteja "aprovado" (decisão explícita do cliente). O
UNIQUE(unidade_id, mes_referencia) de `lancamentos` já impede qualquer
duplicidade na origem, então a agregação abaixo nunca conta a mesma
competência duas vezes.

Agregação por (unidade_id, ano), a partir de TODOS os lançamentos da
unidade, sem exigir 12 meses:
  Faturamento = soma(resultado_json.faturamento)
  Resultado   = soma(resultado_json.resultado)
  Repasse     = soma(resultado_json.aluguel_calculado
                      + resultado_json.extras.repasse_outros)
  (repasse_outros vira 0.0 quando ausente — relevante sobretudo para Pátio
  REAL e Pátio MAIOJAMA, que têm meses com receita extra de mídia)

`quantidade_meses` (contagem de competências distintas efetivamente
agregadas, não a diferença entre a primeira e a última) é gravada dentro do
próprio dados_json — evita nova coluna física em `historico_anual` só para
essa informação, e permite ao reporter.py montar o rótulo "2024 (10 meses)"
sem precisar consultar `lancamentos` de novo (ver app/reporter.py
_formatar_ano_label). Um ano com as 12 competências não carrega sufixo.

Idempotente por reconstrução, não por "pular se já existe": esta migração
SEMPRE recalcula e substitui (upsert) o par (unidade_id, ano) para todo par
que consiga formar a partir de `lancamentos` — é assim que ela corrige os
erros do `historico_anual` antigo. Rodar de novo sobre lançamentos
inalterados produz exatamente o mesmo resultado (mesma soma, mesmo
`quantidade_meses`), portanto o estado final não muda. Nunca faz DELETE:
um (unidade_id, ano) que não tenha nenhum lançamento correspondente (ex.:
Pátio Manutenção, que não tem nenhuma linha em `lancamentos`) simplesmente
não é tocado — se já existir um valor legado antigo para esse par, ele
permanece como está, intocado, não apagado.

Não toca em `lancamentos`, `parametros_vigentes`, `saldos_acumulados`,
`rascunhos_unidade` nem `schema_migrations` (além do próprio registro feito
pelo runner) — apenas `historico_anual`.
"""
import json
from collections import defaultdict


def apply(conn):
    rows = conn.execute(
        "SELECT unidade_id, mes_referencia, resultado_json FROM lancamentos "
        "ORDER BY unidade_id, mes_referencia"
    ).fetchall()

    por_unidade = defaultdict(dict)  # unidade_id -> {mes_referencia: resultado_json}
    for r in rows:
        # dict por mes_referencia: garante 1 linha por competência na agregação
        # mesmo que a consulta acima trouxesse duplicidade — o
        # UNIQUE(unidade_id, mes_referencia) de `lancamentos` já impede isso
        # na prática, esta é só uma segunda camada de defesa.
        por_unidade[r["unidade_id"]][r["mes_referencia"]] = r["resultado_json"]

    total_pares = 0
    resumo = []

    for unidade_id in sorted(por_unidade):
        competencias = por_unidade[unidade_id]

        anos = defaultdict(lambda: {
            "faturamento": 0.0, "resultado": 0.0, "aluguel_calculado": 0.0,
            "quantidade_meses": 0,
        })
        for mes_referencia, resultado_json in competencias.items():
            dados = json.loads(resultado_json)
            ano = int(mes_referencia.split("-")[0])
            extras = dados.get("extras") or {}
            repasse_outros = extras.get("repasse_outros") or 0.0

            anos[ano]["faturamento"] += dados.get("faturamento") or 0.0
            anos[ano]["resultado"] += dados.get("resultado") or 0.0
            anos[ano]["aluguel_calculado"] += (dados.get("aluguel_calculado") or 0.0) + repasse_outros
            anos[ano]["quantidade_meses"] += 1

        anos_ordenados = sorted(anos.keys())
        for ano in anos_ordenados:
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
            total_pares += 1

        detalhe_anos = ", ".join(
            f"{ano} ({anos[ano]['quantidade_meses']}m)" for ano in anos_ordenados
        )
        resumo.append(f"{unidade_id}: {len(anos_ordenados)} ano(s) ({detalhe_anos})")

    print(f"  reconstruir_historico_anual: {total_pares} par(es) (unidade_id, ano) "
          f"gravado(s)/atualizado(s) em {len(por_unidade)} unidade(s) com lançamentos.")
    for linha in resumo:
        print(f"    {linha}")
