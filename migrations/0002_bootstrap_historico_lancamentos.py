"""
Bootstrap do histórico mensal anterior ao Lyon Reports.

Lê migrations/data/historico_lancamentos.json (gerado uma única vez por
scripts/extrair_historico_lancamentos.py a partir da planilha histórica
original) e insere em `lancamentos` apenas as competências que ainda não
existem — nunca sobrescreve um lançamento já presente (real ou de uma
execução anterior desta mesma migração).

Não toca em saldos_acumulados: os saldos iniciais de unidades com prejuízo
acumulado (MW Tristeza, Dom Pedro, Viva Trindade etc.) já foram definidos
deliberadamente como um retrato do momento de lançamento da ferramenta
(app.engine.seed_saldos_iniciais) — recalcular isso a partir do histórico
mensal aqui duplicaria/conflitaria com essa decisão já tomada. O comparativo
mensal do PDF usa exclusivamente `lancamentos` (decisão arquitetural da
sprint v1.1.2) — este é o único dado que esta migração precisa fornecer.

Cada registro histórico é gravado com status "aprovado" (competência já
encerrada no passado) e com aliquota_imposto/subtotal/ponto_equilibrio/custos
zerados — o comparativo mensal só lê faturamento, resultado, aluguel_calculado
e extras.repasse_outros (ver app/reporter.py _comparativo_12m); os demais
campos do ResultadoUnidade não são usados por essa seção do PDF e não fazem
parte do que esta migração se propõe a restaurar.

Idempotente por construção: antes de cada inserção, verifica quais
(unidade_id, mes_referencia) já existem e insere somente os que faltam —
correr de novo (mesmo direto, sem passar pelo runner/schema_migrations) não
duplica nem sobrescreve nada, e o UNIQUE(unidade_id, mes_referencia) da
tabela é a rede de segurança final.
"""
import json
from pathlib import Path

DADOS_PATH = Path(__file__).parent / "data" / "historico_lancamentos.json"


def apply(conn):
    if not DADOS_PATH.exists():
        raise RuntimeError(
            f"Arquivo de dados não encontrado: {DADOS_PATH}. "
            "Gere-o com scripts/extrair_historico_lancamentos.py antes de aplicar esta migração."
        )

    with open(DADOS_PATH, encoding="utf-8") as f:
        historico = json.load(f)

    existentes = {
        (row["unidade_id"], row["mes_referencia"])
        for row in conn.execute("SELECT unidade_id, mes_referencia FROM lancamentos")
    }

    inseridos = 0
    ignorados_ja_existentes = 0

    for unidade_id, registros in historico.items():
        for r in registros:
            chave = (unidade_id, r["mes_referencia"])
            if chave in existentes:
                ignorados_ja_existentes += 1
                continue

            resultado_dict = {
                "unidade_id": unidade_id,
                "mes_referencia": r["mes_referencia"],
                "faturamento": r["faturamento"],
                "aliquota_imposto": 0.0,
                "subtotal": 0.0,
                "ponto_equilibrio": 0.0,
                "custos": {},
                "resultado": r.get("resultado") if r.get("resultado") is not None else 0.0,
                "prejuizo_acumulado_entrada": 0.0,
                "prejuizo_acumulado_saida": 0.0,
                "aluguel_calculado": r.get("aluguel_calculado", 0.0),
                "splits": {},
                "extras": r.get("extras") or {},
                "observacoes": "Restaurado do histórico anterior ao Lyon Reports (migration 0002).",
                "status": "aprovado",
            }

            conn.execute(
                "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    unidade_id,
                    r["mes_referencia"],
                    r["faturamento"],
                    json.dumps(resultado_dict, ensure_ascii=False),
                    "aprovado",
                ),
            )
            existentes.add(chave)
            inseridos += 1

    print(f"  historico_lancamentos: {inseridos} competências inseridas, "
          f"{ignorados_ja_existentes} já existentes (ignoradas).")
