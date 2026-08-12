"""
Tela de Fechamento Mensal — Lyon Park

Fluxo operacional (página única, sem abas):
  Cabeçalho com competência
  Lista de unidades (agrupada por status)
    → Abrir unidade
    → Parâmetros (esq.) | Resultado (dir.)
    → Calcular → Aprovar → retorno automático
"""
from __future__ import annotations

import io, json, os, tempfile, zipfile
from pathlib import Path

import streamlit as st
from streamlit.components.v1 import html as st_html

from app import run_manager as rm
from app.calculators.patio import ResultadoPatio
from app.engine import calcular, get_unit, get_unit_com_params, get_unidades_ativas
from app.models import (
    ResultadoUnidade, get_db, init_db, salvar_lancamento, get_saldo_acumulado,
    salvar_parametros, corrigir_saldo_anual,
)
from app.parsers import eventos as eventos_parser
from app.parsers import faturamento as fat_parser
from app.reporter import build_report_data
from app.renderer import render_html

# ─── CSS global ──────────────────────────────────────────────────────────────

_CSS = """
<style>
/* Remove padding padrão do Streamlit para tela cheia */
.block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; }

/* Tabelas mais compactas */
[data-testid="stDataFrame"] { font-size: 0.82rem; }

/* Métricas menores */
[data-testid="stMetric"] { padding: 0.3rem 0.5rem !important; }
[data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
[data-testid="stMetricValue"] { font-size: 1.05rem !important; }

/* Oculta toolbar do Streamlit */
header[data-testid="stHeader"] { display: none !important; }

/* Cabeçalho fixo */
.lp-header {
    background: #0e1117;
    border-bottom: 2px solid #1f6feb;
    padding: 0.6rem 1.2rem 0.5rem;
    margin: 0 0 0.8rem;
    display: flex;
    align-items: center;
    gap: 1.5rem;
}
.lp-header h2 { margin: 0; font-size: 1.1rem; color: #e6e6e6; letter-spacing: .02em; }
.lp-header .comp { font-size: 0.9rem; color: #8b9fc1; }
.lp-header .status-pill {
    background: #1f6feb22;
    border: 1px solid #1f6feb55;
    border-radius: 20px;
    padding: 0.15rem 0.7rem;
    font-size: 0.78rem;
    color: #79b8ff;
}

/* Badge de status inline */
.badge-pend  { color: #8b9fc1; }
.badge-gerado { color: #388bfd; }
.badge-rev   { color: #d29922; }
.badge-aprov { color: #3fb950; font-weight: 600; }
.badge-reab  { color: #f85149; }
.badge-erro  { color: #f85149; }

/* Linha da lista: menos altura */
.unit-row { padding: 0.15rem 0; border-bottom: 1px solid #21262d; }

/* Destaque de parâmetro alterado */
.param-changed input {
    border-color: #d29922 !important;
    background-color: #2b2209 !important;
}
.changed-label { color: #d29922; font-size: 0.72rem; }

/* Seção compacta */
.section-title {
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: #8b9fc1;
    margin: 0.6rem 0 0.25rem;
}

/* Histórico tabela */
.hist-table th { background: #161b22; font-size: 0.75rem; }
.hist-table td { font-size: 0.8rem; }
</style>
"""


# ─── helpers ─────────────────────────────────────────────────────────────────

_MESES = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
           "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

def _mes_label(mes_ref: str) -> str:
    ano, mes = mes_ref.split("-")
    return f"{_MESES[int(mes)-1]} / {ano}"


def _fmt(v: float | None, signed: bool = False) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if v < 0:
        return f"(R$ {s})"
    return f"R$ {s}"


def _ts(ts: str | None) -> str:
    if not ts:
        return "—"
    return ts[:16].replace("T", " ")


def _display_name(uid: str) -> str:
    if uid == "patio_real":
        return "Pátio — REAL (53,52%)"
    if uid == "patio_maiojama":
        return "Pátio — MAIOJAMA (46,48%)"
    try:
        return get_unit(uid)["nome"]
    except Exception:
        return uid


def _pior_status(statuses: list[str]) -> str:
    ordem = ["erro", "pendente", "reaberto", "gerado", "revisado", "aprovado"]
    for s in ordem:
        if s in statuses:
            return s
    return "pendente"


def _report_uids_of(uid: str) -> list[str]:
    try:
        cfg = get_unit(uid)
    except Exception:
        return [uid]
    if cfg.get("tipo_calculo") == "PATIO_OPERACAO":
        return ["patio_real", "patio_maiojama"]
    return [uid]


def _status_badge(status: str) -> str:
    icones = {
        "pendente": ("🔘", "Pendente"),
        "gerado":   ("🔵", "Gerado"),
        "revisado": ("🟡", "Revisado"),
        "aprovado": ("🟢", "Aprovado"),
        "reaberto": ("🔴", "Reaberto"),
        "erro":     ("❌", "Erro"),
    }
    ic, txt = icones.get(status, ("🔘", status.title()))
    return f"{ic} {txt}"


def _custo_label(k: str) -> str:
    labels = {
        "condominio": "Condomínio",
        "iptu": "IPTU",
        "energia_eletrica": "Energia Elétrica",
        "sistema_perto": "Sistema Perto",
        "sistema_automacao": "Sistema Automação",
        "monitoramento": "Monitoramento",
        "aucon": "Aucon / Equip.",
        "instalacoes": "Manutenção Instalações",
        "investimentos": "Investimentos",
        "fundo_recomposicao": "Fundo Recomposição",
        "agua": "Água",
        "internet": "Internet",
        "manutencao_equipamentos": "Manutenção Equip.",
    }
    return labels.get(k, k.replace("_", " ").title())


def _custo_label_ui(k: str) -> str:
    return _custo_label(k) + " (R$)"


# ─── histórico da unidade por lançamentos ────────────────────────────────────

def _get_historico_lancamentos(uid: str) -> list[dict]:
    """Retorna lançamentos históricos do banco, ordenados por competência."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT mes_referencia, resultado_json
               FROM lancamentos
               WHERE unidade_id = ?
               ORDER BY mes_referencia""",
            (uid,)
        ).fetchall()
    result = []
    for r in rows:
        try:
            d = json.loads(r["resultado_json"])
            result.append({"mes_ref": r["mes_referencia"], **d})
        except Exception:
            pass
    return result


def _get_params_competencia(uid: str, mes_ref: str) -> dict:
    """Retorna parâmetros vigentes planos (dot-notation) para uma competência."""
    from app.models import get_parametros_vigentes
    params = {}
    vigentes = get_parametros_vigentes(uid, mes_ref)
    # Flatten de volta para dot-notation
    def _flatten(d: dict, prefix: str = ""):
        for k, v in d.items():
            chave = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                _flatten(v, chave)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                params[chave] = v
    _flatten(vigentes)
    return params


def _params_anteriores(uid: str, mes_ref: str) -> dict:
    """Parâmetros vigentes na competência anterior."""
    ano, mes = int(mes_ref[:4]), int(mes_ref[5:7])
    if mes == 1:
        mes_ant = f"{ano-1}-12"
    else:
        mes_ant = f"{ano}-{mes-1:02d}"
    return _get_params_competencia(uid, mes_ant)


# ─── entrada principal ────────────────────────────────────────────────────────

def tela_fechamento(mes_ref: str):
    st.markdown(_CSS, unsafe_allow_html=True)
    _init_state()

    if st.session_state.get("selected_unit"):
        _tela_detalhe(mes_ref)
    else:
        _tela_lista(mes_ref)


# ═══════════════════════════════════════════════════════════════════════════════
# TELA DE LISTA
# ═══════════════════════════════════════════════════════════════════════════════

def _tela_lista(mes_ref: str):
    # ── Cabeçalho com seletor de competência ─────────────────────────────────
    from datetime import date
    hoje = date.today()

    c_titulo, c_ano, c_mes, c_espacador = st.columns([4, 1, 2, 3])
    with c_titulo:
        st.markdown("## Fechamento Mensal")
    with c_ano:
        anos = list(range(2024, hoje.year + 2))
        ano_idx = anos.index(st.session_state.get("sel_ano", hoje.year))
        novo_ano = st.selectbox("Ano", anos, index=ano_idx, key="hdr_ano", label_visibility="collapsed")
        if novo_ano != st.session_state.get("sel_ano"):
            st.session_state.sel_ano = novo_ano
            st.rerun()
    with c_mes:
        meses_opt = list(range(1, 13))
        mes_idx = meses_opt.index(st.session_state.get("sel_mes", hoje.month))
        novo_mes = st.selectbox(
            "Mês", meses_opt, index=mes_idx,
            format_func=lambda m: _MESES[m-1],
            key="hdr_mes", label_visibility="collapsed",
        )
        if novo_mes != st.session_state.get("sel_mes"):
            st.session_state.sel_mes = novo_mes
            st.rerun()

    st.caption(f"Competência: **{_mes_label(mes_ref)}**")
    st.divider()

    unidades = get_unidades_ativas(mes_ref)
    run = rm.load_run(mes_ref)
    fat_data = fat_parser.load(mes_ref)
    uid_map = fat_data.get("uid_map", {}) if fat_data else {}

    # ── Planilhas ─────────────────────────────────────────────────────────────
    with st.expander("📁 Planilhas da competência", expanded=not fat_data):
        _secao_uploads(mes_ref, unidades, fat_data)

    # ── Métricas coerentes com a lista ────────────────────────────────────────
    _metricas_lista(unidades, run)

    # ── Ações em massa ────────────────────────────────────────────────────────
    todos_uids: list[str] = []
    for u in unidades:
        todos_uids.extend(_report_uids_of(u["id"]))

    ca, cb, cc = st.columns([2, 2, 2])
    with ca:
        if st.button("⚡ Gerar pendentes", use_container_width=True):
            _gerar_pendentes(mes_ref, todos_uids)
            st.rerun()
    with cb:
        if st.button("✅ Aprovar todos gerados", use_container_width=True):
            _aprovar_todos_gerados(mes_ref, todos_uids)
            st.rerun()
    with cc:
        _download_zip(mes_ref, todos_uids, run)

    st.divider()

    # ── Lista agrupada ────────────────────────────────────────────────────────
    _lista_unidades_agrupada(mes_ref, unidades, uid_map, run)


def _metricas_lista(unidades: list, run: dict):
    """Calcula métricas a partir das mesmas unidades exibidas na lista."""
    contagem = {"pendente": 0, "gerado": 0, "revisado": 0, "aprovado": 0, "reaberto": 0, "erro": 0}
    total = 0
    for u in unidades:
        report_uids = _report_uids_of(u["id"])
        for r_uid in report_uids:
            total += 1
            s = run.get(r_uid, {}).get("status", "pendente")
            contagem[s] = contagem.get(s, 0) + 1

    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    mc1.metric("Total", total)
    mc2.metric("🔘 Pendentes", contagem["pendente"])
    mc3.metric("🔵 Gerados", contagem["gerado"])
    mc4.metric("🟡 Revisados", contagem["revisado"])
    mc5.metric("🟢 Aprovados", contagem["aprovado"])
    mc6.metric("🔴 Reabertos / Erros", contagem["reaberto"] + contagem["erro"])


def _lista_unidades_agrupada(mes_ref: str, unidades: list, uid_map: dict, run: dict):
    grupos: dict[str, list] = {"pendente": [], "andamento": [], "aprovado": []}

    for u in unidades:
        report_uids = _report_uids_of(u["id"])
        statuses = [run.get(r, {}).get("status", "pendente") for r in report_uids]
        s = _pior_status(statuses)
        if s == "aprovado":
            grupos["aprovado"].append((u, s))
        elif s in ("gerado", "revisado"):
            grupos["andamento"].append((u, s))
        else:
            grupos["pendente"].append((u, s))

    def _render_grupo(items, titulo, expandido, is_aprovado=False):
        if not items:
            return
        with st.expander(f"{titulo}  ({len(items)})", expanded=expandido):
            _cabecalho_lista(is_aprovado)
            for u, status in items:
                _linha_unidade(mes_ref, u, status, uid_map, run)

    _render_grupo(grupos["pendente"], "🔘 Pendentes", True)
    _render_grupo(grupos["andamento"], "🔵 Em andamento", True)
    _render_grupo(grupos["aprovado"], "🟢 Aprovadas", False, is_aprovado=True)


def _cabecalho_lista(tem_pdf: bool = False):
    cols = [4, 2, 2, 3] if not tem_pdf else [4, 2, 2, 1, 3]
    h = st.columns(cols)
    h[0].caption("**Unidade**")
    h[1].caption("**Faturamento**")
    h[2].caption("**Status**")
    if tem_pdf:
        h[3].caption("**PDF**")
        h[4].caption("**Ações**")
    else:
        h[3].caption("**Ações**")


def _linha_unidade(mes_ref: str, u: dict, status: str, uid_map: dict, run: dict):
    uid = u["id"]
    fat = uid_map.get(uid)
    report_uids = _report_uids_of(uid)
    is_aprovado = status == "aprovado"

    alertas = []
    if uid_map and fat is None and uid != "patio":
        alertas.append("sem fat.")
    if u.get("tipo_relatorio") == "com_eventos":
        if eventos_parser.load_uid(mes_ref, uid) is None:
            alertas.append("sem eventos")

    nome_exib = u["nome"]
    if alertas:
        nome_exib += "  ⚠"

    if is_aprovado:
        row = st.columns([4, 2, 2, 1, 3])
    else:
        row = st.columns([4, 2, 2, 3])

    row[0].write(f"**{nome_exib}**")
    if alertas:
        row[0].caption("  ⚠ " + " | ".join(alertas))
    row[1].write(_fmt(fat) if fat else "—")
    row[2].write(_status_badge(status))

    if is_aprovado:
        # Coluna PDF para unidades aprovadas
        pdf_path = run.get(report_uids[0], {}).get("pdf_path")
        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                row[3].download_button(
                    "⬇", data=f,
                    file_name=Path(pdf_path).name,
                    mime="application/pdf",
                    key=f"lst_dl_{uid}_{mes_ref}",
                    use_container_width=True,
                )
        else:
            row[3].write("—")

        with row[4]:
            bc = st.columns(2)
            if bc[0].button("Abrir", key=f"open_{uid}_{mes_ref}", use_container_width=True):
                st.session_state.selected_unit = uid
                st.rerun()
            if bc[1].button("↩ Reabrir", key=f"reab_{uid}_{mes_ref}", use_container_width=True):
                for r in report_uids:
                    try:
                        rm.reopen(mes_ref, r)
                    except Exception:
                        pass
                st.rerun()
    else:
        with row[3]:
            bc = st.columns(2)
            if bc[0].button("Abrir", key=f"open_{uid}_{mes_ref}", use_container_width=True):
                st.session_state.selected_unit = uid
                st.rerun()
            if status in ("gerado", "revisado"):
                if bc[1].button("✅ Aprovar", key=f"qaprov_{uid}_{mes_ref}",
                                 use_container_width=True, type="primary"):
                    for r in report_uids:
                        try:
                            rm.mark_approved(mes_ref, r)
                        except Exception:
                            pass
                    st.rerun()
            else:
                bc[1].write("")


# ═══════════════════════════════════════════════════════════════════════════════
# TELA DE DETALHE
# ═══════════════════════════════════════════════════════════════════════════════

def _tela_detalhe(mes_ref: str):
    uid = st.session_state.selected_unit

    try:
        u_base = get_unit(uid)
    except KeyError:
        st.error(f"Unidade '{uid}' não encontrada.")
        if st.button("← Voltar"):
            st.session_state.selected_unit = None
            st.rerun()
        return

    run = rm.load_run(mes_ref)
    resultados = st.session_state.get("resultados", {})
    fat_data = fat_parser.load(mes_ref)
    uid_map = fat_data.get("uid_map", {}) if fat_data else {}
    is_patio = u_base.get("tipo_calculo") == "PATIO_OPERACAO"

    # Carrega parâmetros vigentes (DB > YAML)
    u = get_unit_com_params(uid, mes_ref)

    report_uids = _report_uids_of(uid)
    statuses = [run.get(r, {}).get("status", "pendente") for r in report_uids]
    status = _pior_status(statuses)

    # ── Cabeçalho da unidade ─────────────────────────────────────────────────
    hc1, hc2 = st.columns([1, 9])
    with hc1:
        if st.button("← Voltar", use_container_width=True, key="btn_voltar"):
            st.session_state.selected_unit = None
            st.rerun()
    with hc2:
        nome_exib = "Pátio — Operação" if is_patio else u["nome"]
        st.markdown(f"### {nome_exib}")
        info_line = f"**{_mes_label(mes_ref)}**  ·  {_status_badge(status)}"
        if u.get("contratante"):
            info_line += f"  ·  {u['contratante']}"
        st.caption(info_line)

    # Alerta de reajuste
    reajuste_mes = u.get("reajuste_mes")
    if reajuste_mes and int(mes_ref.split("-")[1]) == int(reajuste_mes):
        st.warning(f"⚠ Mês de reajuste contratual — verifique o novo Ponto de Equilíbrio antes de calcular.")

    st.divider()

    if is_patio:
        _detalhe_patio(uid, u, mes_ref, uid_map, resultados, run, status)
    else:
        _detalhe_simples(uid, u, mes_ref, uid_map, resultados, run, status)


# ─── detalhe: unidade simples ─────────────────────────────────────────────────

def _detalhe_simples(uid: str, u: dict, mes_ref: str,
                     uid_map: dict, resultados: dict, run: dict, status: str):
    tc = u.get("tipo_calculo", "")
    fat_importado = uid_map.get(uid)
    params_ant = _params_anteriores(uid, mes_ref)
    params_atual = _get_params_competencia(uid, mes_ref)

    def _alterado(chave: str) -> bool:
        """True se o parâmetro mudou em relação à competência anterior."""
        ant = params_ant.get(chave)
        atu = params_atual.get(chave)
        if ant is None or atu is None:
            return False
        return abs(float(ant) - float(atu)) > 0.001

    # ── Faixa de dados importados ─────────────────────────────────────────────
    st.markdown('<p class="section-title">Dados Importados</p>', unsafe_allow_html=True)
    di_cols = st.columns(4)
    di_cols[0].metric("Faturamento", _fmt(fat_importado) if fat_importado else "—")
    if tc in ("COM_ALIQUOTA_CUMUL", "PATIO_MANUTENCAO"):
        saldo = get_saldo_acumulado(uid)
        di_cols[1].metric("Saldo Acumulado", _fmt(saldo))

    # Eventos
    ev_total = 0.0
    if u.get("tipo_relatorio") == "com_eventos":
        ev = eventos_parser.load_uid(mes_ref, uid)
        if ev:
            ev_total = eventos_parser.get_total_competencia(ev, mes_ref)
            ev_mes = eventos_parser.get_eventos_competencia(ev, mes_ref)
            di_cols[2].metric("Eventos", _fmt(ev_total), f"{len(ev_mes)} eventos")
        else:
            di_cols[2].error("Eventos não carregados")

    # Correção IPCA (MW Tristeza em janeiro)
    if u.get("prejuizo_correcao_anual") and int(mes_ref.split("-")[1]) == 1:
        saldo_atual = get_saldo_acumulado(uid)
        if saldo_atual < 0:
            with st.expander(f"⚠ Correção anual IPCA — saldo: {_fmt(saldo_atual)}", expanded=True):
                ipca_pct = st.number_input(
                    "IPCA do ano anterior (%)",
                    min_value=0.0, max_value=50.0, step=0.01, format="%.2f",
                    key=f"ipca_corr_{uid}",
                )
                if st.button("Aplicar correção", key=f"btn_ipca_{uid}", type="primary"):
                    novo = corrigir_saldo_anual(uid, ipca_pct / 100.0)
                    st.success(f"Saldo corrigido: {_fmt(novo)}")
                    st.rerun()

    # ── Layout: Parâmetros (esq) | Resultado (dir) ───────────────────────────
    col_p, col_r = st.columns([3, 2], gap="large")

    with col_p:
        st.markdown('<p class="section-title">Parâmetros</p>', unsafe_allow_html=True)
        fat, pe_override, custos_extras = _inputs_parametros(
            uid, u, mes_ref, fat_importado, _alterado
        )
        if ev_total > 0:
            custos_extras["custos_eventos"] = ev_total

    with col_r:
        st.markdown('<p class="section-title">Resultado</p>', unsafe_allow_html=True)
        r = resultados.get(uid) or rm.load_resultado_from_db(mes_ref, uid)
        if r is None:
            st.info("Preencha os parâmetros e clique em **Calcular**.")
        else:
            _mostrar_resultado_unit(r)

    # ── Barra de ações (rodapé) ───────────────────────────────────────────────
    st.divider()
    _barra_acoes_simples(mes_ref, uid, u, fat, pe_override, custos_extras, resultados, run)

    # ── Histórico da unidade ──────────────────────────────────────────────────
    st.divider()
    _secao_historico(uid)


def _inputs_parametros(uid: str, u: dict, mes_ref: str,
                        fat_importado: float | None,
                        _alterado) -> tuple[float, float | None, dict]:
    tc = u.get("tipo_calculo", "")
    custos_extras: dict = {}

    # Faturamento
    fat_val = st.session_state.get(
        f"fat_{uid}",
        st.session_state.get("faturamentos", {}).get(uid, fat_importado or 0.0),
    )
    fat = st.number_input(
        "Faturamento (R$)",
        min_value=0.0, step=100.0, format="%.2f",
        value=float(fat_val), key=f"fat_{uid}",
    )

    if u.get("tem_faturamento_carregadores"):
        fat_car = st.number_input(
            "Faturamento Carregadores (R$)",
            min_value=0.0, step=100.0, format="%.2f",
            value=float(st.session_state.get(f"fat_car_{uid}", 0.0)),
            key=f"fat_car_{uid}",
        )
        if fat_car > 0:
            custos_extras["fat_carregadores"] = fat_car

    # Ponto de Equilíbrio
    pe_default = float(u.get("ponto_equilibrio", 0.0))
    has_pe = pe_default > 0 or tc in (
        "COM_ALIQUOTA", "COM_ALIQUOTA_CUMUL", "COM_ALIQUOTA_SPLIT",
        "COM_FAIXAS", "PERCENTUAL_SIMPLES", "COM_ALIQUOTA_REPASSE_DUPLO",
    )
    pe_override = None
    if has_pe and tc != "PATIO_MANUTENCAO":
        pe_alt = _alterado("ponto_equilibrio")
        label_pe = "Ponto de Equilíbrio (R$)"
        pe_override = st.number_input(
            label_pe,
            min_value=0.0, step=100.0, format="%.2f",
            value=float(st.session_state.get(f"pe_{uid}", pe_default)),
            key=f"pe_{uid}",
        )
        if pe_alt:
            st.caption("⚠️ Alterado em relação à competência anterior",
                        help="Este valor difere do mês anterior")

    # Base de Cálculo Taxa de Cobrança
    if u.get("tem_base_taxa_cobranca"):
        base_tc = st.number_input(
            f"Base Cálculo Taxa Cobrança (R$)",
            min_value=0.0, step=100.0, format="%.2f",
            value=float(st.session_state.get(f"base_tc_{uid}", fat_importado or 0.0)),
            key=f"base_tc_{uid}",
            help=f"Aplica-se {u.get('taxa_cobranca', 0)*100:.1f}%",
        )
        custos_extras["base_calculo_taxa_cobranca"] = base_tc

    # Custos mensais
    custos_mensais = u.get("custos_mensais") or {}
    if custos_mensais:
        st.caption("**Custos mensais:**")
        n = min(3, len(custos_mensais))
        cc = st.columns(n)
        for i, (k, v) in enumerate(custos_mensais.items()):
            chave_db = f"custos_mensais.{k}"
            alt = _alterado(chave_db)
            with cc[i % n]:
                val = st.number_input(
                    _custo_label_ui(k),
                    min_value=0.0, step=10.0, format="%.2f",
                    value=float(st.session_state.get(f"custo_{uid}_{k}", v)),
                    key=f"custo_{uid}_{k}",
                )
                if alt:
                    st.caption("⚠️ Alterado")
                custos_extras[k] = val

    # Custos variáveis
    custos_variaveis = u.get("custos_variaveis") or {}
    if custos_variaveis:
        st.caption("**Custos variáveis:**")
        n = min(3, len(custos_variaveis))
        cv = st.columns(n)
        for i, (k, v) in enumerate(custos_variaveis.items()):
            chave_db = f"custos_variaveis.{k}"
            alt = _alterado(chave_db)
            with cv[i % n]:
                val = st.number_input(
                    _custo_label_ui(k),
                    min_value=0.0, step=10.0, format="%.2f",
                    value=float(st.session_state.get(f"cv_{uid}_{k}", v)),
                    key=f"cv_{uid}_{k}",
                )
                if alt:
                    st.caption("⚠️ Alterado")
                custos_extras[k] = val

    return fat, pe_override, custos_extras


def _barra_acoes_simples(mes_ref: str, uid: str, u: dict,
                          fat: float, pe_override: float | None, custos_extras: dict,
                          resultados: dict, run: dict):
    unit_run = rm.get_unit_run(mes_ref, uid)
    status = unit_run["status"]

    ac1, ac2, ac3, ac4, ac5 = st.columns([2, 2, 2, 2, 2])

    # Recalcular
    with ac1:
        if st.button("⚙️ Calcular", key=f"act_calc_{uid}", use_container_width=True,
                     type="primary" if status in ("pendente", "reaberto") else "secondary"):
            if fat <= 0:
                st.error("Informe o faturamento.")
            else:
                try:
                    ev_total = custos_extras.get("custos_eventos", 0.0)
                    resultado = calcular(uid, mes_ref, fat,
                                         custos_extras=custos_extras or None,
                                         pe_override=pe_override)
                    _salvar_resultado_session(uid, fat, resultado)
                    st.session_state[f"params_usados_{uid}"] = _coletar_params_usados(
                        uid, u, pe_override, custos_extras)
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

    # Gerar PDF
    with ac2:
        if st.button("📄 Gerar PDF", key=f"act_pdf_{uid}", use_container_width=True):
            r = resultados.get(uid) or rm.load_resultado_from_db(mes_ref, uid)
            if r is None:
                st.error("Calcule antes de gerar o PDF.")
            else:
                try:
                    rm.generate_report(mes_ref, uid, r)
                    st.success("PDF gerado.")
                    st.rerun()
                except Exception as e:
                    rm.mark_error(mes_ref, uid, str(e))
                    st.error(f"Erro: {e}")

    # Download PDF (se existir)
    with ac3:
        pdf_path = unit_run.get("pdf_path")
        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                st.download_button(
                    "⬇ Baixar PDF", data=f,
                    file_name=Path(pdf_path).name,
                    mime="application/pdf",
                    key=f"act_dl_{uid}",
                    use_container_width=True,
                )

    # Aprovar (PDF + salva + parâmetros + aprovação + volta)
    with ac4:
        if status in ("pendente", "gerado", "revisado", "reaberto", "erro"):
            if st.button("✅ Aprovar", key=f"act_apr_{uid}",
                         type="primary", use_container_width=True):
                r = resultados.get(uid) or rm.load_resultado_from_db(mes_ref, uid)
                if r is None:
                    st.error("Calcule antes de aprovar.")
                else:
                    try:
                        r.status = "aprovado"
                        r.mes_referencia = mes_ref
                        salvar_lancamento(r)
                        rm.generate_report(mes_ref, uid, r)
                        params = st.session_state.get(f"params_usados_{uid}")
                        if not params:
                            from app.models import _extrair_editaveis
                            u_cfg = get_unit_com_params(uid, mes_ref)
                            params = {}
                            _extrair_editaveis(u_cfg, params)
                        if params:
                            salvar_parametros(uid, mes_ref, params, alterado_por="aprovacao")
                        rm.mark_approved(mes_ref, uid)
                        st.session_state.selected_unit = None
                        st.rerun()
                    except Exception as e:
                        rm.mark_error(mes_ref, uid, str(e))
                        st.error(f"Erro na aprovação: {e}")

    # Reabrir
    with ac5:
        if status == "aprovado":
            if st.button("↩ Reabrir", key=f"act_reab_{uid}", use_container_width=True):
                try:
                    rm.reopen(mes_ref, uid)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    # Histórico de workflow (colapsado)
    with st.expander("Histórico de versões", expanded=False):
        tc1, tc2, tc3 = st.columns(3)
        tc1.caption(f"Gerado: {_ts(unit_run.get('last_generated_at'))}")
        tc2.caption(f"Revisado: {_ts(unit_run.get('last_reviewed_at'))}")
        tc3.caption(f"Aprovado: {_ts(unit_run.get('last_approved_at'))}")
        versions = unit_run.get("versions", [])
        for v in reversed(versions):
            vc1, vc2, vc3 = st.columns([1, 3, 1])
            vc1.caption(f"v{v['version']}")
            vc2.caption(f"{_ts(v['created_at'])} — {v['status_at_time']}")
            vp = v.get("pdf_path", "")
            if vp and Path(vp).exists():
                with open(vp, "rb") as f:
                    vc3.download_button("⬇", data=f, file_name=Path(vp).name,
                                        mime="application/pdf",
                                        key=f"dl_v{v['version']}_{uid}")


# ─── histórico da unidade ─────────────────────────────────────────────────────

def _secao_historico(uid: str):
    import pandas as pd

    lancamentos = _get_historico_lancamentos(uid)
    if not lancamentos:
        with st.expander("📊 Histórico da unidade", expanded=False):
            st.caption("Nenhum fechamento registrado ainda.")
        return

    # Monta DRE na mesma ordem de _mostrar_resultado_unit
    # Cada entrada: (chave_ou_label, callback(lancamento) -> valor_formatado)
    def _v(l, key):
        v = l.get(key)
        return _fmt(v) if isinstance(v, (int, float)) else "—"

    def _build_dre_rows(lancamentos):
        linhas = []  # list of (label, key_or_fn)

        # Receita Bruta / Subtotal (se houver impostos)
        tem_subtotal = any(
            l.get("subtotal") and l.get("subtotal") != l.get("faturamento")
            for l in lancamentos
        )
        if tem_subtotal:
            linhas.append(("Receita Bruta",         lambda l: _v(l, "faturamento")))
            linhas.append(("(-) Impostos / ISS",    lambda l: _fmt(
                (l.get("faturamento") or 0) - (l.get("subtotal") or 0)
                if isinstance(l.get("faturamento"), (int, float))
                   and isinstance(l.get("subtotal"), (int, float))
                else None
            )))
            linhas.append(("Subtotal",               lambda l: _v(l, "subtotal")))
        else:
            linhas.append(("Faturamento",            lambda l: _v(l, "faturamento")))

        # Ponto de Equilíbrio
        tem_pe = any(l.get("ponto_equilibrio") for l in lancamentos)
        if tem_pe:
            linhas.append(("(-) Ponto de Equilíbrio", lambda l: _v(l, "ponto_equilibrio")))

        # Custos — em ordem de aparição no primeiro lançamento que os tenha
        custos_keys: list[str] = []
        for l in lancamentos:
            for k in (l.get("custos") or {}):
                if k not in custos_keys:
                    custos_keys.append(k)
        for k in custos_keys:
            label = f"(-) {_custo_label(k)}"
            k_cap = k  # capture
            linhas.append((label, lambda l, kk=k_cap: _fmt(
                (l.get("custos") or {}).get(kk)
            )))

        # Resultado e aluguel
        linhas.append(("Resultado",               lambda l: _v(l, "resultado")))
        linhas.append(("Aluguel/Repasse",         lambda l: _v(l, "aluguel_calculado")))

        return linhas

    dre_linhas = _build_dre_rows(lancamentos)

    rows = []
    for label, fn in dre_linhas:
        row = {"Indicador": label}
        for l in lancamentos:
            row[_mes_label(l["mes_ref"])] = fn(l)
        rows.append(row)

    df = pd.DataFrame(rows).set_index("Indicador")

    with st.expander(f"📊 Histórico da unidade  ({len(lancamentos)} competência(s))", expanded=False):
        st.dataframe(df, use_container_width=True)

        # Exportar CSV
        csv = df.to_csv().encode("utf-8")
        st.download_button(
            "⬇ Exportar CSV",
            data=csv,
            file_name=f"historico_{uid}.csv",
            mime="text/csv",
            key=f"csv_hist_{uid}",
        )


# ─── detalhe: pátio ──────────────────────────────────────────────────────────

def _detalhe_patio(uid: str, u: dict, mes_ref: str,
                   uid_map: dict, resultados: dict, run: dict, status: str):
    fat_importado = uid_map.get("patio")

    st.markdown('<p class="section-title">Dados Importados</p>', unsafe_allow_html=True)
    st.metric("Faturamento Total (Planilha)", _fmt(fat_importado) if fat_importado else "—")
    st.divider()

    col_p, col_r = st.columns([3, 2], gap="large")

    with col_p:
        st.markdown('<p class="section-title">Parâmetros</p>', unsafe_allow_html=True)

        fat_val = st.session_state.get(
            "fat_patio",
            st.session_state.get("faturamentos", {}).get("patio", fat_importado or 0.0),
        )
        fat = st.number_input("Faturamento total (R$)", min_value=0.0, step=100.0,
                               format="%.2f", value=float(fat_val), key="fat_patio")

        st.caption("**Outros Serviços**")
        c1, c2, c3 = st.columns(3)
        midia = c1.number_input("Mídias", min_value=0.0, step=100.0, format="%.2f", key="fp_midia")
        eq    = c2.number_input("Equip.", min_value=0.0, step=100.0, format="%.2f", key="fp_eq")
        lona  = c3.number_input("Lona",   min_value=0.0, step=100.0, format="%.2f", key="fp_lona")

        st.caption("**Carregadores**")
        c1, c2, c3, c4 = st.columns(4)
        rec_car   = c1.number_input("Receita",    min_value=0.0, step=100.0, format="%.2f", key="fp_rec_car")
        en        = c2.number_input("Energia",    min_value=0.0, step=10.0,  format="%.2f", key="fp_energia")
        inv_car   = c3.number_input("Investim.",  min_value=0.0, step=100.0, format="%.2f", key="fp_inv_car")
        saldo_car = c4.number_input("Saldo ant.", step=100.0, format="%.2f",               key="fp_saldo_car")

        st.caption("**Custos Variáveis**")
        c1, c2 = st.columns(2)
        with c1:
            st.caption("REAL")
            cond_real = st.number_input("Condomínio", min_value=0.0, step=10.0, format="%.2f", key="fp_cond_r")
        with c2:
            st.caption("MAIOJAMA")
            cond_mj = st.number_input("Condomínio", min_value=0.0, step=10.0, format="%.2f", key="fp_cond_m")
            iptu_mj = st.number_input("IPTU",       min_value=0.0, step=10.0, format="%.2f", key="fp_iptu_m")

    with col_r:
        st.markdown('<p class="section-title">Resultado</p>', unsafe_allow_html=True)
        r = resultados.get("patio")
        if r is None:
            st.info("Preencha os dados e clique em **Calcular**.")
        elif isinstance(r, ResultadoPatio):
            _mostrar_resultado_patio(r)

    st.divider()

    # Barra de ações do pátio
    act1, act2 = st.columns(2)
    with act1:
        if st.button("⚙️ Calcular Pátio", type="primary", key="calc_patio", use_container_width=True):
            if fat <= 0:
                st.error("Informe o faturamento.")
            else:
                try:
                    extras = {
                        "receitas_midia": midia,
                        "outros_custos_midia": {"investimentos_equipamentos": eq, "troca_de_lona": lona},
                        "receita_carregadores": rec_car,
                        "custo_energia_carregadores": en,
                        "investimento_inicial_carregadores": inv_car,
                        "saldo_carregadores": saldo_car,
                        "custos_variaveis_real": {"condominio": cond_real},
                        "custos_variaveis_maiojama": {"condominio": cond_mj, "iptu": iptu_mj},
                    }
                    resultado = calcular("patio", mes_ref, fat, extras_patio=extras)
                    _salvar_resultado_session("patio", fat, resultado)
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

    st.divider()
    _barra_acoes_patio(mes_ref, resultados, run)


def _barra_acoes_patio(mes_ref: str, resultados: dict, run: dict):
    r_patio = resultados.get("patio")
    for sub_uid, split_id in [("patio_real", "real"), ("patio_maiojama", "maiojama")]:
        ur = rm.get_unit_run(mes_ref, sub_uid)
        status = ur["status"]
        st.markdown(f"**{_display_name(sub_uid)}**  ·  {_status_badge(status)}")

        bc1, bc2, bc3, bc4 = st.columns(4)
        with bc1:
            if st.button("📄 Gerar PDF", key=f"wf_gen_{sub_uid}", use_container_width=True):
                r_db = rm.load_resultado_from_db(mes_ref, sub_uid)
                try:
                    rm.generate_report(mes_ref, sub_uid, r_db,
                                       patio_split_id=split_id, patio_resultado=r_patio)
                    st.success(f"PDF gerado.")
                    st.rerun()
                except Exception as e:
                    rm.mark_error(mes_ref, sub_uid, str(e))
                    st.error(f"Erro: {e}")

        with bc2:
            pdf_path = ur.get("pdf_path")
            if pdf_path and Path(pdf_path).exists():
                with open(pdf_path, "rb") as f:
                    st.download_button("⬇ PDF", data=f, file_name=Path(pdf_path).name,
                                       mime="application/pdf",
                                       key=f"wf_dl_{sub_uid}", use_container_width=True)

        with bc3:
            if status in ("pendente", "gerado", "revisado", "reaberto", "erro") and r_patio:
                if st.button("✅ Aprovar", key=f"wf_apr_{sub_uid}",
                             type="primary", use_container_width=True):
                    split_r = r_patio.real if split_id == "real" else r_patio.maiojama
                    split_r.status = "aprovado"
                    split_r.mes_referencia = mes_ref
                    salvar_lancamento(split_r)
                    try:
                        rm.generate_report(mes_ref, sub_uid, split_r,
                                           patio_split_id=split_id, patio_resultado=r_patio)
                        rm.mark_approved(mes_ref, sub_uid)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        with bc4:
            if status == "aprovado":
                if st.button("↩ Reabrir", key=f"wf_reab_{sub_uid}", use_container_width=True):
                    try:
                        rm.reopen(mes_ref, sub_uid)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        st.divider()


# ─── resultado visual ─────────────────────────────────────────────────────────

def _mostrar_resultado_unit(r: ResultadoUnidade):
    import pandas as pd
    extras = r.extras or {}

    # Cards — usa 3 colunas para evitar truncamento
    aluguel_label = "Saldo a Pagar" if extras.get("saldo_a_pagar") is not None else "Repasse / Aluguel"
    aluguel_val = extras.get("saldo_a_pagar", r.aluguel_calculado)

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Faturamento", _fmt(r.faturamento))
    mc2.metric("Resultado", _fmt(r.resultado))
    mc3.metric(aluguel_label, _fmt(aluguel_val))

    # Métricas extras em linha extra se houver
    extras_metrics = {}
    if r.prejuizo_acumulado_saida and r.prejuizo_acumulado_saida < 0:
        extras_metrics["Prejuízo Acumulado"] = _fmt(r.prejuizo_acumulado_saida)
    if extras.get("saldo_acumulado"):
        extras_metrics["Saldo Acumulado"] = _fmt(extras["saldo_acumulado"])

    if extras_metrics:
        ecols = st.columns(len(extras_metrics))
        for col, (lbl, val) in zip(ecols, extras_metrics.items()):
            col.metric(lbl, val)

    # DRE resumida
    rows = []
    if r.subtotal and r.subtotal != r.faturamento:
        rows.append(("Receita Bruta", _fmt(r.faturamento)))
        rows.append(("(-) Impostos / ISS", _fmt(r.faturamento - r.subtotal)))
        rows.append(("Subtotal", _fmt(r.subtotal)))
    if r.ponto_equilibrio:
        rows.append(("(-) Ponto de Equilíbrio", _fmt(-r.ponto_equilibrio)))
    for k, v in (r.custos or {}).items():
        if v:
            rows.append((f"(-) {_custo_label(k)}", _fmt(-v)))
    rows.append(("Resultado", _fmt(r.resultado)))
    rows.append((aluguel_label, _fmt(aluguel_val)))

    if rows:
        st.dataframe(
            pd.DataFrame(rows, columns=["", "Valor"]),
            hide_index=True, use_container_width=True,
        )


def _mostrar_resultado_patio(r: ResultadoPatio):
    col_r, col_m = st.columns(2)
    with col_r:
        st.caption("**REAL (53,52%)**")
        _mostrar_resultado_unit(r.real)
    with col_m:
        st.caption("**MAIOJAMA (46,48%)**")
        _mostrar_resultado_unit(r.maiojama)
    if r.outros_servicos:
        os_d = r.outros_servicos
        st.caption(f"Outros Serviços: resultado {_fmt(os_d.get('resultado',0))} | repasse {_fmt(os_d.get('repasse_total',0))}")
    if r.carregadores:
        c = r.carregadores
        st.caption(f"Carregadores: resultado {_fmt(c.get('resultado',0))} | repasse {_fmt(c.get('repasse_total',0))}")


# ─── uploads ─────────────────────────────────────────────────────────────────

def _secao_uploads(mes_ref: str, unidades: list, fat_data: dict | None):
    st.markdown("**Planilha de Faturamentos**")
    if fat_data:
        n = len(fat_data.get("uid_map", {}))
        total = sum(fat_data["uid_map"].values())
        c1, c2 = st.columns([4, 1])
        c1.success(f"✅ {n} unidades  |  Total: R$ {total:,.2f}")
        if c2.button("Substituir", key="btn_sub_fat"):
            _limpar_fat_import(mes_ref)
            st.rerun()
    else:
        arq = st.file_uploader("Selecione (.xlsx)", type=["xlsx"], key="fat_upload_f")
        if arq:
            _processar_upload_fat(mes_ref, arq, unidades)

    uids_eventos = [u for u in unidades if u.get("tipo_relatorio") == "com_eventos"]
    if not uids_eventos:
        return

    st.markdown("**Planilhas de Eventos**")
    cols = st.columns(len(uids_eventos))
    for col, u in zip(cols, uids_eventos):
        uid = u["id"]
        ev = eventos_parser.load_uid(mes_ref, uid)
        with col:
            st.caption(f"**{u['nome']}**")
            if ev:
                total_ev = eventos_parser.get_total_competencia(ev, mes_ref)
                ev_mes = eventos_parser.get_eventos_competencia(ev, mes_ref)
                st.success(f"✅ {len(ev_mes)} eventos | {_fmt(total_ev)}")
                if st.button("Substituir", key=f"btn_sub_ev_{uid}"):
                    _limpar_ev_uid(mes_ref, uid)
                    st.rerun()
            else:
                arq_ev = st.file_uploader("Selecione (.xlsx)", type=["xlsx"], key=f"ev_upload_{uid}")
                if arq_ev:
                    _processar_upload_ev(mes_ref, uid, arq_ev)


def _processar_upload_fat(mes_ref: str, arq, unidades: list):
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(arq.read())
        tmp_path = tmp.name
    try:
        parsed = fat_parser.parse_xlsx(tmp_path, unidades)
        fat_parser.salvar(mes_ref, parsed, tmp_path)
        _aplicar_fat_importado(parsed.get("uid_map", {}))
        n = len(parsed.get("uid_map", {}))
        total = sum(parsed["uid_map"].values())
        st.success(f"✅ {n} unidades  |  Total: R$ {total:,.2f}")
        nao_map = parsed.get("nao_mapeados", [])
        if nao_map:
            st.warning(f"⚠ Sem correspondência: {', '.join(a['nome'] for a in nao_map)}")
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao processar planilha: {e}")
    finally:
        os.unlink(tmp_path)


def _processar_upload_ev(mes_ref: str, uid: str, arq):
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(arq.read())
        tmp_path = tmp.name
    try:
        parsed = eventos_parser.parse_xlsx(tmp_path)
        eventos_parser.salvar_uid(mes_ref, uid, parsed, tmp_path)
        total_ev = eventos_parser.get_total_competencia(parsed, mes_ref)
        st.success(f"✅ Eventos importados | {_fmt(total_ev)}")
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao processar eventos {uid.upper()}: {e}")
    finally:
        os.unlink(tmp_path)


def _aplicar_fat_importado(uid_map: dict):
    if "faturamentos" not in st.session_state:
        st.session_state.faturamentos = {}
    for uid, fat in uid_map.items():
        st.session_state.faturamentos[uid] = fat
        st.session_state[f"fat_{uid}"] = fat


def _limpar_fat_import(mes_ref: str):
    fat_path = Path(f"data/runs/{mes_ref}/processed/faturamento.json")
    if fat_path.exists():
        fat_path.unlink()
    if "faturamentos" in st.session_state:
        st.session_state.faturamentos = {}


def _limpar_ev_uid(mes_ref: str, uid: str):
    p = Path(f"data/runs/{mes_ref}/processed/eventos_{uid}.json")
    if p.exists():
        p.unlink()


# ─── ações em massa ───────────────────────────────────────────────────────────

def _gerar_pendentes(mes_ref: str, todos_uids: list):
    pendentes = [uid for uid in todos_uids
                 if rm.get_unit_run(mes_ref, uid)["status"] in ("pendente", "erro")]
    if not pendentes:
        st.info("Nenhuma unidade pendente.")
        return
    bar = st.progress(0, text="Gerando PDFs…")
    for i, uid in enumerate(pendentes):
        bar.progress((i+1)/len(pendentes), text=f"Gerando: {_display_name(uid)}")
        try:
            resultado = rm.load_resultado_from_db(mes_ref, uid)
            if resultado is None:
                continue
            if uid in ("patio_real", "patio_maiojama"):
                rm.generate_report(mes_ref, uid, None,
                                   patio_split_id=uid.replace("patio_",""), patio_resultado=None)
            else:
                rm.generate_report(mes_ref, uid, resultado)
        except Exception as e:
            rm.mark_error(mes_ref, uid, str(e))
    bar.empty()
    st.success(f"{len(pendentes)} PDF(s) gerado(s).")


def _aprovar_todos_gerados(mes_ref: str, todos_uids: list):
    count = 0
    for uid in todos_uids:
        if rm.get_unit_run(mes_ref, uid)["status"] in ("gerado", "revisado"):
            try:
                rm.mark_approved(mes_ref, uid)
                count += 1
            except Exception:
                pass
    if count:
        st.success(f"{count} unidade(s) aprovada(s).")
    else:
        st.info("Nenhuma unidade com status 'gerado' ou 'revisado'.")


def _download_zip(mes_ref: str, todos_uids: list, run: dict):
    disponiveis = [
        uid for uid in todos_uids
        if run.get(uid, {}).get("status") in ("gerado", "revisado", "aprovado")
        and run.get(uid, {}).get("pdf_path")
        and Path(run[uid]["pdf_path"]).exists()
    ]
    if not disponiveis:
        st.button("📦 Baixar ZIP", disabled=True, use_container_width=True)
        return
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for uid in disponiveis:
            p = run[uid]["pdf_path"]
            zf.write(p, Path(p).name)
    buf.seek(0)
    st.download_button(
        f"📦 Baixar ZIP ({len(disponiveis)} PDFs)",
        data=buf, file_name=f"relatorios_lyon_{mes_ref}.zip",
        mime="application/zip", use_container_width=True,
    )


# ─── helpers de sessão ────────────────────────────────────────────────────────

def _salvar_resultado_session(uid: str, fat: float, resultado):
    if "resultados" not in st.session_state:
        st.session_state.resultados = {}
    st.session_state.resultados[uid] = resultado
    if "faturamentos" not in st.session_state:
        st.session_state.faturamentos = {}
    st.session_state.faturamentos[uid] = fat


def _coletar_params_usados(uid: str, u_cfg: dict,
                            pe_override: float | None,
                            custos_extras: dict) -> dict:
    from app.models import _extrair_editaveis
    params: dict = {}
    _extrair_editaveis(u_cfg, params)
    if pe_override is not None:
        params["ponto_equilibrio"] = pe_override
    for k in u_cfg.get("custos_mensais") or {}:
        if k in custos_extras:
            params[f"custos_mensais.{k}"] = custos_extras[k]
    for k in u_cfg.get("custos_variaveis") or {}:
        if k in custos_extras:
            params[f"custos_variaveis.{k}"] = custos_extras[k]
    return params


def _init_state():
    defaults = {"faturamentos": {}, "resultados": {}, "selected_unit": None}
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
