"""
Camada de controle de workflow/status dos relatórios.
Gerencia ciclo de vida: pendente → gerado → revisado → aprovado → reaberto
e versionamento de PDFs por competência.

Não conhece regras de cálculo. Só sabe gerar PDF e mover arquivos.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.reporter import build_report_data
from app.renderer import render_html, export_pdf
from app.models import ResultadoUnidade, get_db
from app.calculators.patio import ResultadoPatio
from app.paths import RUNS_DIR, ensure_dirs

# Transições de status permitidas
_TRANSITIONS: dict[str, set[str]] = {
    "pendente": {"gerado", "erro"},
    "gerado":   {"revisado", "aprovado", "erro"},
    "revisado": {"aprovado", "reaberto", "gerado", "erro"},
    "aprovado": {"reaberto"},
    "reaberto": {"gerado", "erro"},
    "erro":     {"gerado", "pendente"},
}

# ─── helpers de path ────────────────────────────────────────────────────────

def _run_dir(mes_ref: str) -> Path:
    return RUNS_DIR / mes_ref

def _reports_dir(mes_ref: str) -> Path:
    return _run_dir(mes_ref) / "reports"

def _versions_dir(mes_ref: str) -> Path:
    return _reports_dir(mes_ref) / "versions"

def _status_path(mes_ref: str) -> Path:
    return _run_dir(mes_ref) / "status.json"

def _pdf_path(mes_ref: str, uid: str) -> Path:
    return _reports_dir(mes_ref) / f"{uid}.pdf"

def _version_pdf_path(mes_ref: str, uid: str, version: int) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return _versions_dir(mes_ref) / f"{uid}_v{version}_{ts}.pdf"

# ─── leitura/escrita do status.json ─────────────────────────────────────────

def load_run(mes_ref: str) -> dict:
    """Carrega status.json da competência. Retorna {} se não existir."""
    p = _status_path(mes_ref)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_run(mes_ref: str, data: dict):
    _run_dir(mes_ref).mkdir(parents=True, exist_ok=True)
    with open(_status_path(mes_ref), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_unit_run(mes_ref: str, uid: str) -> dict:
    """Retorna o bloco de status de uma unidade, criando se necessário."""
    run = load_run(mes_ref)
    return run.get(uid, _default_unit_run())


def _default_unit_run() -> dict:
    return {
        "status": "pendente",
        "pdf_path": None,
        "version": 0,
        "last_generated_at": None,
        "last_reviewed_at": None,
        "last_approved_at": None,
        "reopened_at": None,
        "reopened_reason": None,
        "versions": [],
    }


def _update_unit(mes_ref: str, uid: str, **kwargs):
    run = load_run(mes_ref)
    if uid not in run:
        run[uid] = _default_unit_run()
    run[uid].update(kwargs)
    _save_run(mes_ref, run)
    return run[uid]


def _can_transition(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, set())

# ─── ações de workflow ───────────────────────────────────────────────────────

def generate_report(
    mes_ref: str,
    uid: str,
    resultado: ResultadoUnidade,
    patio_split_id: Optional[str] = None,
    patio_resultado: Optional[ResultadoPatio] = None,
) -> str:
    """
    Gera HTML → PDF para a unidade.
    Se já existir PDF em status revisado/aprovado/reaberto, cria versão histórica antes.
    Retorna caminho do PDF gerado.
    """
    _reports_dir(mes_ref).mkdir(parents=True, exist_ok=True)
    _versions_dir(mes_ref).mkdir(parents=True, exist_ok=True)

    unit_run = get_unit_run(mes_ref, uid)
    current_status = unit_run["status"]
    current_pdf = unit_run["pdf_path"]
    current_version = unit_run["version"]

    # Backup se já existia PDF em status significativo
    new_versions = list(unit_run.get("versions", []))
    if current_pdf and Path(current_pdf).exists() and current_status in ("revisado", "aprovado", "reaberto"):
        v_path = _version_pdf_path(mes_ref, uid, current_version)
        shutil.copy2(current_pdf, v_path)
        new_versions.append({
            "version": current_version,
            "pdf_path": str(v_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "status_at_time": current_status,
        })

    # Gera novo PDF
    report = build_report_data(
        resultado, mes_ref,
        patio_split_id=patio_split_id,
        patio_resultado=patio_resultado,
    )
    html = render_html(report)
    pdf_dest = str(_pdf_path(mes_ref, uid))
    export_pdf(html, os.path.basename(pdf_dest))

    # WeasyPrint escreve em output/; mover para runs/
    from app.renderer import OUTPUT_DIR
    src = os.path.join(OUTPUT_DIR, os.path.basename(pdf_dest))
    os.makedirs(os.path.dirname(pdf_dest), exist_ok=True)
    shutil.move(src, pdf_dest)

    new_version = current_version + 1
    _update_unit(mes_ref, uid,
        status="gerado",
        pdf_path=pdf_dest,
        version=new_version,
        last_generated_at=datetime.now().isoformat(timespec="seconds"),
        versions=new_versions,
    )
    return pdf_dest


def mark_reviewed(mes_ref: str, uid: str):
    unit_run = get_unit_run(mes_ref, uid)
    if not _can_transition(unit_run["status"], "revisado"):
        raise ValueError(f"Não é possível marcar como revisado a partir de '{unit_run['status']}'")
    _update_unit(mes_ref, uid,
        status="revisado",
        last_reviewed_at=datetime.now().isoformat(timespec="seconds"),
    )


def mark_approved(mes_ref: str, uid: str):
    unit_run = get_unit_run(mes_ref, uid)
    if not _can_transition(unit_run["status"], "aprovado"):
        raise ValueError(f"Não é possível aprovar a partir de '{unit_run['status']}'")
    _update_unit(mes_ref, uid,
        status="aprovado",
        last_approved_at=datetime.now().isoformat(timespec="seconds"),
    )


def reopen(mes_ref: str, uid: str, reason: Optional[str] = None):
    unit_run = get_unit_run(mes_ref, uid)
    if not _can_transition(unit_run["status"], "reaberto"):
        raise ValueError(f"Não é possível reabrir a partir de '{unit_run['status']}'")
    _update_unit(mes_ref, uid,
        status="reaberto",
        reopened_at=datetime.now().isoformat(timespec="seconds"),
        reopened_reason=reason or "",
    )


def mark_error(mes_ref: str, uid: str, message: str):
    _update_unit(mes_ref, uid, status="erro", error_message=message)


def get_versions(mes_ref: str, uid: str) -> list[dict]:
    return get_unit_run(mes_ref, uid).get("versions", [])


# ─── helpers para reconstruir resultado a partir do DB ───────────────────────

def load_resultado_from_db(mes_ref: str, uid: str) -> Optional[ResultadoUnidade]:
    """Reconstrói ResultadoUnidade a partir do lancamento salvo no SQLite."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
            (uid, mes_ref)
        ).fetchone()
    if not row:
        return None
    data = json.loads(row["resultado_json"])
    # Remove campos que não são parâmetros do dataclass
    data.pop("__class__", None)
    try:
        return ResultadoUnidade(**{k: v for k, v in data.items()
                                   if k in ResultadoUnidade.__dataclass_fields__})
    except Exception:
        return None


# ─── resumo da competência ───────────────────────────────────────────────────

def summarize_run(mes_ref: str) -> dict[str, str]:
    """Retorna {uid: status} para exibição rápida."""
    run = load_run(mes_ref)
    return {uid: info["status"] for uid, info in run.items()}


STATUS_LABELS = {
    "pendente":  ("⬜", "Pendente"),
    "gerado":    ("🔵", "Gerado"),
    "revisado":  ("🟡", "Revisado"),
    "aprovado":  ("🟢", "Aprovado"),
    "reaberto":  ("🔴", "Reaberto"),
    "erro":      ("❌", "Erro"),
}


def status_label(status: str) -> str:
    icon, label = STATUS_LABELS.get(status, ("⬜", status.title()))
    return f"{icon} {label}"
