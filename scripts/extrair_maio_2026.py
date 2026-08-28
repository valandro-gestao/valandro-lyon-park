"""
Backfill pontual de 2026-05 (migration 0004).

Contexto: scripts/extrair_historico_lancamentos.py usa MES_CORTE = "2026-05"
como limite EXCLUSIVO, presumindo que a partir dessa competência todas as
unidades já teriam lançamento real gerado pela própria ferramenta. Essa
suposição se mostrou falsa: só 5 unidades (a_schneider, anitta_mall, fiergs,
patio_real, patio_maiojama) tinham 2026-05 real em `lancamentos` — as demais
simplesmente não tinham essa competência em lugar nenhum, e o comparativo do
PDF não alcançava 12 meses para elas (ex.: In 1183).

Este script reaproveita os mapeamentos de coluna já verificados em
scripts/extrair_historico_lancamentos.py (mesmas abas, mesmos índices,
mesma verificação de rótulo) e extrai SOMENTE a competência 2026-05, via o
parâmetro `apenas_mes` das funções de extração — sem tocar em
migrations/data/historico_lancamentos.json, que permanece exatamente como a
migração 0002 já publicou.

Gera migrations/data/historico_lancamentos_2026_05.json, usado exclusivamente
por migrations/0004_backfill_maio_2026.py. A migração decide, unidade por
unidade, se essa competência já existe em `lancamentos` (lançamento real) —
se existir, este arquivo é ignorado para ela.

Uso:
  .venv/bin/python scripts/extrair_maio_2026.py
"""
import json
import os
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(__file__))
import extrair_historico_lancamentos as base

MES_ALVO = "2026-05"
SAIDA = os.path.join(os.path.dirname(__file__), "..", "migrations", "data", "historico_lancamentos_2026_05.json")


def main():
    if not os.path.exists(base.EXCEL):
        sys.exit(f"Planilha não encontrada em {base.EXCEL}. Este script só roda localmente, uma vez.")

    wb = openpyxl.load_workbook(base.EXCEL, data_only=True, read_only=True)

    resultado: dict[str, list[dict]] = {}
    problemas: dict[str, list[str]] = {}

    for uid, (aba, col_fat, rot_fat, col_res, rot_res, col_al1, rot_al1, col_al2, rot_al2) in base.MAPA_LINHA.items():
        registros, erros = base._extrair_linha(
            wb, aba, col_fat, rot_fat, col_res, rot_res, col_al1, rot_al1, col_al2, rot_al2,
            apenas_mes=MES_ALVO,
        )
        if erros:
            problemas[uid] = erros
        resultado[uid] = registros

    for uid, (aba, col_fat, rot_fat, col_res, rot_res, col_alug, rot_alug) in base.MAPA_LINHA_RESULTADO_DERIVADO.items():
        registros, erros = base._extrair_linha_resultado_derivado(
            wb, aba, col_fat, rot_fat, col_res, rot_res, col_alug, rot_alug,
            apenas_mes=MES_ALVO,
        )
        if erros:
            problemas[uid] = erros
        resultado[uid] = registros

    for uid, (aba, row_fat, rot_fat, row_res, rot_res, row_alug, rot_alug) in base.MAPA_TRANSPOSTO.items():
        registros, erros = base._extrair_transposto(
            wb, aba, row_fat, rot_fat, row_res, rot_res, row_alug, rot_alug,
            apenas_mes=MES_ALVO,
        )
        if erros:
            problemas[uid] = erros
        resultado[uid] = registros

    patio_dados, patio_problemas = base._extrair_patio(wb, apenas_mes=MES_ALVO)
    resultado.update(patio_dados)
    problemas.update(patio_problemas)

    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"Gravado em {SAIDA}")
    print()
    for uid, registros in sorted(resultado.items()):
        if not registros:
            extra = f" ({'; '.join(problemas[uid])})" if uid in problemas else ""
            print(f"  {uid:20s} sem {MES_ALVO} na planilha{extra}")
        else:
            print(f"  {uid:20s} {registros[0]}")
    if problemas:
        print()
        print("Problemas:")
        for uid, msgs in sorted(problemas.items()):
            for msg in msgs:
                print(f"  {uid}: {msg}")


if __name__ == "__main__":
    main()
