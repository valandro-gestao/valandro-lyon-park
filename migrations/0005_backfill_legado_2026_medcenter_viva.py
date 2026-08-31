"""
Backfill do histórico legado de janeiro a maio/2026 para Medcenter e Viva
Open Mall — as duas únicas unidades RESULTADO_SPLIT com lacuna em
`lancamentos` entre a última competência restaurada pela migração 0002
(2025-12) e a virada operacional para o Lyon Reports em 2026-06.

Regra temporal definida pelo cliente: até maio/2026 os valores vêm do
controle legado (planilha/relatório anterior ao sistema); a partir de
junho/2026 a fonte é o próprio Lyon Reports. Por isso esta migração cobre
estritamente 2026-01 a 2026-05 — nunca insere nem altera 2026-06 em diante.

Valores oficiais informados pelo cliente (Faturamento, Resultado da
Operação, Saldo a pagar). "Saldo a pagar" é gravado em `aluguel_calculado`
porque é exatamente esse o campo que o comparativo mensal e os cards do PDF
já leem como "Repasse" (ver app/reporter.py _comparativo_12m e
build_report_data) — mesmo conceito, não um valor novo.

Segue o mesmo formato de resultado_json usado pela migração 0002 para as
competências restauradas (aliquota_imposto/subtotal/ponto_equilibrio/custos
zerados ou vazios): o comparativo mensal do PDF só lê faturamento,
resultado, aluguel_calculado e extras.repasse_outros — os demais campos do
ResultadoUnidade não são usados por essa seção e não fazem parte do que
esta migração se propõe a fornecer. Não há dado oficial de custos/alíquota
para essas competências, então esses campos ficam no mesmo zero/vazio
"placeholder" já estabelecido pela 0002 — nunca inventados.

Idempotente, mas mais estrito que 0002/0004: se a competência já existir em
`lancamentos`, esta migração NUNCA sobrescreve. Em vez disso compara
faturamento/resultado/aluguel_calculado com o valor oficial e:
  - se coincidirem (diferença < 1 centavo): reporta como já presente, ok.
  - se divergirem: reporta a divergência (unidade, competência, campo,
    valor existente vs. oficial) e mantém o valor existente intocado —
    correção manual de divergência é decisão de produto, não desta
    migração.

Não toca em nenhuma outra unidade, competência ou tabela.
"""
import json

TOLERANCIA = 0.01  # diferença em R$ acima disso é reportada como divergência

# unidade_id -> mes_referencia -> (faturamento, resultado, saldo_a_pagar)
DADOS_OFICIAIS = {
    "viva_open_mall": {
        "2026-01": (162158.30, 72956.45, 29479.62),
        "2026-02": (161111.38, 71272.16, 28047.97),
        "2026-03": (224355.20, 124972.45, 73693.23),
        "2026-04": (208462.11, 110709.18, 61569.44),
        "2026-05": (261227.17, 156010.66, 100075.70),
    },
    "medcenter": {
        "2026-01": (470606.23, 301276.87, 145957.65),
        "2026-02": (411121.99, 244423.13, 103317.43),
        "2026-03": (552892.78, 369871.83, 197403.87),
        "2026-04": (521587.84, 288055.23, 136041.42),
        "2026-05": (563101.18, 348302.16, 181226.62),
    },
}


def _difere(a: float, b: float) -> bool:
    return abs((a or 0.0) - (b or 0.0)) >= TOLERANCIA


def apply(conn):
    inseridos = 0
    preservados_ok = 0
    divergencias = []

    for unidade_id, competencias in DADOS_OFICIAIS.items():
        for mes_referencia, (faturamento, resultado, saldo_a_pagar) in competencias.items():
            existente = conn.execute(
                "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
                (unidade_id, mes_referencia),
            ).fetchone()

            if existente is not None:
                dados_existentes = json.loads(existente["resultado_json"])
                campos = [
                    ("faturamento", dados_existentes.get("faturamento"), faturamento),
                    ("resultado", dados_existentes.get("resultado"), resultado),
                    ("aluguel_calculado", dados_existentes.get("aluguel_calculado"), saldo_a_pagar),
                ]
                divergiu = False
                for campo, valor_existente, valor_oficial in campos:
                    if _difere(valor_existente, valor_oficial):
                        divergiu = True
                        divergencias.append(
                            f"{unidade_id}/{mes_referencia}: {campo} existente={valor_existente!r} "
                            f"!= oficial={valor_oficial!r}"
                        )
                if not divergiu:
                    preservados_ok += 1
                continue  # nunca sobrescreve, com ou sem divergência

            resultado_dict = {
                "unidade_id": unidade_id,
                "mes_referencia": mes_referencia,
                "faturamento": faturamento,
                "aliquota_imposto": 0.0,
                "subtotal": 0.0,
                "ponto_equilibrio": 0.0,
                "custos": {},
                "resultado": resultado,
                "prejuizo_acumulado_entrada": 0.0,
                "prejuizo_acumulado_saida": 0.0,
                "aluguel_calculado": saldo_a_pagar,
                "splits": {},
                "extras": {},
                "observacoes": (
                    "Backfill do histórico legado (jan-mai/2026), anterior à virada "
                    "operacional para o Lyon Reports em 2026-06 (migration 0005)."
                ),
                "status": "aprovado",
            }
            conn.execute(
                "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    unidade_id,
                    mes_referencia,
                    faturamento,
                    json.dumps(resultado_dict, ensure_ascii=False),
                    "aprovado",
                ),
            )
            inseridos += 1

    print(f"  backfill_legado_2026_medcenter_viva: {inseridos} competência(s) inserida(s), "
          f"{preservados_ok} já existente(s) e conferida(s) sem divergência.")
    if divergencias:
        print(f"  ATENÇÃO — {len(divergencias)} divergência(s) encontrada(s) (valor existente preservado):")
        for d in divergencias:
            print(f"    - {d}")
