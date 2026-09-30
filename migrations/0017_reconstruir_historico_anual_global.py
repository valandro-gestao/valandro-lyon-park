"""
Reconstrói `historico_anual` para TODAS as unidades, a partir de
`lancamentos` — correção emergencial de dados (homologação FIERGS,
set/2026), não uma mudança de arquitetura.

Causa raiz confirmada em produção: `historico_anual` é populado
INTEIRAMENTE pela migration 0006 (reconstrução por agregação de
`lancamentos`) — migrations rodam uma única vez (`migrations.runner`
nunca reaplica um id já registrado em `schema_migrations`) e não são
reexecutadas automaticamente a cada deploy (`main.py` só chama
`init_db()` na subida do app; migrations são aplicadas manualmente via
`scripts/migrate.py`). A migration 0006 foi aplicada em 31/08/2026. Todo
lançamento aprovado DEPOIS dessa data (ex.: FIERGS Jul/Ago/Set de 2026)
entrou corretamente em `lancamentos` — por isso o Comparativo do PDF
(`app.reporter._comparativo_12m`, que lê `lancamentos` diretamente) já os
mostrava — mas nunca foi refletido em `historico_anual`, porque nenhum
outro caminho do sistema escreve nessa tabela (`app.reporter.
_historico_anual` só ajusta em memória a ÚNICA competência do próprio PDF
sendo gerado, e só quando ela ainda não está persistida — nunca as demais
que ficaram para trás). Resultado: FIERGS/2026 ficou congelado em
Mai+Jun (quantidade_meses=2) enquanto `lancamentos` já tinha 5 meses.
Esta mesma lacuna pode ter atingido qualquer outra unidade com aprovações
posteriores a 31/08/2026 — por isso a reconstrução aqui é GLOBAL (todas as
unidades, todos os anos), não escopada a uma unidade específica (ver
0011, que fez essa reconstrução escopada para um caso anterior e
diferente — cadeia de prejuízo acumulado, não este problema).

Mesma regra de agregação já consolidada e validada por 0006/0011 — não
recalcula nem reinterpreta nada, só reaplica a mesma fórmula sobre o
estado atual de `lancamentos`:
  Faturamento = soma(resultado_json.faturamento)
  Resultado   = soma(resultado_json.resultado)
  Repasse     = soma(resultado_json.aluguel_calculado
                      + resultado_json.extras.repasse_outros)
  quantidade_meses = contagem de competências distintas agregadas

Sem nenhum id de unidade hardcoded — itera todas as unidades presentes em
`lancamentos`, dinamicamente, exatamente como 0006 já fazia (0011 é quem
introduziu o escopo fixo por unidade, para o problema específico que
resolvia; aqui voltamos ao escopo global de 0006, propositalmente).

Idempotente por reconstrução (mesmo padrão de 0006/0011): sempre
recalcula e faz UPSERT do par (unidade_id, ano) a partir de `lancamentos`
— rodar de novo sobre lançamentos inalterados produz exatamente o mesmo
resultado, portanto o estado final não muda. Nunca faz DELETE: um
(unidade_id, ano) sem nenhum lançamento correspondente (ex.: Pátio —
Manutenções, que não tem linha própria em `lancamentos`) não é tocado.

NUNCA modifica `lancamentos`, `parametros_vigentes`, `saldos_acumulados`,
`rascunhos_unidade` nem `schema_migrations` (além do próprio registro
feito pelo runner) — só `historico_anual`. Não altera nenhuma fórmula de
cálculo do sistema (app.calculators/app.engine intocados).

Esta migration é a correção EMERGENCIAL dos dados já existentes — a causa
arquitetural (historico_anual como cache que pode voltar a ficar
desatualizado após a próxima aprovação/reabertura de qualquer unidade)
está registrada como débito técnico em docs/ROADMAP.md, para decisão
futura entre manter o cache sincronizado automaticamente ou eliminar essa
persistência e calcular o histórico anual diretamente de `lancamentos`.
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
        # dict por mes_referencia: 1 linha por competência na agregação, mesma
        # segunda camada de defesa já usada em 0006 (o UNIQUE(unidade_id,
        # mes_referencia) de `lancamentos` já impede duplicidade na origem).
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

    print(f"  reconstruir_historico_anual_global: {total_pares} par(es) (unidade_id, ano) "
          f"gravado(s)/atualizado(s) em {len(por_unidade)} unidade(s) com lançamentos.")
    for linha in resumo:
        print(f"    {linha}")
