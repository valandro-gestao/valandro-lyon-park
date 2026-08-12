"""
Parser da planilha operacional de eventos (Excel MDO).

Estrutura esperada:
  Aba "Eventos":
    Col 0: Data         — datetime ou serial Excel
    Col 1: Quantidade   — int (nº de extras)
    Col 2: Horário      — str ("10h às 22h")
    Col 3: Evento       — str (nome do evento)
    Col 4: Valor un.    — float (150.0)
    Col 5: Valor Total  — float
    Col 6: Mês          — str ("mai/2026")
    Col 7: NOMES        — str (opcional, staff)

  Aba "Resumo Mensal":
    Col 0: Mês          — str ("jan/2026" … "Total")
    Col 1: Total Extras — int
    Col 2: Valor Total  — float
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pandas as pd

RUNS_DIR = Path(__file__).parent.parent.parent / "data" / "runs"

_MES_MAP = {
    "jan": "01", "fev": "02", "mar": "03", "abr": "04",
    "mai": "05", "jun": "06", "jul": "07", "ago": "08",
    "set": "09", "out": "10", "nov": "11", "dez": "12",
}


def _mes_label_to_ref(label: str) -> str | None:
    """'mai/2026' → '2026-05'. Retorna None se não reconhecido."""
    try:
        partes = str(label).lower().strip().split("/")
        return f"{partes[1]}-{_MES_MAP[partes[0]]}"
    except (KeyError, IndexError):
        return None


def _fmt_data(val) -> str:
    """Converte data (Timestamp/datetime/str) para 'dd/mm/aa'."""
    try:
        if hasattr(val, "strftime"):
            return val.strftime("%d/%m/%y")
        return str(val)
    except Exception:
        return str(val)


def _safe_float(val, default=0.0) -> float:
    try:
        return float(val) if pd.notna(val) else default
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=0) -> int:
    try:
        return int(float(val)) if pd.notna(val) else default
    except (TypeError, ValueError):
        return default


# ─── parse principal ─────────────────────────────────────────────────────────

def parse_xlsx(path: str) -> dict:
    """
    Lê a planilha e retorna:
    {
      "eventos": [{data, evento, horario, qtd_extras, valor_unitario, valor_total, mes_ref}, ...],
      "resumo":  [{mes_label, mes_ref, qtd_extras, valor_total}, ...]   # apenas meses com dados
    }
    """
    xf = pd.ExcelFile(path)

    # ── Aba Eventos ──
    df_ev = pd.read_excel(xf, sheet_name="Eventos", header=0)
    df_ev.columns = range(len(df_ev.columns))  # normaliza para índices

    eventos = []
    for _, row in df_ev.iterrows():
        mes_label = str(row.get(6, "")).strip()
        mes_ref = _mes_label_to_ref(mes_label)
        if not mes_ref:
            continue  # linha sem mês válido (total, vazio etc.)

        val_total = _safe_float(row.get(5))
        if val_total == 0.0:
            continue  # linha vazia

        eventos.append({
            "data":           _fmt_data(row.get(0)),
            "evento":         str(row.get(3, "")).strip(),
            "horario":        str(row.get(2, "")).strip(),
            "qtd_extras":     _safe_int(row.get(1)),
            "valor_unitario": _safe_float(row.get(4)),
            "valor_total":    val_total,
            "mes_ref":        mes_ref,
            "mes_label":      mes_label,
        })

    # ── Aba Resumo Mensal ──
    df_res = pd.read_excel(xf, sheet_name="Resumo Mensal", header=0)
    df_res.columns = range(len(df_res.columns))

    resumo = []
    for _, row in df_res.iterrows():
        mes_label = str(row.get(0, "")).strip()
        if mes_label.lower() in ("total", "mês", "mes", ""):
            continue
        mes_ref = _mes_label_to_ref(mes_label)
        if not mes_ref:
            continue
        qtd = _safe_int(row.get(1))
        total = _safe_float(row.get(2))
        if qtd == 0 and total == 0.0:
            continue  # meses sem eventos
        resumo.append({
            "mes_label": mes_label,
            "mes_ref":   mes_ref,
            "qtd_extras": qtd,
            "valor_total": total,
        })

    return {"eventos": eventos, "resumo": resumo}


# ─── acesso por competência ───────────────────────────────────────────────────

def get_eventos_competencia(parsed: dict, mes_ref: str) -> list[dict]:
    """Filtra eventos da competência informada."""
    return [e for e in parsed["eventos"] if e["mes_ref"] == mes_ref]


def get_total_competencia(parsed: dict, mes_ref: str) -> float:
    """Soma valor_total dos eventos da competência."""
    return sum(e["valor_total"] for e in get_eventos_competencia(parsed, mes_ref))


def get_resumo_anual(parsed: dict) -> list[dict]:
    """Retorna o resumo mensal apenas de meses com dados."""
    return parsed.get("resumo", [])


# ─── persistência ────────────────────────────────────────────────────────────

def salvar(mes_ref: str, parsed: dict, original_path: str | None = None):
    """
    Salva:
      data/runs/{mes_ref}/processed/eventos.json  (dados estruturados)
      data/runs/{mes_ref}/input/eventos/           (cópia do arquivo original)
    """
    run_dir = RUNS_DIR / mes_ref

    processed_dir = run_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    with open(processed_dir / "eventos.json", "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)

    if original_path:
        input_dir = run_dir / "input" / "eventos"
        input_dir.mkdir(parents=True, exist_ok=True)
        dest = input_dir / Path(original_path).name
        shutil.copy2(original_path, dest)


def load(mes_ref: str) -> dict | None:
    """Carrega eventos processados do disco. Retorna None se não existir."""
    p = RUNS_DIR / mes_ref / "processed" / "eventos.json"
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── funções por unidade (ILP / Fiergs separados) ────────────────────────────

def salvar_uid(mes_ref: str, uid: str, parsed: dict,
               original_path: str | None = None):
    """
    Salva eventos de uma unidade específica:
      processed/eventos_{uid}.json
      input/eventos/{uid}/  (cópia do original)
    """
    run_dir = RUNS_DIR / mes_ref

    processed_dir = run_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    with open(processed_dir / f"eventos_{uid}.json", "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)

    if original_path:
        input_dir = run_dir / "input" / "eventos" / uid
        input_dir.mkdir(parents=True, exist_ok=True)
        dest = input_dir / Path(original_path).name
        shutil.copy2(original_path, dest)


def load_uid(mes_ref: str, uid: str) -> dict | None:
    """Carrega eventos de uma unidade específica. Retorna None se não existir."""
    p = RUNS_DIR / mes_ref / "processed" / f"eventos_{uid}.json"
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
