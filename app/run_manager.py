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
import time
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
    """Grava o status.json de forma atômica (arquivo temporário + os.replace):
    uma falha no meio da escrita nunca deixa o status.json truncado — o estado
    anterior (status de aprovação, versões) permanece íntegro."""
    _run_dir(mes_ref).mkdir(parents=True, exist_ok=True)
    destino = _status_path(mes_ref)
    tmp = destino.with_name(destino.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, destino)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


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


# ─── regeneração do PDF de uma competência APROVADA ──────────────────────────

# Pátio: o PDF de cada contratante depende do ResultadoPatio completo (blocos
# "Outros Serviços — Mídias" e "Carregadores"), que NÃO fica no lançamento
# persistido (só `repasse_outros`) — não há como regenerá-lo só do banco.
_UIDS_PATIO = ("patio_real", "patio_maiojama")


def load_resultado_aprovado(mes_ref: str, uid: str) -> Optional[ResultadoUnidade]:
    """Resultado do lançamento APROVADO da unidade na competência, lido do
    banco. None se não existe lançamento ou se ele não está `aprovado`.
    Nunca consulta valores temporários da sessão."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
            (uid, mes_ref),
        ).fetchone()
    if row is None or row["status"] != "aprovado":
        return None
    return load_resultado_from_db(mes_ref, uid)


def regenerar_pdf_aprovado(mes_ref: str, uid: str) -> str:
    """Regenera o PDF de uma competência JÁ APROVADA preservando a aprovação.

    Não é um fluxo de aprovação: não recalcula, não grava lançamento, saldo
    nem parâmetro, e não mexe em `status`, `last_approved_at`,
    `last_reviewed_at` nem `reopened_*`. O resultado vem EXCLUSIVAMENTE do
    lançamento aprovado persistido (esta função nem recebe um resultado), e a
    configuração é lida sem a semeadura de parâmetros de get_unit_com_params
    (build_report_data(..., somente_leitura=True)).

    Só atualiza `pdf_path` (mesmo caminho), `version` (+1), `last_generated_at`
    e `versions` (o PDF anterior, byte a byte, com status_at_time "aprovado").

    Ordem à prova de falha — o PDF vigente, o status e o histórico de versões
    nunca ficam pior do que estavam:
      1. renderiza para um arquivo TEMPORÁRIO (falha aqui: nada foi tocado);
      2. copia o temporário para a pasta de destino e valida que é um PDF;
      3. arquiva o PDF vigente em versions/;
      4. registra a nova versão no status.json (gravação atômica);
      5. substitui o PDF vigente por os.replace (atômico). Se isso falhar, o
         registro do passo 4 é revertido e o arquivamento descartado.

    Levanta ValueError (sem alterar nada) se o workflow não for `aprovado`, se
    não houver lançamento aprovado, ou para o Pátio (ver _UIDS_PATIO).
    """
    if uid in _UIDS_PATIO:
        raise ValueError(
            "A regeneração do PDF de um Pátio aprovado ainda não está disponível: os blocos de "
            "Mídias e Carregadores não ficam no lançamento aprovado."
        )
    unit_run = get_unit_run(mes_ref, uid)
    if unit_run["status"] != "aprovado":
        raise ValueError(f"Só é possível regenerar o PDF de uma competência aprovada (status atual: '{unit_run['status']}').")
    resultado = load_resultado_aprovado(mes_ref, uid)
    if resultado is None:
        raise ValueError("Lançamento aprovado não encontrado para esta unidade/competência.")

    from app.renderer import OUTPUT_DIR

    html = render_html(build_report_data(resultado, mes_ref, somente_leitura=True))

    _reports_dir(mes_ref).mkdir(parents=True, exist_ok=True)
    _versions_dir(mes_ref).mkdir(parents=True, exist_ok=True)
    pdf_dest = _pdf_path(mes_ref, uid)
    sufixo = f"{os.getpid()}_{int(time.time() * 1000)}"
    nome_render = f"regen_{uid}_{mes_ref}_{sufixo}.pdf"
    render_tmp = Path(OUTPUT_DIR) / nome_render
    dest_tmp = pdf_dest.with_name(f".regen_{uid}_{sufixo}.pdf")

    atual = unit_run.get("pdf_path")
    anterior = {
        "pdf_path": atual,
        "version": unit_run["version"],
        "versions": list(unit_run.get("versions", [])),
        "last_generated_at": unit_run.get("last_generated_at"),
    }
    backup: Optional[Path] = None
    registrado = False
    try:
        export_pdf(html, nome_render)                      # 1) temporário (área do renderer)
        with open(render_tmp, "rb") as f:
            if f.read(5) != b"%PDF-" or os.path.getsize(render_tmp) < 100:
                raise RuntimeError("O PDF gerado é inválido; o PDF vigente foi mantido.")
        shutil.copyfile(render_tmp, dest_tmp)              # 2) mesma pasta/sistema de arquivos do destino

        versions = list(anterior["versions"])
        if atual and Path(atual).exists():                 # 3) arquiva o PDF vigente
            backup = _version_pdf_path(mes_ref, uid, unit_run["version"])
            shutil.copy2(atual, backup)
            versions.append({
                "version": unit_run["version"],
                "pdf_path": str(backup),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "status_at_time": "aprovado",
            })
        _update_unit(mes_ref, uid,                         # 4) SEM `status`
            pdf_path=str(pdf_dest),
            version=unit_run["version"] + 1,
            last_generated_at=datetime.now().isoformat(timespec="seconds"),
            versions=versions,
        )
        registrado = True
        try:
            os.replace(dest_tmp, pdf_dest)                 # 5) substituição atômica
        except BaseException:
            _update_unit(mes_ref, uid, **anterior)         # reverte o registro
            registrado = False
            raise
    except BaseException:
        if backup is not None and not registrado:
            try:
                backup.unlink()
            except OSError:
                pass
        raise
    finally:
        for tmp in (render_tmp, dest_tmp):
            try:
                tmp.unlink()
            except OSError:
                pass
    return str(pdf_dest)


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
