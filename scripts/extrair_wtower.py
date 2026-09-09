"""
Extrai o histórico de W Tower Caxias da planilha histórica original
("Lyon - Dados para Relatórios.xlsx", aba "W-Tower Caxias") e grava em
migrations/data/historico_wtower.json — o único formato que a migração de
correção desta unidade lê. Executado uma única vez, localmente; não faz
parte do runtime da aplicação.

Layout da aba (bloco-resumo, colunas Q:BV, rótulos fixos na coluna P,
linhas 3-17): Faturamento / Alíquota / Subtotal / PE / Condomínio / IPTU /
Energia / PE Total / Resultado / Prejuízo Acumulado / (branco) / Aluguel a
Pagar / Recomposição Fundo / Saldo a Pagar. Os meses ficam em COLUNAS,
agrupados em blocos de 12, cada bloco seguido por uma coluna "totalizadora"
(linha 3 = inteiro puro, ex. 2022) — NUNCA uma competência.

Resolução temporal (a parte não-trivial, e a causa de uma leitura anterior
incorreta): o rótulo escrito na coluna totalizadora NÃO é o ano do bloco
que a precede visualmente — é o ano do bloco que ela FECHA, isto é, do
bloco de 12 meses IMEDIATAMENTE ANTERIOR a ela. Confirmado por igualdade
exata, célula a célula: valor da coluna totalizadora (linha 4, Faturamento)
== soma das 12 colunas mensais que a antecedem — nunca das 12 que a
sucedem. Esse é o sentido de "a coluna totalizadora de cada ano vem depois
das colunas mensais" (confirmação da operadora): o totalizador de um ano
está posicionado DEPOIS dos seus 12 meses, não antes. Uma leitura ingênua
(rótulo da coluna totalizadora = ano do bloco que vem a seguir) desloca
toda a série em -1 ano — foi exatamente o erro da investigação anterior
(achava prejuízo zerando em janeiro/2023 em vez de janeiro/2024).

A coluna totalizadora inicial (Q, rotulada "2021") não tem bloco de 12
meses antes dela nesta aba — é um total avulso, carregado de fora do
bloco-resumo visível aqui. Por isso 2021 nunca é reconstruído por este
script (não há suporte direto na planilha) — a competência mais antiga
extraída é 2022-01. O bloco final (Jan-Maio, 5 meses, sem totalizador
depois porque o ano ainda não fechou) tem seu ano confirmado por outra via,
independente: datas reais (datetime) na linha 2, só presentes nessas 5
últimas colunas — confirmam 2026-01 a 2026-05.

Convenção de sinal do Fundo de Recomposição: a planilha grava a linha
"Recomposição Fundo" como valor NEGATIVO (dedução already-applied, ex.
-717.38). O sistema (app.calculators.cumulativo) grava
extras["fundo_recomposicao"] como valor POSITIVO (717.38) e calcula
extras["saldo_a_pagar"] = aluguel_calculado - fundo_recomposicao. Este
script já converte para a convenção do sistema (abs()) — a migração nunca
precisa inverter sinal.

Convenção do "Prejuízo Acumulado" no mês de virada (a única linha da
planilha que precisa de um ajuste, não uma leitura direta): no mês em que
o resultado supera o prejuízo restante, a célula da planilha mostra o
EXCEDENTE disponível (positivo, ex. +7340.64 em jan/2024) — não o saldo
acumulado de saída. O sistema sempre zera prejuizo_acumulado_saida nesse
caso (ver app.calculators.cumulativo: resultado_com_prejuizo > 0 =>
prejuizo_saida = 0.0). Este script aplica a mesma regra: sempre que a
célula de Prejuízo Acumulado é positiva, grava saida = 0.0 no lugar do
valor positivo da planilha — em qualquer outro caso (negativo ou já 0),
grava o valor da planilha sem alteração. Essa é a ÚNICA transformação
aplicada a um valor oficial nesta extração; todo o resto é lido e gravado
como está.

Este script se RECUSA a gravar o JSON se qualquer validação abaixo falhar:
  1. o layout de blocos (totalizador a cada 13 colunas) é o esperado, sem
     coluna extra/faltante;
  2. o bloco final (sem totalizador depois) tem datas reais na linha 2
     confirmando 2026, meses Jan-Maio, em ordem;
  3. cada totalizador valida contra a soma do Faturamento do bloco que o
     antecede (dentro de meio centavo);
  4. a série final (após filtrar só 2022-01..2026-05) não tem duplicata,
     lacuna, e está em ordem cronológica;
  5. entrada[mês] + resultado[mês] (cadeia reconstruída, andando para
     frente a partir de uma âncora derivada em 2022-01) bate com a saída
     revista (0.0 quando positiva, valor da planilha caso contrário) em
     TODOS os meses — mesma regra exata do calculator ao vivo
     (app.calculators.cumulativo: disponivel>0 => saida=0.0);
  6. o mês de virada (disponivel>0 pela primeira vez) é exatamente 2024-01
     — fato confirmado pela operadora;
  7. o Fundo de Recomposição é não-zero exatamente nos 10 meses
     2024-06..2025-03 — fato confirmado pela operadora — e zero em todos
     os outros meses do intervalo extraído;
  8. em todo mês com Fundo, Aluguel a Pagar + Fundo (negativo) == Saldo a
     Pagar da planilha (dentro de meio centavo) — confirma a regra
     "repasse bruto - fundo = repasse líquido" também na fonte.

Uso:
  .venv/bin/python scripts/extrair_wtower.py
"""
import datetime
import json
import os
import sys

import openpyxl

EXCEL = os.path.expanduser("~/Downloads/Lyon - Dados para Relatórios.xlsx")
SAIDA = os.path.join(os.path.dirname(__file__), "..", "migrations", "data", "historico_wtower.json")

ABA = "W-Tower Caxias"
UNIDADE_ID = "w_tower_caxias"

LINHA_MES = 3
LINHA_DATA = 2
LINHA_FATURAMENTO = 4
LINHA_RESULTADO = 12
LINHA_PREJUIZO = 13
LINHA_ALUGUEL = 15
LINHA_FUNDO = 16
LINHA_SALDO_PAGAR = 17

COL_INICIO = openpyxl.utils.column_index_from_string("Q")
COL_FIM = openpyxl.utils.column_index_from_string("BV")

MES_INICIO_ESCOPO = "2022-01"
MES_FIM_ESCOPO = "2026-05"
MES_VIRADA_ESPERADO = "2024-01"
FUNDO_MESES_ESPERADOS = [
    "2024-06", "2024-07", "2024-08", "2024-09", "2024-10", "2024-11", "2024-12",
    "2025-01", "2025-02", "2025-03",
]
TOLERANCIA = 0.005  # meio centavo

MESES_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def main():
    if not os.path.exists(EXCEL):
        sys.exit(f"Planilha não encontrada em {EXCEL}. Este script só roda localmente, uma vez.")

    wb = openpyxl.load_workbook(EXCEL, data_only=True)
    if ABA not in wb.sheetnames:
        sys.exit(f"Aba {ABA!r} não encontrada na planilha. Abas disponíveis: {wb.sheetnames}")
    ws = wb[ABA]

    erros = []

    # ── 1ª passada: classifica cada coluna como 'mes' ou 'totalizador' ──────
    tokens = []  # (col, kind, value)
    for c in range(COL_INICIO, COL_FIM + 1):
        v = ws.cell(row=LINHA_MES, column=c).value
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            tokens.append((c, "totalizador", int(v)))
        elif v in MESES_PT:
            tokens.append((c, "mes", v))
        else:
            erros.append(f"coluna {c}: valor inesperado na linha de rótulo ({v!r}) — nem mês nem totalizador")

    if erros:
        _abortar(erros)

    # ── 2ª passada: agrupa meses consecutivos em blocos de 12 (ou parcial no fim) ──
    blocos = []  # cada item: {"cols": [...], "totalizador_col": int|None}
    atual = []
    for c, kind, v in tokens:
        if kind == "mes":
            atual.append(c)
        else:  # totalizador — fecha o bloco corrente (se houver)
            if atual:
                blocos.append({"cols": atual, "totalizador_col": c})
                atual = []
            # totalizador sem bloco antes (ex.: Q inicial) — sem competência associada, ignorado
    if atual:
        blocos.append({"cols": atual, "totalizador_col": None})

    # ── 3ª passada: determina o ANO verdadeiro de cada bloco ────────────────
    dados_por_mes = {}  # mes_referencia -> dict de valores brutos
    for bloco in blocos:
        cols = bloco["cols"]
        tot_col = bloco["totalizador_col"]

        if tot_col is not None:
            label = ws.cell(row=LINHA_MES, column=tot_col).value
            soma_bloco = sum(_num(ws.cell(row=LINHA_FATURAMENTO, column=c).value) for c in cols)
            valor_totalizador = _num(ws.cell(row=LINHA_FATURAMENTO, column=tot_col).value)
            if abs(soma_bloco - valor_totalizador) > TOLERANCIA:
                erros.append(
                    f"totalizador na coluna {tot_col} (rótulo {label}): soma do Faturamento do bloco "
                    f"que o antecede ({round(soma_bloco,2)}) não bate com o valor do totalizador "
                    f"({round(valor_totalizador,2)}) — layout inesperado, abortando."
                )
                continue
            ano_bloco = int(label)
        else:
            # Bloco final, sem totalizador depois — ano vem de datas reais na linha 2.
            datas = [ws.cell(row=LINHA_DATA, column=c).value for c in cols]
            if not all(isinstance(d, datetime.datetime) for d in datas):
                erros.append(
                    "bloco final (sem totalizador depois) não tem datas reais (datetime) na "
                    "linha 2 em todas as suas colunas — não há como confirmar o ano sem inferência."
                )
                continue
            anos = {d.year for d in datas}
            if len(anos) != 1:
                erros.append(f"bloco final tem datas de anos diferentes na linha 2: {sorted(anos)}")
                continue
            meses_datas = [d.month for d in datas]
            if meses_datas != list(range(1, len(cols) + 1)):
                erros.append(f"bloco final: meses das datas reais não são 1..N em sequência: {meses_datas}")
                continue
            ano_bloco = anos.pop()

        if len(cols) != 12 and tot_col is not None:
            erros.append(f"bloco terminado no totalizador da coluna {tot_col} tem {len(cols)} meses, esperado 12.")
            continue

        for idx, c in enumerate(cols):
            mes_nome = ws.cell(row=LINHA_MES, column=c).value
            mes_idx = MESES_PT.index(mes_nome) + 1
            if tot_col is None:
                mes_idx = idx + 1  # já confirmado == mês da data real acima
            mes_ref = f"{ano_bloco:04d}-{mes_idx:02d}"

            if mes_ref in dados_por_mes:
                erros.append(f"competência {mes_ref} produzida por mais de uma coluna (coluna {c} duplicada)")
                continue

            dados_por_mes[mes_ref] = {
                "mes_referencia": mes_ref,
                "faturamento": _num(ws.cell(row=LINHA_FATURAMENTO, column=c).value),
                "resultado": _num(ws.cell(row=LINHA_RESULTADO, column=c).value),
                "prejuizo_planilha": _num(ws.cell(row=LINHA_PREJUIZO, column=c).value),
                "aluguel_calculado": _num(ws.cell(row=LINHA_ALUGUEL, column=c).value),
                "fundo_planilha": _num(ws.cell(row=LINHA_FUNDO, column=c).value),
                "saldo_pagar_planilha": _num(ws.cell(row=LINHA_SALDO_PAGAR, column=c).value),
            }

    if erros:
        _abortar(erros)

    # ── filtra só o escopo desta correção (2022-01..2026-05) ────────────────
    competencias = sorted(m for m in dados_por_mes if MES_INICIO_ESCOPO <= m <= MES_FIM_ESCOPO)

    if not competencias:
        _abortar(["nenhuma competência dentro do escopo 2022-01..2026-05 foi extraída"])

    if competencias[0] != MES_INICIO_ESCOPO or competencias[-1] != MES_FIM_ESCOPO:
        erros.append(
            f"intervalo extraído é {competencias[0]}..{competencias[-1]}, "
            f"esperado {MES_INICIO_ESCOPO}..{MES_FIM_ESCOPO}"
        )

    def _proximo_mes(m):
        ano, mes = int(m[:4]), int(m[5:7])
        return f"{ano+1:04d}-01" if mes == 12 else f"{ano:04d}-{mes+1:02d}"

    for i in range(len(competencias) - 1):
        if _proximo_mes(competencias[i]) != competencias[i + 1]:
            erros.append(f"lacuna na série entre {competencias[i]} e {competencias[i+1]}")

    if erros:
        _abortar(erros)

    # ── cadeia de prejuízo: valida a regra exata do calculator ao vivo ──────
    # disponivel = entrada + resultado; saida = 0.0 se disponivel>0, senão disponivel.
    # Âncora: entrada do primeiro mês do escopo = saida_planilha - resultado (mesmo
    # mês) — só possível porque o primeiro mês do escopo (2022-01) já está em
    # prejuízo (disponivel<0), então a saida_planilha ali já É o valor final, sem
    # ajuste de virada.
    primeiro = dados_por_mes[competencias[0]]
    if primeiro["prejuizo_planilha"] > 0:
        erros.append(f"{competencias[0]}: mês inicial do escopo já mostra prejuízo positivo — "
                      "não é possível âncorar a cadeia sem o mês anterior. Abortando.")
        _abortar(erros)

    # Carrega a cadeia em PRECISÃO TOTAL (sem arredondar a cada passo) — a
    # própria planilha soma o Resultado internamente em precisão total,
    # célula a célula já vindo com várias casas decimais (ex.
    # -2222.4544250000035); arredondar a cada mês antes de somar o próximo
    # introduz um desvio de centavo em cascata que NÃO é erro de dado (ver
    # mesmo cuidado em scripts/extrair_patio_manutencao.py). Só o valor
    # final gravado no JSON é arredondado a 2 casas.
    entrada_atual = primeiro["prejuizo_planilha"] - primeiro["resultado"]
    mes_virada = None
    for m in competencias:
        r = dados_por_mes[m]
        disponivel = entrada_atual + r["resultado"]
        saida_esperada = 0.0 if disponivel > 0 else disponivel
        saida_planilha_ajustada = 0.0 if r["prejuizo_planilha"] > 0 else r["prejuizo_planilha"]

        if abs(saida_esperada - saida_planilha_ajustada) > TOLERANCIA:
            erros.append(
                f"{m}: cadeia reconstruída (entrada {round(entrada_atual,2)} + resultado "
                f"{round(r['resultado'],2)} = disponível {round(disponivel,2)} => saída esperada "
                f"{round(saida_esperada,2)}) não bate com a saída da planilha ajustada "
                f"({round(saida_planilha_ajustada,2)}, bruto planilha {round(r['prejuizo_planilha'],2)})"
            )

        if disponivel > 0 and mes_virada is None:
            mes_virada = m

        r["prejuizo_acumulado_entrada"] = entrada_atual
        r["prejuizo_acumulado_saida"] = saida_esperada
        entrada_atual = saida_esperada

    if mes_virada != MES_VIRADA_ESPERADO:
        erros.append(f"mês de virada (prejuízo chega a zero) é {mes_virada!r}, esperado {MES_VIRADA_ESPERADO!r}")

    # ── Fundo de Recomposição: exatamente os 10 meses esperados ─────────────
    fundo_encontrados = [m for m in competencias if abs(dados_por_mes[m]["fundo_planilha"]) > TOLERANCIA]
    if fundo_encontrados != FUNDO_MESES_ESPERADOS:
        erros.append(
            f"meses com Fundo de Recomposição não-zero: {fundo_encontrados}, "
            f"esperado exatamente: {FUNDO_MESES_ESPERADOS}"
        )

    for m in FUNDO_MESES_ESPERADOS:
        if m not in dados_por_mes:
            continue
        r = dados_por_mes[m]
        aluguel = r["aluguel_calculado"]
        fundo = r["fundo_planilha"]  # negativo, na planilha
        saldo_esperado = round(aluguel + fundo, 2)
        if abs(saldo_esperado - round(r["saldo_pagar_planilha"], 2)) > TOLERANCIA:
            erros.append(
                f"{m}: Aluguel a Pagar ({aluguel}) + Fundo ({fundo}) = {saldo_esperado}, "
                f"não bate com Saldo a Pagar da planilha ({round(r['saldo_pagar_planilha'],2)})"
            )

    if erros:
        _abortar(erros)

    # ── monta os registros finais ────────────────────────────────────────────
    registros = []
    for m in competencias:
        r = dados_por_mes[m]
        registro = {
            "mes_referencia": m,
            "faturamento": round(r["faturamento"], 2),
            "resultado": round(r["resultado"], 2),
            "prejuizo_acumulado_entrada": round(r["prejuizo_acumulado_entrada"], 2),
            "prejuizo_acumulado_saida": round(r["prejuizo_acumulado_saida"], 2),
            "aluguel_calculado": round(r["aluguel_calculado"], 2),
        }
        if m in FUNDO_MESES_ESPERADOS:
            registro["fundo_recomposicao"] = round(abs(r["fundo_planilha"]), 2)
            registro["saldo_a_pagar"] = round(r["saldo_pagar_planilha"], 2)
        registros.append(registro)

    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump({UNIDADE_ID: registros}, f, ensure_ascii=False, indent=2, sort_keys=False)

    print(f"Gravado em {SAIDA}")
    print(f"  {UNIDADE_ID}: {registros[0]['mes_referencia']} -> {registros[-1]['mes_referencia']} "
          f"({len(registros)} competências)")
    print(f"  mês de virada do prejuízo (chega a zero): {mes_virada}")
    print(f"  meses com Fundo de Recomposição: {fundo_encontrados[0]} -> {fundo_encontrados[-1]} "
          f"({len(fundo_encontrados)})")
    print("  todas as validações passaram (blocos, datas do bloco final, totalizadores, "
          "cadeia de prejuízo idêntica à regra do calculator ao vivo, mês de virada, "
          "janela do Fundo, identidade bruto+fundo=líquido).")


def _abortar(erros):
    print(f"EXTRAÇÃO ABORTADA — {len(erros)} validação(ões) falharam, nenhum arquivo foi gravado:")
    for e in erros:
        print(f"  - {e}")
    sys.exit(1)


if __name__ == "__main__":
    main()
