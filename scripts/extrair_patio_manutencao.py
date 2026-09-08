"""
Extrai o histórico de Pátio Manutenções da planilha histórica original
("Lyon - Dados para Relatórios.xlsx", aba "Patio Manutenção") e grava em
migrations/data/historico_patio_manutencao.json — o único formato que a
migração de backfill desta unidade lê. Executado uma única vez, localmente;
não faz parte do runtime da aplicação e não é uma funcionalidade do
usuário.

Contexto: Pátio Manutenções nunca foi incluída no escopo de
scripts/extrair_historico_lancamentos.py (nem de nenhum outro script já
existente) — confirmado por inspeção: nenhum mapeamento daquele script
(MAPA_LINHA, MAPA_LINHA_RESULTADO_DERIVADO, MAPA_TRANSPOSTO, _extrair_patio)
referencia a aba "Patio Manutenção". Não foi um bug nem uma exclusão
deliberada documentada — a unidade simplesmente nunca entrou no escopo
original da extração. A operadora confirmou (set/2026) que esse histórico
existe e deve ser recuperado.

Layout da aba (diferente das demais abas do arquivo — aqui os indicadores
ficam em LINHAS fixas, e os meses em COLUNAS, com uma coluna de "total
anual" — valor numérico puro, sem nome de mês — intercalada a cada ano):
  linha 3  Receita de Manutenção        (faturamento)
  linha 4  Retenção de ISS - 5%
  linha 5  Total Líquido                (subtotal)
  linha 6  Total Despesas               (= linha 7 + linha 8)
  linha 7  Manutenção Equipamentos/Aucon
  linha 8  Manutenção de Instalações
  linha 9  Resultado
  linha 10 Saldo Acumulado
As colunas de total anual (linha 2 com um int puro, ex. 2023) são
identificadas e descartadas — nunca tratadas como competência.

Resolução temporal (a parte não-trivial desta extração): a aba NÃO tem
nenhuma célula de data explícita (diferente de outras abas do mesmo
arquivo — "W-Tower Caxias", por exemplo, tem datetimes reais na linha 2
para os últimos 5 meses). Os rótulos de "ano total" desta aba estão
defasados em exatamente 1 ano — mesmo defeito de manutenção manual já
confirmado de forma independente na aba "W-Tower Caxias" (lá comprovável
porque tem datas explícitas: o bloco rotulado "2025" carrega, na própria
planilha, datas reais de 2026 na linha 2 — o mantenedor evidentemente
atualiza os valores mensais mas nem sempre o rótulo do "total do ano").

Aqui a confirmação vem por outra via, igualmente direta: o Saldo Acumulado
da ÚLTIMA coluna bate — na casa do centavo — com a âncora oficial de saldo
de Pátio Manutenções em maio/2026, já confirmada pela operadora e
registrada no sistema (-42223.85 — ver migrations/0008_ancoras_saldo_
acumulado.py e migrations/0010_corrigir_sinal_ancora_patio_manutencao.py).
Se a última coluna fosse realmente maio/2025 (rótulo literal da planilha),
faltariam 12 meses de evolução do saldo até maio/2026 — bater no mesmo
valor seria uma coincidência estatisticamente implausível (o saldo varia
milhares de reais mês a mês). Por isso todo rótulo de ano é corrigido em
+1 antes de gerar a competência final: o bloco não rotulado inicial
(abril-dezembro, imediatamente anterior ao primeiro total "2023") vira
2023; o total "2023" (jan-dez) vira 2024; o total "2024" (jan-dez) vira
2025; o total "2025" (jan-maio, a cauda) vira 2026.

Este script se RECUSA a gravar o JSON se qualquer validação abaixo falhar
— aborta com sys.exit e uma mensagem explicando exatamente qual validação
não passou, para nunca produzir um arquivo com competências erradas:
  1. a série completa de Saldo Acumulado precisa fechar sem nenhuma
     divergência (Saldo[mês] == Saldo[mês-1] + Resultado[mês], para todo
     mês exceto o primeiro) — confirma que nenhuma coluna foi
     pulada/duplicada e que a leitura estrutural está correta;
  2. a competência do último mês, DEPOIS da correção de +1 ano, precisa
     ser exatamente 2026-05;
  3. o Saldo Acumulado do último mês precisa bater com -42223.85 dentro de
     meio centavo de tolerância;
  4. nenhuma competência duplicada;
  5. a série de competências, em ordem, precisa ser estritamente
     cronológica e sem lacunas (mês a mês, sem pular nenhum).

Uso:
  .venv/bin/python scripts/extrair_patio_manutencao.py
"""
import json
import os
import sys

import openpyxl

EXCEL = os.path.expanduser("~/Downloads/Lyon - Dados para Relatórios.xlsx")
SAIDA = os.path.join(os.path.dirname(__file__), "..", "migrations", "data", "historico_patio_manutencao.json")

ABA = "Patio Manutenção"
UNIDADE_ID = "patio_manutencao"

LINHA_FATURAMENTO = 3
LINHA_RETENCAO_ISS = 4
LINHA_TOTAL_LIQUIDO = 5
LINHA_TOTAL_DESPESAS = 6
LINHA_AUCON = 7
LINHA_INSTALACOES = 8
LINHA_RESULTADO = 9
LINHA_SALDO_ACUMULADO = 10

COL_INICIO = "C"
COL_FIM = "AQ"
CORRECAO_ANOS = 1  # ver docstring — rótulos de ano da planilha defasados em 1 ano
COMPETENCIA_FINAL_ESPERADA = "2026-05"
ANCORA_OFICIAL_MAIO_2026 = -42223.85
TOLERANCIA = 0.005  # meio centavo

MESES_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def main():
    if not os.path.exists(EXCEL):
        sys.exit(f"Planilha não encontrada em {EXCEL}. Este script só roda localmente, uma vez.")

    wb = openpyxl.load_workbook(EXCEL, data_only=True, read_only=True)
    if ABA not in wb.sheetnames:
        sys.exit(f"Aba {ABA!r} não encontrada na planilha. Abas disponíveis: {wb.sheetnames}")
    ws = wb[ABA]

    col_inicio = openpyxl.utils.column_index_from_string(COL_INICIO)
    col_fim = openpyxl.utils.column_index_from_string(COL_FIM)

    # 1a passada: identifica colunas de total anual (linha 2, valor numérico
    # puro) e monta o ano corrente de cada coluna de mês real.
    anos_totais = []
    for c in range(col_inicio, col_fim + 1):
        v = ws.cell(row=2, column=c).value
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            anos_totais.append(int(v))
    if not anos_totais:
        sys.exit("Nenhuma coluna de 'total anual' encontrada na linha 2 — layout da aba mudou, abortando.")

    # Guarda os valores em precisão total (sem arredondar) para validar a
    # continuidade — a planilha soma o Saldo Acumulado internamente sobre
    # os valores completos, não sobre versões já arredondadas a 2 casas;
    # arredondar cada célula antes de somar introduz divergências de
    # ±0,01 em cascata que não são erro de dado, só efeito de
    # arredondamento prematuro. O JSON final é arredondado (dinheiro real
    # não tem mais que 2 casas), só a validação usa o valor bruto.
    registros = []
    brutos = []
    ano_atual = anos_totais[0] - 1
    for c in range(col_inicio, col_fim + 1):
        v2 = ws.cell(row=2, column=c).value
        if isinstance(v2, (int, float)) and not isinstance(v2, bool):
            ano_atual = int(v2)
            continue  # coluna de total anual — nunca é competência

        mes_nome = v2
        if mes_nome not in MESES_PT:
            sys.exit(f"Coluna {c} (linha 2 = {v2!r}) não é nome de mês nem total anual — layout inesperado, abortando.")
        mes_idx = MESES_PT.index(mes_nome) + 1
        ano_corrigido = ano_atual + CORRECAO_ANOS
        mes_referencia = f"{ano_corrigido:04d}-{mes_idx:02d}"

        faturamento = _num(ws.cell(row=LINHA_FATURAMENTO, column=c).value)
        retencao_iss = _num(ws.cell(row=LINHA_RETENCAO_ISS, column=c).value)
        total_liquido = _num(ws.cell(row=LINHA_TOTAL_LIQUIDO, column=c).value)
        total_despesas = _num(ws.cell(row=LINHA_TOTAL_DESPESAS, column=c).value)
        aucon = _num(ws.cell(row=LINHA_AUCON, column=c).value)
        instalacoes = _num(ws.cell(row=LINHA_INSTALACOES, column=c).value)
        resultado = _num(ws.cell(row=LINHA_RESULTADO, column=c).value)
        saldo_acumulado = _num(ws.cell(row=LINHA_SALDO_ACUMULADO, column=c).value)

        brutos.append({
            "mes_referencia": mes_referencia,
            "faturamento": faturamento, "retencao_iss": retencao_iss,
            "total_liquido": total_liquido, "total_despesas": total_despesas,
            "aucon": aucon, "instalacoes": instalacoes,
            "resultado": resultado, "saldo_acumulado": saldo_acumulado,
        })
        registros.append({
            "mes_referencia": mes_referencia,
            "faturamento": round(faturamento, 2),
            "retencao_iss": round(retencao_iss, 2),
            "total_liquido": round(total_liquido, 2),
            "total_despesas": round(total_despesas, 2),
            "custos": {"aucon": round(aucon, 2), "instalacoes": round(instalacoes, 2)},
            "resultado": round(resultado, 2),
            "saldo_acumulado": round(saldo_acumulado, 2),
        })

    # ── Validações — nenhuma delas passa em silêncio ────────────────────────
    erros = []

    competencias = [r["mes_referencia"] for r in registros]
    if len(competencias) != len(set(competencias)):
        vistos, duplicadas = set(), set()
        for m in competencias:
            (duplicadas if m in vistos else vistos).add(m)
        erros.append(f"competências duplicadas: {sorted(duplicadas)}")

    competencias_ordenadas = sorted(competencias)
    if competencias != competencias_ordenadas:
        erros.append("série não está em ordem cronológica estrita")

    def _proximo_mes(m):
        ano, mes = int(m[:4]), int(m[5:7])
        return f"{ano+1:04d}-01" if mes == 12 else f"{ano:04d}-{mes+1:02d}"

    for i in range(len(competencias) - 1):
        if _proximo_mes(competencias[i]) != competencias[i + 1]:
            erros.append(f"lacuna na série entre {competencias[i]} e {competencias[i+1]}")

    for i, r in enumerate(brutos):
        esperado = r["resultado"] if i == 0 else brutos[i - 1]["saldo_acumulado"] + r["resultado"]
        if abs(esperado - r["saldo_acumulado"]) > TOLERANCIA:
            erros.append(
                f"{r['mes_referencia']}: saldo acumulado não fecha "
                f"(esperado {round(esperado, 2)}, planilha {round(r['saldo_acumulado'], 2)})"
            )

    if not registros or competencias[-1] != COMPETENCIA_FINAL_ESPERADA:
        ultima = competencias[-1] if registros else None
        erros.append(f"última competência é {ultima!r}, esperada {COMPETENCIA_FINAL_ESPERADA!r}")

    if registros:
        saldo_final = registros[-1]["saldo_acumulado"]
        if abs(saldo_final - ANCORA_OFICIAL_MAIO_2026) > TOLERANCIA:
            erros.append(
                f"saldo final ({saldo_final}) não bate com a âncora oficial "
                f"({ANCORA_OFICIAL_MAIO_2026}) — validação de segurança da correção de ano falhou"
            )

    for r in brutos:
        if abs(r["faturamento"] - (r["total_liquido"] + r["retencao_iss"])) > TOLERANCIA:
            erros.append(f"{r['mes_referencia']}: faturamento != total_liquido + retencao_iss")
        if abs(r["total_despesas"] - (r["aucon"] + r["instalacoes"])) > TOLERANCIA:
            erros.append(f"{r['mes_referencia']}: total_despesas != aucon + instalacoes")
        if abs(r["resultado"] - (r["total_liquido"] - r["total_despesas"])) > TOLERANCIA:
            erros.append(f"{r['mes_referencia']}: resultado != total_liquido - total_despesas")

    if erros:
        print(f"EXTRAÇÃO ABORTADA — {len(erros)} validação(ões) falharam, nenhum arquivo foi gravado:")
        for e in erros:
            print(f"  - {e}")
        sys.exit(1)

    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump({UNIDADE_ID: registros}, f, ensure_ascii=False, indent=2, sort_keys=False)

    print(f"Gravado em {SAIDA}")
    print(f"  {UNIDADE_ID}: {registros[0]['mes_referencia']} -> {registros[-1]['mes_referencia']} "
          f"({len(registros)} competências)")
    print(f"  saldo final: {registros[-1]['saldo_acumulado']} "
          f"(âncora oficial: {ANCORA_OFICIAL_MAIO_2026})")
    print("  todas as validações passaram (continuidade, sem duplicata, sem lacuna, "
          "âncora, consistência interna dos campos).")


if __name__ == "__main__":
    main()
