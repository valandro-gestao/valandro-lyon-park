"""
Importa histórico anual da planilha Excel para o SQLite.
Lê as abas de cada unidade, agrupa por ano e salva totais anuais.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import sqlite3
import datetime as dt
from app.models import init_db, DB_PATH

EXCEL = os.path.expanduser("~/Downloads/Lyon - Dados para Relatórios.xlsx")

# Mapeamento unidade_id -> (aba, col_mes, col_fat, col_subtotal, col_pe, col_resultado, col_aluguel, col_prejuizo)
# Índices de coluna (0-based)
MAPA = {
    "a_schneider":   ("A. Schneider",   1, 2, 4, 5, 6, 8, 7),
    "axis":          ("Axis",           1, 2, None, None, None, 6, None),
    "dom_pedro":     ("Dom Pedro",      1, 2, None, 3, 4, 6, None),
    "fk":            ("FK",             1, 2, None, None, None, None, None),
    "ilp":           ("ILP",            1, 2, 4, 9, 10, 12, 11),
    "in_1183":       ("In 1183",        1, 2, 4, 5, 6, 8, None),
    "medcenter":     ("Medcenter",      1, 2, 4, 5, 6, 8, None),
    "monza":         ("Monza",          1, 2, None, None, None, 4, None),
    "mw_tristeza":   ("MW Tristeza",    1, 2, 4, 5, 9, 12, 10),
    "park_tower":    ("Park Tower",     1, 2, 4, None, 5, 7, None),
    "praia_de_bellas":("Praia de Bellas",1, 2, 4, 5, 6, 10, None),
    "vasco":         ("Vasco",          1, 2, None, 3, 4, 6, None),
    "viva_open_mall":("Viva Open Mall", 1, 2, 4, 5, 6, 8, None),
    "viva_trindade": ("Viva Trindade",  1, 2, 4, 5, 6, 8, 7),
    "w_tower_caxias":("W-Tower Caxias", 1, 2, 4, None, 5, 7, None),
    "ekos":          ("EKOS",           1, 2, 4, 5, 6, 8, None),
    "oka":           ("OKA",            1, 2, 4, 5, 6, 8, None),
}

# Fiergs e Pátio têm estrutura diferente — importados separadamente
FIERGS = ("Fiergs", 1, 2, 6, 7, 10, 13)  # mes, fat, subtotal, pe, resultado, total_aluguel

def ler_mensal(df: pd.DataFrame, col_mes, col_fat, col_sub, col_pe, col_res, col_alug, col_prej):
    """Retorna lista de dicts com dados mensais válidos."""
    registros = []
    for _, row in df.iterrows():
        mes = row.iloc[col_mes] if col_mes is not None else None
        if not isinstance(mes, (pd.Timestamp, dt.datetime)):
            continue
        fat = _num(row, col_fat)
        if fat is None or fat == 0:
            continue
        registros.append({
            "mes": mes,
            "ano": mes.year,
            "faturamento": fat,
            "subtotal": _num(row, col_sub),
            "ponto_equilibrio": _num(row, col_pe),
            "resultado": _num(row, col_res),
            "aluguel_calculado": _num(row, col_alug),
            "prejuizo_acumulado_entrada": _num(row, col_prej),
        })
    return registros


def _num(row, col):
    if col is None:
        return None
    try:
        v = row.iloc[col]
        return float(v) if pd.notna(v) else None
    except Exception:
        return None


def agregar_anual(registros: list) -> dict:
    """Agrupa registros mensais por ano, somando e calculando médias."""
    anos = {}
    for r in registros:
        ano = r["ano"]
        if ano not in anos:
            anos[ano] = {k: 0.0 for k in ["faturamento","subtotal","ponto_equilibrio",
                                            "resultado","aluguel_calculado","prejuizo_acumulado_entrada"]}
            anos[ano]["_count"] = 0
        anos[ano]["_count"] += 1
        for k in ["faturamento","subtotal","resultado","aluguel_calculado"]:
            v = r.get(k)
            if v is not None:
                anos[ano][k] += v
        # PE e prejuízo: usar o último valor do ano (não soma)
        for k in ["ponto_equilibrio","prejuizo_acumulado_entrada"]:
            v = r.get(k)
            if v is not None:
                anos[ano][k] = v

    for ano in anos:
        anos[ano].pop("_count", None)
    return anos


def salvar_historico(conn, unidade_id: str, anos_data: dict):
    for ano, dados in anos_data.items():
        conn.execute("""
            INSERT INTO historico_anual (unidade_id, ano, dados_json)
            VALUES (?, ?, ?)
            ON CONFLICT(unidade_id, ano)
            DO UPDATE SET dados_json=excluded.dados_json
        """, (unidade_id, int(ano), json.dumps(dados, ensure_ascii=False)))
    print(f"  {unidade_id}: {len(anos_data)} anos importados ({sorted(anos_data.keys())})")


def importar_transposto(conn, xf, uid, aba, row_fat, row_sub, row_res, row_alug):
    """Lê abas onde meses são colunas e totais anuais são colunas marcadas com o ano (float)."""
    df = pd.read_excel(xf, sheet_name=aba, header=None)
    header = list(df.iloc[1])  # linha 1 tem os cabeçalhos de mês/ano
    anos_data = {}
    for col_idx, h in enumerate(header):
        try:
            ano = int(float(h))
            if 2018 <= ano <= 2030:
                anos_data[ano] = {
                    "faturamento": _num(df.iloc[row_fat], col_idx),
                    "subtotal": _num(df.iloc[row_sub], col_idx) if row_sub else None,
                    "resultado": _num(df.iloc[row_res], col_idx) if row_res else None,
                    "aluguel_calculado": _num(df.iloc[row_alug], col_idx) if row_alug else None,
                }
        except (ValueError, TypeError):
            continue
    if anos_data:
        salvar_historico(conn, uid, anos_data)


def importar_patio(conn, xf):
    """Importa histórico das abas Patio (Real e Maiojama)."""
    for split_id, aba, col_mes, col_fat, col_sub, col_pe, col_res, col_alug in [
        ("patio_real",     "Patio",        1, 7,  9, 10, 12, 14),   # fat REAL, subtotal, PE, resultado, aluguel
        ("patio_maiojama", "Patio",        1, 18, 20, 21, 23, 25), # fat MAIOJAMA
    ]:
        df = pd.read_excel(xf, sheet_name=aba, header=None)
        registros = ler_mensal(df, col_mes, col_fat, col_sub, col_pe, col_res, col_alug, None)
        if registros:
            anos = agregar_anual(registros)
            salvar_historico(conn, split_id, anos)


def main():
    init_db()
    xf = pd.ExcelFile(EXCEL)

    with sqlite3.connect(DB_PATH) as conn:
        for uid, params in MAPA.items():
            aba = params[0]
            if aba not in xf.sheet_names:
                print(f"  SKIP {uid} — aba '{aba}' não encontrada")
                continue
            df = pd.read_excel(xf, sheet_name=aba, header=None)
            registros = ler_mensal(df, *params[1:])
            if not registros:
                print(f"  SKIP {uid} — sem dados mensais")
                continue
            anos = agregar_anual(registros)
            salvar_historico(conn, uid, anos)

        # Fiergs separado
        if "Fiergs" in xf.sheet_names:
            df = pd.read_excel(xf, sheet_name="Fiergs", header=None)
            registros = ler_mensal(df, 1, 2, 6, 7, 10, 13, None)
            if registros:
                anos = agregar_anual(registros)
                salvar_historico(conn, "fiergs", anos)

        # Pátio
        importar_patio(conn, xf)

        # Medcenter e Viva Open Mall — estrutura transposta
        importar_transposto(conn, xf, "medcenter",    "Medcenter",    row_fat=2, row_sub=4, row_res=13, row_alug=14)
        importar_transposto(conn, xf, "viva_open_mall","Viva Open Mall", row_fat=2, row_sub=4, row_res=None, row_alug=None)

        conn.commit()

    print("\nImportação concluída.")


if __name__ == "__main__":
    main()
