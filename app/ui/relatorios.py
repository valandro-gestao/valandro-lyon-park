"""Tela de relatórios com workflow de status por unidade."""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import streamlit as st

from app import run_manager as rm
from app.calculators.patio import ResultadoPatio
from app.engine import get_unit, get_unidades_ativas, load_units
from app.models import ResultadoUnidade
from app.parsers import faturamento as fat_parser
from app.reporter import build_report_data
from app.renderer import render_html


# ─── helpers ─────────────────────────────────────────────────────────────────

def _fmt(v):
    if v is None:
        return "—"
    s = f"{abs(float(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"(R$ {s})" if float(v) < 0 else f"R$ {s}"


def _ts(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso


def _resultado_para_uid(resultados: dict, uid: str):
    """Retorna (resultado, patio_split_id, patio_resultado) para uma unidade."""
    r = resultados.get(uid)
    if r is None:
        return None, None, None
    if isinstance(r, ResultadoPatio):
        return None, None, r
    return r, None, None


def _uid_list_from_resultados(resultados: dict) -> list[str]:
    """Expande ResultadoPatio em patio_real e patio_maiojama; demais UIDs passam direto."""
    uids = []
    for uid, r in resultados.items():
        if isinstance(r, ResultadoPatio):
            uids.append("patio_real")
            uids.append("patio_maiojama")
        else:
            uids.append(uid)
    return uids


def _generate_for_uid(mes_ref: str, uid: str, resultados: dict) -> str:
    """Gera PDF para um uid (tratando splits do Pátio)."""
    if uid == "patio_real":
        patio_r = resultados.get("patio")
        resultado = rm.load_resultado_from_db(mes_ref, "patio_real") if not patio_r else None
        return rm.generate_report(mes_ref, uid, resultado,
                                  patio_split_id="real", patio_resultado=patio_r)
    if uid == "patio_maiojama":
        patio_r = resultados.get("patio")
        resultado = rm.load_resultado_from_db(mes_ref, "patio_maiojama") if not patio_r else None
        return rm.generate_report(mes_ref, uid, resultado,
                                  patio_split_id="maiojama", patio_resultado=patio_r)
    resultado = resultados.get(uid) or rm.load_resultado_from_db(mes_ref, uid)
    if resultado is None:
        raise ValueError(f"Resultado não encontrado para {uid}")
    return rm.generate_report(mes_ref, uid, resultado)


def _display_name(uid: str) -> str:
    if uid == "patio_real":
        return "Pátio — REAL (53,52%)"
    if uid == "patio_maiojama":
        return "Pátio — MAIOJAMA (46,48%)"
    if uid == "patio_manutencao":
        return "Pátio — Manutenções"
    try:
        return get_unit(uid)["nome"]
    except Exception:
        return uid


# ─── painel de validação ─────────────────────────────────────────────────────

def _painel_validacao(mes_ref: str):
    """Tabela resumo: todas as unidades vs. dados importados vs. status de workflow."""
    import pandas as pd

    fat_data = fat_parser.load(mes_ref)
    uid_map  = fat_data.get("uid_map", {}) if fat_data else {}

    run = rm.load_run(mes_ref)
    unidades = get_unidades_ativas(mes_ref)

    # Monta lista de uids exibíveis (inclui splits do pátio)
    rows = []
    for u in unidades:
        uid = u["id"]
        tipo = u.get("tipo_relatorio", "padrao")

        if u.get("tipo_calculo") == "PATIO_OPERACAO":
            # Pátio expande em 3 linhas: real, maiojama, manutencao (se tiver)
            fat_patio = uid_map.get("patio", uid_map.get(uid))
            for sub_uid, sub_nome in [
                ("patio_real",      "Pátio — REAL"),
                ("patio_maiojama",  "Pátio — MAIOJAMA"),
                ("patio_manutencao","Pátio — Manutenções"),
            ]:
                ur = run.get(sub_uid, {})
                status = ur.get("status", "pendente")
                ts = ur.get("last_generated_at", "")
                pdf_ok = bool(ur.get("pdf_path") and Path(ur["pdf_path"]).exists())
                fat_display = f"R$ {fat_patio:,.2f}" if fat_patio and sub_uid != "patio_manutencao" else "—"
                rows.append({
                    "Unidade": sub_nome,
                    "Tipo": tipo if sub_uid != "patio_manutencao" else "padrao",
                    "Faturamento": fat_display,
                    "Status": rm.status_label(status),
                    "PDF": "✅" if pdf_ok else "—",
                    "Gerado em": ts[:16].replace("T", " ") if ts else "—",
                    "Alerta": "",
                })
            continue

        fat_val = uid_map.get(uid)
        ur = run.get(uid, {})
        status = ur.get("status", "pendente")
        ts = ur.get("last_generated_at", "")
        pdf_ok = bool(ur.get("pdf_path") and Path(ur["pdf_path"]).exists())

        alertas = []
        if fat_data and fat_val is None:
            alertas.append("sem faturamento na planilha")

        rows.append({
            "Unidade": u["nome"],
            "Tipo": tipo,
            "Faturamento": f"R$ {fat_val:,.2f}" if fat_val else "—",
            "Status": rm.status_label(status),
            "PDF": "✅" if pdf_ok else "—",
            "Gerado em": ts[:16].replace("T", " ") if ts else "—",
            "Alerta": " | ".join(alertas),
        })

    # Alertas de itens na planilha sem YAML
    nao_map = fat_data.get("nao_mapeados", []) if fat_data else []
    for item in nao_map:
        rows.append({
            "Unidade": f"[planilha] {item['nome']}",
            "Tipo": "—",
            "Faturamento": f"R$ {item['valor']:,.2f}",
            "Status": "—",
            "PDF": "—",
            "Gerado em": "—",
            "Alerta": "não encontrado no YAML",
        })

    if not rows:
        st.info("Nenhuma unidade ativa encontrada.")
        return

    if not fat_data:
        st.caption("Importe a planilha de faturamentos na tela **Entrada** para ver os valores aqui.")

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Alerta": st.column_config.TextColumn(width="medium"),
            "Faturamento": st.column_config.TextColumn(width="medium"),
        },
    )


# ─── tela principal ───────────────────────────────────────────────────────────

def tela_relatorios(mes_ref: str):
    st.header("Relatórios")

    resultados: dict = st.session_state.get("resultados", {})

    # ── Painel de validação da competência ────────────────────────────────────
    _painel_validacao(mes_ref)
    st.divider()

    # Expande Pátio em dois UIDs separados
    uids = _uid_list_from_resultados(resultados)

    # Carrega status da competência
    run = rm.load_run(mes_ref)

    # ── Barra de resumo ────────────────────────────────────────────────────
    if uids:
        contagem = {}
        for uid in uids:
            s = run.get(uid, {}).get("status", "pendente")
            contagem[s] = contagem.get(s, 0) + 1
        cols = st.columns(len(rm.STATUS_LABELS))
        for i, (status, (icon, label)) in enumerate(rm.STATUS_LABELS.items()):
            n = contagem.get(status, 0)
            cols[i].metric(f"{icon} {label}", n)
        st.divider()

    # ── Ações em massa ─────────────────────────────────────────────────────
    col_gerar, col_zip = st.columns([1, 1])
    with col_gerar:
        if st.button("Gerar todos os pendentes", use_container_width=True):
            _bulk_generate(mes_ref, uids, resultados, run)
            st.rerun()
    with col_zip:
        _download_zip_button(mes_ref, uids, run)

    st.divider()

    if not uids:
        st.info("Calcule os lançamentos na tela de **Entrada** e aprove na **Revisão** primeiro.")
        return

    # ── Cartão por unidade ─────────────────────────────────────────────────
    for uid in uids:
        _unit_card(mes_ref, uid, run, resultados)


# ─── geração em massa ────────────────────────────────────────────────────────

def _bulk_generate(mes_ref, uids, resultados, run):
    pendentes = [uid for uid in uids
                 if run.get(uid, {}).get("status", "pendente") in ("pendente", "erro")]
    if not pendentes:
        st.info("Nenhuma unidade pendente.")
        return

    progress = st.progress(0, text="Gerando PDFs...")
    erros = []
    for i, uid in enumerate(pendentes):
        progress.progress((i + 1) / len(pendentes), text=f"Gerando: {_display_name(uid)}")
        try:
            _generate_for_uid(mes_ref, uid, resultados)
        except Exception as e:
            rm.mark_error(mes_ref, uid, str(e))
            erros.append(f"{uid}: {e}")
    progress.empty()
    if erros:
        st.warning("Erros:\n" + "\n".join(erros))
    else:
        st.success(f"{len(pendentes)} PDF(s) gerado(s).")


# ─── download ZIP ────────────────────────────────────────────────────────────

def _download_zip_button(mes_ref, uids, run):
    aprovados = [
        uid for uid in uids
        if run.get(uid, {}).get("status") in ("gerado", "revisado", "aprovado")
        and run.get(uid, {}).get("pdf_path")
        and Path(run[uid]["pdf_path"]).exists()
    ]
    if not aprovados:
        st.button("Baixar ZIP", disabled=True, use_container_width=True,
                  help="Nenhum PDF disponível ainda.")
        return

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for uid in aprovados:
            p = run[uid]["pdf_path"]
            zf.write(p, Path(p).name)
    buf.seek(0)

    st.download_button(
        label=f"Baixar ZIP ({len(aprovados)} PDFs)",
        data=buf,
        file_name=f"relatorios_lyon_{mes_ref}.zip",
        mime="application/zip",
        use_container_width=True,
    )


# ─── cartão por unidade ───────────────────────────────────────────────────────

def _unit_card(mes_ref: str, uid: str, run: dict, resultados: dict):
    unit_run = run.get(uid, rm._default_unit_run())
    status = unit_run["status"]
    nome = _display_name(uid)
    label = f"{rm.status_label(status)}  ·  **{nome}**"

    with st.expander(label, expanded=(status in ("pendente", "reaberto", "erro"))):

        # ── Info de timestamps ─────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        c1.caption(f"Gerado em\n**{_ts(unit_run.get('last_generated_at'))}**")
        c2.caption(f"Revisado em\n**{_ts(unit_run.get('last_reviewed_at'))}**")
        c3.caption(f"Aprovado em\n**{_ts(unit_run.get('last_approved_at'))}**")
        if unit_run.get("reopened_at"):
            motivo = unit_run.get("reopened_reason") or "—"
            c4.caption(f"Reaberto em\n**{_ts(unit_run['reopened_at'])}**\n_{motivo}_")
        else:
            c4.caption("Reaberto em\n**—**")

        if status == "erro" and unit_run.get("error_message"):
            st.error(f"Erro: {unit_run['error_message']}")

        st.write("")  # espaço

        # ── Ações primárias ───────────────────────────────────────────────
        actions = _actions_for_status(status)
        btn_cols = st.columns(len(actions) + 1)

        for i, (action_id, label_btn, btn_type) in enumerate(actions):
            with btn_cols[i]:
                key = f"{action_id}_{uid}_{mes_ref}"
                clicked = st.button(label_btn, key=key, type=btn_type,
                                    use_container_width=True)
                if clicked:
                    _handle_action(action_id, mes_ref, uid, resultados)
                    st.rerun()

        # Download PDF atual
        pdf_path = unit_run.get("pdf_path")
        if pdf_path and Path(pdf_path).exists():
            with btn_cols[-1]:
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        "⬇ PDF atual",
                        data=f,
                        file_name=Path(pdf_path).name,
                        mime="application/pdf",
                        use_container_width=True,
                        key=f"dl_{uid}_{mes_ref}",
                    )

        # ── Versões históricas ─────────────────────────────────────────────
        versions = unit_run.get("versions", [])
        if versions:
            with st.expander(f"Versões anteriores ({len(versions)})"):
                for v in reversed(versions):
                    vc1, vc2, vc3 = st.columns([1, 2, 1])
                    vc1.write(f"**v{v['version']}**")
                    vc2.write(f"{_ts(v['created_at'])} — {v['status_at_time']}")
                    vp = v.get("pdf_path", "")
                    if vp and Path(vp).exists():
                        with open(vp, "rb") as f:
                            vc3.download_button(
                                "⬇ PDF",
                                data=f,
                                file_name=Path(vp).name,
                                mime="application/pdf",
                                key=f"dl_v{v['version']}_{uid}_{mes_ref}",
                            )
                    else:
                        vc3.caption("Arquivo removido")


def _actions_for_status(status: str) -> list[tuple[str, str, str]]:
    """Retorna lista de (action_id, label, button_type) para o status atual."""
    if status == "pendente":
        return [("generate", "Gerar PDF", "primary")]
    if status == "gerado":
        return [
            ("generate", "Regenerar PDF", "secondary"),
            ("review",   "Marcar como Revisado", "secondary"),
            ("approve",  "Marcar como Aprovado", "primary"),
        ]
    if status == "revisado":
        return [
            ("generate", "Regenerar PDF", "secondary"),
            ("approve",  "Marcar como Aprovado", "primary"),
            ("reopen",   "Reabrir para Edição", "secondary"),
        ]
    if status == "aprovado":
        return [
            ("reopen", "Reabrir para Edição", "secondary"),
        ]
    if status == "reaberto":
        return [
            ("generate", "Gerar novo PDF", "primary"),
        ]
    if status == "erro":
        return [
            ("generate", "Tentar novamente", "primary"),
        ]
    return []


def _handle_action(action_id: str, mes_ref: str, uid: str, resultados: dict):
    if action_id == "generate":
        try:
            _generate_for_uid(mes_ref, uid, resultados)
            st.toast(f"PDF gerado com sucesso.", icon="✅")
        except Exception as e:
            rm.mark_error(mes_ref, uid, str(e))
            st.error(f"Erro ao gerar PDF: {e}")

    elif action_id == "review":
        try:
            rm.mark_reviewed(mes_ref, uid)
            st.toast("Marcado como revisado.", icon="🟡")
        except ValueError as e:
            st.error(str(e))

    elif action_id == "approve":
        try:
            rm.mark_approved(mes_ref, uid)
            st.toast("Aprovado.", icon="🟢")
        except ValueError as e:
            st.error(str(e))

    elif action_id == "reopen":
        # Pede motivo via session_state (diálogo simples)
        st.session_state[f"_reopen_{uid}"] = True

    # Se havia pedido de reabertura pendente, exibir campo motivo
    if st.session_state.get(f"_reopen_{uid}"):
        _reopen_dialog(mes_ref, uid)


def _reopen_dialog(mes_ref: str, uid: str):
    """Exibe campo de motivo e confirma reabertura."""
    with st.form(key=f"form_reopen_{uid}_{mes_ref}"):
        st.warning("Ao reabrir, o relatório voltará ao status **reaberto** e poderá ser editado.")
        motivo = st.text_input("Motivo da reabertura (opcional)")
        col1, col2 = st.columns(2)
        confirmar = col1.form_submit_button("Confirmar reabertura", type="primary")
        cancelar  = col2.form_submit_button("Cancelar")

        if confirmar:
            try:
                rm.reopen(mes_ref, uid, reason=motivo)
                st.session_state.pop(f"_reopen_{uid}", None)
                st.toast("Unidade reaberta para edição.", icon="🔴")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        if cancelar:
            st.session_state.pop(f"_reopen_{uid}", None)
            st.rerun()
