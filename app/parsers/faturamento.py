"""
Parser da planilha de faturamentos mensais.

Detecta automaticamente as colunas de nome/unidade e valor,
faz matching fuzzy com o YAML de unidades e retorna um mapa
{uid: faturamento} pronto para uso no engine.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path

import pandas as pd

RUNS_DIR = Path(__file__).parent.parent.parent / "data" / "runs"

# UIDs derivados do Pátio que não aparecem diretamente na planilha de faturamento
_VIRTUAL_UIDS = {"patio_real", "patio_maiojama"}

# Termos que indicam coluna de nomes/unidades
_NOME_KEYWORDS = {"unidade", "estacionamento", "nome", "local", "contratante", "empreendimento"}
# Termos que indicam coluna de faturamento
_FAT_KEYWORDS  = {"faturamento", "receita", "bruto", "valor", "total", "fat"}


# ─── normalização ─────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Remove acentos, pontuação e lowercase para comparação."""
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def _palavras(s: str) -> set[str]:
    return set(_norm(s).split())


def _match_score(planilha_nome: str, unit_nome: str, unit_id: str) -> float:
    """Retorna score 0–1 de similaridade entre nome da planilha e unidade do YAML."""
    pn = _palavras(planilha_nome)
    un = _palavras(unit_nome)
    ui = _palavras(unit_id.replace("_", " "))

    # Interseção sobre a união (Jaccard)
    score_nome = len(pn & un) / max(len(pn | un), 1)
    score_id   = len(pn & ui) / max(len(pn | ui), 1)
    return max(score_nome, score_id)


def match_nome(planilha_nome: str, units: list[dict],
               threshold: float = 0.35) -> tuple[str | None, float]:
    """
    Retorna (uid, score) da melhor correspondência ou (None, 0) se abaixo do threshold.
    units: lista de dicts do YAML (cada um com 'id' e 'nome').
    """
    best_uid, best_score = None, 0.0
    for u in units:
        if u.get("id") in _VIRTUAL_UIDS:
            continue
        s = _match_score(planilha_nome, u.get("nome", ""), u.get("id", ""))
        if s > best_score:
            best_score, best_uid = s, u["id"]
    if best_score >= threshold:
        return best_uid, best_score
    return None, best_score


# ─── detecção de colunas ─────────────────────────────────────────────────────

def _detect_cols(df: pd.DataFrame) -> tuple[int, int]:
    """
    Detecta índice da coluna de nomes e da coluna de faturamento.
    Retorna (col_nome_idx, col_fat_idx).
    """
    cols = list(df.columns)

    # 1. Tenta pelo cabeçalho (string match)
    col_nome_idx, col_fat_idx = None, None
    for i, col in enumerate(cols):
        col_s = _norm(str(col))
        if any(k in col_s for k in _NOME_KEYWORDS) and col_nome_idx is None:
            col_nome_idx = i
        if any(k in col_s for k in _FAT_KEYWORDS) and col_fat_idx is None:
            col_fat_idx = i

    # 2. Fallback: primeira coluna de strings = nome, primeira coluna numérica = valor
    if col_nome_idx is None:
        for i, col in enumerate(cols):
            if df[col].dtype == object:
                col_nome_idx = i
                break
    if col_fat_idx is None:
        for i, col in enumerate(cols):
            if pd.api.types.is_numeric_dtype(df[col]):
                col_fat_idx = i
                break

    return col_nome_idx or 0, col_fat_idx or 1


# ─── parse principal ──────────────────────────────────────────────────────────

def parse_xlsx(path: str, units: list[dict]) -> dict:
    """
    Lê planilha de faturamentos e retorna:
    {
      "uid_map":        {uid: faturamento},          # mapeados com sucesso
      "nao_mapeados":   [{nome, valor, score}],      # linhas sem uid correspondente
      "sem_fat":        [uid],                       # uids do YAML não encontrados
      "col_nome":       str,                         # nome da coluna detectada como nomes
      "col_fat":        str,                         # nome da coluna detectada como valores
      "raw_rows":       [{nome, valor}],             # todas as linhas brutas com valor > 0
      "sheet":          str,                         # aba utilizada
    }
    """
    xf = pd.ExcelFile(path)
    sheet = xf.sheet_names[0]
    df = pd.read_excel(xf, sheet_name=sheet, header=0)
    df.columns = range(len(df.columns))  # normaliza para índices numéricos

    col_nome_idx, col_fat_idx = _detect_cols(df)

    col_nome_real = df.columns[col_nome_idx]
    col_fat_real  = df.columns[col_fat_idx]

    # Nome das colunas para exibição (pega o nome original antes do reset)
    xf2 = pd.ExcelFile(path)
    df_orig = pd.read_excel(xf2, sheet_name=sheet, header=0)
    col_nome_label = str(list(df_orig.columns)[col_nome_idx])
    col_fat_label  = str(list(df_orig.columns)[col_fat_idx])

    uid_map: dict[str, float] = {}
    nao_mapeados: list[dict]   = []
    raw_rows: list[dict]       = []

    active_uids = {u["id"] for u in units if u.get("id") not in _VIRTUAL_UIDS}

    for _, row in df.iterrows():
        nome_raw = str(row.get(col_nome_real, "")).strip()
        valor_raw = row.get(col_fat_real)

        # ignora linhas sem nome ou sem valor numérico
        if not nome_raw or nome_raw.lower() in ("nan", "total", ""):
            continue
        try:
            valor = float(valor_raw)
        except (TypeError, ValueError):
            continue
        if valor <= 0:
            continue

        raw_rows.append({"nome": nome_raw, "valor": valor})

        uid, score = match_nome(nome_raw, units)
        if uid:
            # se já existe, soma (pode haver linhas duplicadas)
            uid_map[uid] = uid_map.get(uid, 0.0) + valor
        else:
            nao_mapeados.append({"nome": nome_raw, "valor": valor, "score": round(score, 2)})

    sem_fat = [uid for uid in active_uids if uid not in uid_map]

    return {
        "uid_map":      uid_map,
        "nao_mapeados": nao_mapeados,
        "sem_fat":      sem_fat,
        "col_nome":     col_nome_label,
        "col_fat":      col_fat_label,
        "raw_rows":     raw_rows,
        "sheet":        sheet,
    }


# ─── persistência ─────────────────────────────────────────────────────────────

def salvar(mes_ref: str, parsed: dict, original_path: str | None = None):
    """
    Salva:
      data/runs/{mes_ref}/processed/faturamento.json
      data/runs/{mes_ref}/input/faturamento/<arquivo original>
    """
    run_dir = RUNS_DIR / mes_ref
    proc_dir = run_dir / "processed"
    proc_dir.mkdir(parents=True, exist_ok=True)
    with open(proc_dir / "faturamento.json", "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)

    if original_path:
        inp_dir = run_dir / "input" / "faturamento"
        inp_dir.mkdir(parents=True, exist_ok=True)
        dest = inp_dir / Path(original_path).name
        shutil.copy2(original_path, dest)


def load(mes_ref: str) -> dict | None:
    """Carrega faturamento.json processado. Retorna None se não existir."""
    p = RUNS_DIR / mes_ref / "processed" / "faturamento.json"
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
