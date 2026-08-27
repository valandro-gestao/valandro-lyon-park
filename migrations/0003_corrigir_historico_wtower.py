"""
Corrige o histórico anual do W-Tower Caxias em `historico_anual`.

Bug identificado durante a investigação da sprint v1.1.2 (independente do
bootstrap do comparativo mensal — por isso é uma migração separada, não
misturada com a 0002): scripts/importar_historico.py mapeou a coluna errada
da planilha histórica como "Aluguel a pagar" para esta unidade — a coluna 7
("IPTU"), não a coluna 12 ("Aluguel a pagar (fdic)"). O valor de repasse
gravado em `historico_anual` para w_tower_caxias está, portanto, errado
desde a primeira importação (ex.: 2025 mostra R$23.769,91 quando o valor
correto, somando os 12 meses com a coluna certa, é R$103.461,50 — a
proporção correta de 80% do resultado, que é o percentual_aluguel
contratual desta unidade, só aparece com a coluna corrigida).

Corrige apenas a chave `aluguel_calculado` de cada ano já presente em
`historico_anual` para w_tower_caxias — faturamento, subtotal, resultado,
ponto_equilibrio e prejuizo_acumulado_entrada não são afetados por este bug
e permanecem como estão.

Os valores corretos abaixo foram recalculados a partir da mesma planilha
histórica, somando a coluna correta (M = "Aluguel a pagar (fdic)") mês a
mês, e conferidos contra o percentual contratual (80% do resultado, exceto
em meses de prejuízo, onde é 0) — não dependem do arquivo do bootstrap
mensal (migrations/data/historico_lancamentos.json), propositalmente, para
que esta correção não fique acoplada a ele.

Idempotente: só grava se o valor atual for diferente do valor correto.
"""
import json

UNIDADE = "w_tower_caxias"

# ano -> aluguel_calculado correto (soma dos 12 meses, coluna M da aba
# "W-Tower Caxias", verificada célula a célula contra o rótulo do cabeçalho)
ALUGUEL_CORRETO = {
    2021: 0.0,
    2022: 16564.00,
    2023: 66450.19,
    2024: 91095.94,
    2025: 103461.50,
    2026: 47923.04,  # parcial: só até a competência 2026-04 (a partir de
                      # 2026-05 o histórico já vem de `lancamentos`, não daqui)
}


def apply(conn):
    rows = conn.execute(
        "SELECT id, ano, dados_json FROM historico_anual WHERE unidade_id=?",
        (UNIDADE,),
    ).fetchall()

    corrigidos = 0
    for row in rows:
        ano = row["ano"]
        if ano not in ALUGUEL_CORRETO:
            continue
        dados = json.loads(row["dados_json"])
        correto = ALUGUEL_CORRETO[ano]
        if dados.get("aluguel_calculado") == correto:
            continue  # já está certo — nada a fazer
        dados["aluguel_calculado"] = correto
        conn.execute(
            "UPDATE historico_anual SET dados_json=? WHERE id=?",
            (json.dumps(dados, ensure_ascii=False), row["id"]),
        )
        corrigidos += 1

    print(f"  historico_wtower: {corrigidos} ano(s) corrigido(s) de {len(ALUGUEL_CORRETO)} conhecidos "
          f"({len(rows)} anos encontrados na base).")
