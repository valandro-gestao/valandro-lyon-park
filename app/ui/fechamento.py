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

import base64, io, json, os, tempfile, zipfile
from pathlib import Path

import streamlit as st
from streamlit.components.v1 import html as st_html

from app import run_manager as rm
from app.calculators.patio import ResultadoPatio
from app.engine import calcular, get_unit, get_unit_com_params, get_unidades_ativas
from app.paths import RUNS_DIR
from app.models import (
    ResultadoUnidade, get_db, init_db, salvar_lancamento, get_saldo_acumulado,
    salvar_parametros, corrigir_saldo_anual,
)
from app.parsers import eventos as eventos_parser
from app.parsers import faturamento as fat_parser
from app.reporter import build_report_data
from app.renderer import render_html

# ─── CSS global ──────────────────────────────────────────────────────────────
# Tokens alinhados ao padrão aprovado no Login (docs/03_DESIGN_LANGUAGE.md).
# Nenhuma fonte é carregada por CDN — mesma stack de sistema do Login.

_CSS = """
<style>
:root {
  --vd-navy:      #1B3A6B;
  --vd-navy-mid:  #2E6DA4;
  --vd-ink:       #1F2937;
  --vd-muted:     #6B7280;
  --vd-faint:     #9CA3AF;
  --vd-border:    #E2E5EA;
  --vd-green:     #059669;
  --vd-amber:     #B45309;
  --vd-red:       #DC2626;
  --vd-font-display: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --vd-font-body:    -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

/* Largura pensada para notebook ~14" — evita dispersão em monitores largos */
.block-container {
  padding-top: 0.7rem !important;
  padding-bottom: 1rem !important;
  max-width: 1180px;
}

/* Divisores mais discretos — aproxima competência, resumo, filtros e ações */
.block-container hr { margin: 0.4rem 0 !important; }

/* Expanders mais compactos — mais unidades visíveis por viewport */
[data-testid="stExpander"] { margin-bottom: 4px !important; }
[data-testid="stExpander"] summary { padding-top: 6px !important; padding-bottom: 6px !important; }

/* Tabelas mais compactas */
[data-testid="stDataFrame"] { font-size: 0.82rem; }

/* Métricas menores (padrão geral — tela de detalhe usa este tamanho) */
[data-testid="stMetric"] { padding: 0.3rem 0.5rem !important; }
[data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
[data-testid="stMetricValue"] { font-size: 1.05rem !important; }

/* Oculta toolbar do Streamlit */
header[data-testid="stHeader"] { display: none !important; }

/* Botões: altura/alinhamento padronizados — prioridade só por cor e peso */
div[data-testid="stButton"] button {
  display: flex !important;
  align-items: center;
  justify-content: center;
  line-height: 1.3;
  min-height: 38px;
}
div[data-testid="stButton"] button[kind="primary"] {
  background: var(--vd-navy) !important;
  border-color: var(--vd-navy) !important;
  color: #fff !important;
  font-weight: 600;
}
div[data-testid="stButton"] button[kind="primary"]:hover {
  background: var(--vd-navy-mid) !important;
  border-color: var(--vd-navy-mid) !important;
}
div[data-testid="stButton"] button[kind="secondary"] {
  color: var(--vd-muted) !important;
  border-color: var(--vd-border) !important;
  font-weight: 500;
}

/* ── Marca Valandro: discreta, mesma identidade do Login ───────────────────── */
.vd-brand-mark { height: 24px; display: block; margin-bottom: 12px; opacity: 0.85; }

/* ── Cabeçalho: competência em primeiro plano ─────────────────────────────── */
.vd-comp-label {
  font-family: var(--vd-font-body);
  font-size: 0.7rem;
  color: var(--vd-faint);
  margin: 0 0 1px;
}
.vd-comp-value {
  font-family: var(--vd-font-display);
  font-size: 1.7rem;
  font-weight: 600;
  color: var(--vd-ink);
  line-height: 1.15;
  letter-spacing: -.2px;
  white-space: nowrap;
}
.st-key-vd-comp-filter p { font-size: 0.72rem !important; color: var(--vd-faint) !important; margin-bottom: 3px !important; }
.st-key-vd-comp-filter [data-baseweb="select"] > div {
  min-height: 40px !important;
  font-size: 0.85rem !important;
}
.st-key-vd-comp-filter [data-baseweb="select"] { min-width: 100px; }

/* ── Resumo operacional: número + rótulo lidos como uma única informação ──── */
.vd-summary {
  display: flex;
  align-items: baseline;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 0.85rem;
  margin: 2px 0;
}
.vd-summary-item { display: inline-flex; align-items: baseline; gap: 4px; white-space: nowrap; }
.vd-summary-item strong { font-size: 1.1rem; font-weight: 700; }
.vd-summary-item span.vd-lbl { color: var(--vd-muted); }
.vd-summary .vd-sep { color: var(--vd-border); }
.vd-summary-pend strong { color: var(--vd-ink); }
.vd-summary-pend span.vd-lbl { color: var(--vd-ink); opacity: .72; }
.vd-summary-and strong  { color: var(--vd-navy-mid); font-size: 1.02rem; }
.vd-summary-and span.vd-lbl { color: var(--vd-navy-mid); opacity: .75; }
.vd-summary-apr strong  { color: var(--vd-green); font-size: 1.02rem; }
.vd-summary-apr span.vd-lbl { color: var(--vd-green); opacity: .75; }
.vd-summary-tot strong  { color: var(--vd-muted); font-size: 1.02rem; font-weight: 500; }
.vd-summary-secondary { font-size: 0.76rem; margin-top: 1px; }
.vd-summary-secondary strong { font-size: 0.88rem; }
.vd-summary-reab strong { color: var(--vd-amber); }
.vd-summary-reab span.vd-lbl { color: var(--vd-amber); opacity: .75; }
.vd-summary-erro strong { color: var(--vd-red); }
.vd-summary-erro span.vd-lbl { color: var(--vd-red); opacity: .75; }
.vd-summary-item.vd-zero strong,
.vd-summary-item.vd-zero span.vd-lbl { color: var(--vd-faint) !important; opacity: 1 !important; }

/* ── Status: círculo + texto, sem emoji (seção 2.1 do Design Language) ────── */
.vd-status { display: inline-flex; align-items: center; gap: 6px; font-size: 0.85rem; font-family: var(--vd-font-body); }
.vd-status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.vd-status--pendente .vd-status-dot  { background: var(--vd-ink); }
.vd-status--pendente                 { color: var(--vd-ink); }
.vd-status--andamento .vd-status-dot { background: var(--vd-navy-mid); }
.vd-status--andamento                { color: var(--vd-navy-mid); }
.vd-status--aprovado .vd-status-dot  { background: var(--vd-green); }
.vd-status--aprovado                 { color: var(--vd-green); font-weight: 600; }
.vd-status--reaberto .vd-status-dot  { background: var(--vd-amber); }
.vd-status--reaberto                 { color: var(--vd-amber); }
.vd-status--erro .vd-status-dot      { background: var(--vd-red); }
.vd-status--erro                     { color: var(--vd-red); font-weight: 600; }

/* ── Alerta de unidade (sem faturamento / sem eventos) ─────────────────────── */
.vd-alert-tag { color: var(--vd-amber); font-size: 0.74rem; font-weight: 500; }

/* ── Importação: sucesso e alertas como leituras distintas ─────────────────── */
.vd-upload-ok   { font-size: 0.85rem; color: var(--vd-ink); }
.vd-upload-warn-group {
  margin-top: 6px;
  padding-left: 10px;
  border-left: 2px solid var(--vd-amber);
}
.vd-upload-warn { font-size: 0.78rem; color: var(--vd-amber); line-height: 1.6; }

/* ── Lista de unidades: linhas compactas, ações próximas do status ────────── */
[class*="st-key-vd-unit-list"] [data-testid="stHorizontalBlock"] {
  align-items: center;
  padding: 4px 0;
  border-bottom: 1px solid var(--vd-border);
}

/* Rótulo de subseção (tela de detalhe) — sem kicker uppercase (seção 5 do
   Design Language descarta esse padrão). Margem reduzida: Dados importados,
   Parâmetros, Calcular e Resultado devem ler como um raciocínio contínuo. */
.section-title {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--vd-muted);
    margin: 0.3rem 0 0.15rem;
}
/* A leitura sequencial do cálculo fica com o ritmo vertical mais compacto —
   aplicado apenas ao contêiner explicitamente marcado, não à página toda. */
.st-key-vd-fluxo-calculo [data-testid="stElementContainer"] { margin-bottom: 2px !important; }

/* ── Cabeçalho da unidade: mesma identidade do Login/Dashboard ────────────── */
.st-key-vd-back-link button {
  background: none !important;
  border: none !important;
  box-shadow: none !important;
  color: var(--vd-faint) !important;
  font-weight: 500 !important;
  font-size: 0.8rem !important;
  padding: 0 !important;
  min-height: auto !important;
  justify-content: flex-start !important;
}
.st-key-vd-back-link button:hover { color: var(--vd-navy-mid) !important; }
.vd-unit-name {
  font-family: var(--vd-font-display);
  font-size: 1.55rem;
  font-weight: 600;
  color: var(--vd-ink);
  letter-spacing: -.2px;
  line-height: 1.2;
  margin: 2px 0 2px;
}
.vd-unit-meta { font-size: 0.85rem; color: var(--vd-muted); display: flex; align-items: center; gap: 8px; }
.vd-unit-meta .vd-sep { color: var(--vd-border); }

/* Nota inline (reajuste etc.) — mesmo padrão do bloco de avisos de importação */
.vd-inline-note {
  margin-top: 6px;
  padding-left: 10px;
  border-left: 2px solid var(--vd-amber);
  font-size: 0.8rem;
  color: var(--vd-amber);
}

/* ── Comparação de parâmetro alterado: valor anterior riscado → valor atual ─ */
.vd-param-diff { font-size: 0.76rem; margin: -4px 0 8px; }
.vd-param-old { color: var(--vd-faint); text-decoration: line-through; }
.vd-param-arrow { color: var(--vd-faint); margin: 0 4px; }
.vd-param-new { color: var(--vd-amber); font-weight: 600; }

/* ── Ação que desfaz aprovação: tratamento distinto de ação segura ────────── */
[class*="st-key-vd-danger-action"] button {
  color: var(--vd-amber) !important;
  border-color: var(--vd-amber) !important;
}

/* ── Barra de decisão final: uma ferramenta, não três caixas soltas ───────── */
[class*="st-key-vd-decisao-final"] {
  background: #FAFBFC;
  border: 1px solid var(--vd-border);
  border-radius: 4px;
  padding: 8px 10px;
}
[class*="st-key-vd-decisao-final"] div[data-testid="stButton"] button,
[class*="st-key-vd-decisao-final"] div[data-testid="stDownloadButton"] button {
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
}
[class*="st-key-vd-decisao-final"] div[data-testid="stButton"] button[kind="primary"] {
  background: var(--vd-navy) !important;
  color: #fff !important;
  border-radius: 4px !important;
}
[class*="st-key-vd-decisao-final"] [class*="st-key-vd-danger-action"] button {
  background: transparent !important;
}
[class*="st-key-vd-decisao-final"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
  border-right: 1px solid var(--vd-border);
}
[class*="st-key-vd-decisao-final"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child {
  border-right: none;
}

/* ── Histórico: um único bloco, dois subconjuntos claramente identificados ── */
.vd-hist-sub {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--vd-navy-mid);
  margin: 4px 0 6px;
  padding-bottom: 3px;
  border-bottom: 1px solid var(--vd-border);
}

/* Histórico tabela (tela de detalhe) */
.hist-table th { font-size: 0.75rem; }
.hist-table td { font-size: 0.8rem; }
</style>
"""

# ── UX de campos numéricos: primeiro clique seleciona todo o conteúdo ────────
# Streamlit não expõe essa opção nativamente. O componente roda num iframe
# same-origin, então o listener é anexado em window.parent.document — evento
# delegado (focusin) para cobrir também campos renderizados depois deste
# primeiro carregamento, sem precisar reinjetar a cada rerun. Não altera
# nenhuma regra de cálculo; é puramente uma melhoria de digitação.
_NUMBER_SELECT_JS = """
<script>
(function() {
  var doc = window.parent.document;
  if (doc.__vdNumberSelectAttached) return;
  doc.__vdNumberSelectAttached = true;
  doc.addEventListener('focusin', function(e) {
    var el = e.target;
    if (el && el.tagName === 'INPUT' && el.closest('[data-testid="stNumberInput"]')) {
      el.select();
    }
  });
})();
</script>
"""


def _load_valandro_logo_uri() -> str:
    """Mesma marca usada no Login — identidade consistente entre telas."""
    path = Path(__file__).resolve().parent.parent.parent / "assets" / "valandro_logo.png"
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


_VALANDRO_LOGO_URI = _load_valandro_logo_uri()


# ─── helpers ─────────────────────────────────────────────────────────────────

_MESES = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
           "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

def _mes_label(mes_ref: str) -> str:
    ano, mes = mes_ref.split("-")
    return f"{_MESES[int(mes)-1]} / {ano}"


def _mes_label_grande(mes_ref: str) -> str:
    """Formato de destaque para o cabeçalho da tela principal: 'Julho 2026'."""
    ano, mes = mes_ref.split("-")
    return f"{_MESES[int(mes)-1]} {ano}"


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


def _status_chip_html(status: str) -> str:
    """Rótulo de status via cor + círculo (sem emoji) — tela de lista."""
    grupo = {
        "pendente": "pendente",
        "gerado": "andamento",
        "revisado": "andamento",
        "aprovado": "aprovado",
        "reaberto": "reaberto",
        "erro": "erro",
    }.get(status, "pendente")
    label = {
        "pendente": "Pendente", "gerado": "Gerado", "revisado": "Revisado",
        "aprovado": "Aprovado", "reaberto": "Reaberto", "erro": "Erro",
    }.get(status, status.title())
    return f'<span class="vd-status vd-status--{grupo}"><span class="vd-status-dot"></span>{label}</span>'


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
        "seguranca": "Segurança",
        "sistemas_voip": "Sistemas VOIP",
        "perto": "Perto",
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


# ─── rascunho de trabalho (persistência de estado antes da aprovação) ───────
# Sprint v1.1.1, item 1: os campos de entrada de uma unidade devem sobreviver
# à navegação, ao fechamento da sessão e à reabertura — sem criar um novo
# status de workflow. "Salvar estado" é automático a cada rerender; "Aprovar"
# continua sendo a única ação que persiste parâmetros vigentes/lançamentos.

_CHAVES_PATIO = [
    "fat_patio", "fp_midia", "fp_eq", "fp_lona",
    "fp_rec_car", "fp_energia", "fp_inv_car", "fp_saldo_car",
    "fp_cond_r", "fp_cond_m", "fp_iptu_m",
]


def _chaves_estado_unidade(uid: str, u: dict) -> list[str]:
    """Lista as chaves de session_state que compõem o estado de entrada de
    uma unidade simples. Precisa refletir exatamente os widgets criados em
    _inputs_parametros — mantidas juntas de propósito."""
    tc = u.get("tipo_calculo", "")
    chaves = [f"fat_{uid}"]
    if u.get("tem_faturamento_carregadores"):
        chaves.append(f"fat_car_{uid}")
    if u.get("tem_receita_selos"):
        chaves.append(f"selos_{uid}")
    pe_default = float(u.get("ponto_equilibrio", 0.0))
    has_pe = (pe_default > 0 or tc in (
        "COM_ALIQUOTA", "COM_ALIQUOTA_CUMUL", "COM_ALIQUOTA_SPLIT",
        "COM_FAIXAS", "PERCENTUAL_SIMPLES", "COM_ALIQUOTA_REPASSE_DUPLO",
    )) and tc != "PATIO_MANUTENCAO"
    if has_pe:
        chaves.append(f"pe_{uid}")
    if u.get("tem_base_taxa_cobranca"):
        chaves.append(f"base_tc_{uid}")
    for k in (u.get("custos_mensais") or {}):
        chaves.append(f"custo_{uid}_{k}")
    for k in (u.get("custos_variaveis") or {}):
        chaves.append(f"cv_{uid}_{k}")
    return chaves


def _restaurar_rascunho(uid: str, mes_ref: str, chaves: list[str]):
    """Restaura o rascunho salvo (models.carregar_rascunho_unidade) sempre que
    a tela é aberta numa nova sessão ou a competência muda dentro da mesma
    sessão. Se não houver rascunho (ex.: acabou de ser limpo por uma
    aprovação), as chaves são removidas para que os widgets voltem a usar o
    valor vigente (YAML + DB de parâmetros) como padrão — que é exatamente o
    valor usado na aprovação, no caso de reabertura."""
    from app.models import carregar_rascunho_unidade
    marker = f"_draft_ctx_{uid}"
    if st.session_state.get(marker) == mes_ref:
        return
    for k in chaves:
        st.session_state.pop(k, None)
    draft = carregar_rascunho_unidade(uid, mes_ref)
    if draft:
        for k, v in draft.items():
            if k in chaves:
                st.session_state[k] = v
    st.session_state[marker] = mes_ref


def _salvar_rascunho(uid: str, mes_ref: str, chaves: list[str]):
    """Persiste o valor atual de cada chave — chamado ao final de toda
    renderização dos parâmetros, ou seja, a cada alteração de campo."""
    from app.models import salvar_rascunho_unidade
    estado = {k: st.session_state[k] for k in chaves if k in st.session_state}
    if estado:
        salvar_rascunho_unidade(uid, mes_ref, estado)


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
    st_html(_NUMBER_SELECT_JS, height=0)
    _init_state()

    if st.session_state.get("selected_unit"):
        _tela_detalhe(mes_ref)
    else:
        _tela_lista(mes_ref)


# ═══════════════════════════════════════════════════════════════════════════════
# TELA DE LISTA
# ═══════════════════════════════════════════════════════════════════════════════

def _tela_lista(mes_ref: str):
    # ── Marca + cabeçalho: competência em primeiro plano ──────────────────────
    from datetime import date
    hoje = date.today()

    st.markdown(
        f'<img src="{_VALANDRO_LOGO_URI}" class="vd-brand-mark" alt="Valandro" />',
        unsafe_allow_html=True,
    )

    c_comp, c_filtro = st.columns([3, 2])
    with c_comp:
        st.markdown(
            f'<div class="vd-comp-label">Fechamento Mensal</div>'
            f'<div class="vd-comp-value">{_mes_label_grande(mes_ref)}</div>',
            unsafe_allow_html=True,
        )
    with c_filtro:
        with st.container(key="vd-comp-filter"):
            st.caption("Alterar competência")
            fc1, fc2 = st.columns(2)
            with fc1:
                anos = list(range(2024, hoje.year + 2))
                ano_idx = anos.index(st.session_state.get("sel_ano", hoje.year))
                novo_ano = st.selectbox("Ano", anos, index=ano_idx, key="hdr_ano", label_visibility="collapsed")
                if novo_ano != st.session_state.get("sel_ano"):
                    st.session_state.sel_ano = novo_ano
                    st.rerun()
            with fc2:
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

    st.divider()

    unidades = get_unidades_ativas(mes_ref)
    run = rm.load_run(mes_ref)
    fat_data = fat_parser.load(mes_ref)
    uid_map = fat_data.get("uid_map", {}) if fat_data else {}

    # ── Planilhas ─────────────────────────────────────────────────────────────
    with st.expander("Planilhas da competência", expanded=not fat_data):
        _secao_uploads(mes_ref, unidades, fat_data)

    # ── Resumo operacional + próxima ação, lado a lado (menos rolagem) ───────
    col_resumo, col_acoes = st.columns([1, 1])
    with col_resumo:
        _resumo_operacional(unidades, run)

    todos_uids: list[str] = []
    for u in unidades:
        todos_uids.extend(_report_uids_of(u["id"]))

    with col_acoes:
        act1, act2, act3 = st.columns(3)
        with act1:
            if st.button("Gerar pendentes", type="primary", use_container_width=True):
                _gerar_pendentes(mes_ref, todos_uids)
                st.rerun()
        with act2:
            if st.button("Aprovar todos", use_container_width=True):
                _dialog_confirmar_aprovar_todos(mes_ref, todos_uids)
        with act3:
            _download_zip(mes_ref, todos_uids, run)

    st.divider()

    # ── Lista agrupada ────────────────────────────────────────────────────────
    _lista_unidades_agrupada(mes_ref, unidades, uid_map, run)


def _resumo_operacional(unidades: list, run: dict):
    """Leitura rápida do estado da competência — linha única, com cor e rótulo
    ao lado do número (nunca isolado em card ou badge — seção 6 do Design
    Language). Hierarquia: Pendentes / Em andamento / Aprovadas / Total;
    Reabertos e Erros separados, numa segunda linha menor.
    """
    contagem = {"pendente": 0, "gerado": 0, "revisado": 0, "aprovado": 0, "reaberto": 0, "erro": 0}
    total = 0
    for u in unidades:
        for r_uid in _report_uids_of(u["id"]):
            total += 1
            s = run.get(r_uid, {}).get("status", "pendente")
            contagem[s] = contagem.get(s, 0) + 1
    andamento = contagem["gerado"] + contagem["revisado"]

    def _item(cls: str, valor: int, rotulo: str, zero_ok: bool = False) -> str:
        zero_cls = " vd-zero" if (zero_ok and valor == 0) else ""
        return (
            f'<span class="vd-summary-item {cls}{zero_cls}">'
            f'<strong>{valor}</strong><span class="vd-lbl">{rotulo}</span></span>'
        )

    linha1 = (
        _item("vd-summary-pend", contagem["pendente"], "pendentes")
        + '<span class="vd-sep">·</span>'
        + _item("vd-summary-and", andamento, "em andamento")
        + '<span class="vd-sep">·</span>'
        + _item("vd-summary-apr", contagem["aprovado"], "aprovadas")
        + '<span class="vd-sep">·</span>'
        + _item("vd-summary-tot", total, "total")
    )
    linha2 = (
        _item("vd-summary-reab", contagem["reaberto"], "reabertas", zero_ok=True)
        + '<span class="vd-sep">·</span>'
        + _item("vd-summary-erro", contagem["erro"], "erros", zero_ok=True)
    )

    st.markdown(f'<div class="vd-summary">{linha1}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="vd-summary vd-summary-secondary">{linha2}</div>', unsafe_allow_html=True)


def _alertas_unidade(mes_ref: str, u: dict, uid_map: dict) -> list[str]:
    """Alertas de dados ausentes para uma unidade (usado para priorizar e destacar)."""
    uid = u["id"]
    fat = uid_map.get(uid)
    alertas = []
    if uid_map and fat is None and uid != "patio":
        alertas.append("sem faturamento")
    if u.get("tipo_relatorio") == "com_eventos":
        if eventos_parser.load_uid(mes_ref, uid) is None:
            alertas.append("sem eventos")
    return alertas


def _lista_unidades_agrupada(mes_ref: str, unidades: list, uid_map: dict, run: dict):
    grupos: dict[str, list] = {"pendente": [], "andamento": [], "aprovado": []}

    for u in unidades:
        report_uids = _report_uids_of(u["id"])
        statuses = [run.get(r, {}).get("status", "pendente") for r in report_uids]
        s = _pior_status(statuses)
        alertas = _alertas_unidade(mes_ref, u, uid_map)
        item = (u, s, alertas)
        if s == "aprovado":
            grupos["aprovado"].append(item)
        elif s in ("gerado", "revisado"):
            grupos["andamento"].append(item)
        else:
            grupos["pendente"].append(item)

    # Unidades com alerta sobem para o topo do próprio grupo.
    for k in ("pendente", "andamento"):
        grupos[k].sort(key=lambda item: 0 if item[2] else 1)

    def _render_grupo(items, titulo, expandido, key_suffix, is_aprovado=False):
        if not items:
            return
        with st.expander(f"{titulo} ({len(items)})", expanded=expandido):
            with st.container(key=f"vd-unit-list-{key_suffix}"):
                _cabecalho_lista(is_aprovado)
                for u, status, alertas in items:
                    _linha_unidade(mes_ref, u, status, uid_map, run, alertas)

    _render_grupo(grupos["pendente"], "Pendentes", True, "pend")
    _render_grupo(grupos["andamento"], "Em andamento", False, "and")
    _render_grupo(grupos["aprovado"], "Aprovadas", False, "apr", is_aprovado=True)


def _cabecalho_lista(tem_pdf: bool = False):
    cols = [3, 2, 2, 2] if not tem_pdf else [3, 2, 2, 1, 2]
    h = st.columns(cols)
    h[0].caption("**Unidade**")
    h[1].caption("**Faturamento**")
    h[2].caption("**Status**")
    if tem_pdf:
        h[3].caption("**PDF**")
        h[4].caption("**Ações**")
    else:
        h[3].caption("**Ações**")


def _linha_unidade(mes_ref: str, u: dict, status: str, uid_map: dict, run: dict, alertas: list[str]):
    uid = u["id"]
    fat = uid_map.get(uid)
    report_uids = _report_uids_of(uid)
    is_aprovado = status == "aprovado"

    if is_aprovado:
        row = st.columns([3, 2, 2, 1, 2])
    else:
        row = st.columns([3, 2, 2, 2])

    row[0].write(f"**{u['nome']}**")
    if alertas:
        row[0].markdown(
            f'<span class="vd-alert-tag">{" · ".join(a.capitalize() for a in alertas)}</span>',
            unsafe_allow_html=True,
        )
    row[1].write(_fmt(fat) if fat else "—")
    row[2].markdown(_status_chip_html(status), unsafe_allow_html=True)

    if is_aprovado:
        # Coluna PDF para unidades aprovadas
        pdf_path = run.get(report_uids[0], {}).get("pdf_path")
        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                row[3].download_button(
                    "PDF", data=f,
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
            if bc[1].button("Reabrir", key=f"reab_{uid}_{mes_ref}", use_container_width=True):
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
                if bc[1].button("Aprovar", key=f"qaprov_{uid}_{mes_ref}",
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

    # Restaura o rascunho de trabalho (ou limpa, se não houver, para cair no
    # valor vigente) antes de qualquer widget ser criado — ver item 1 da
    # sprint v1.1.1.
    if is_patio:
        _restaurar_rascunho("patio", mes_ref, _CHAVES_PATIO)
    else:
        _restaurar_rascunho(uid, mes_ref, _chaves_estado_unidade(uid, u))

    report_uids = _report_uids_of(uid)
    statuses = [run.get(r, {}).get("status", "pendente") for r in report_uids]
    status = _pior_status(statuses)

    # A página inteira (cabeçalho → raciocínio → decisão → histórico) vive num
    # único ritmo vertical compacto — transições de seção, não blocos soltos.
    with st.container(key="vd-detalhe-page", gap="xsmall"):
        # ── Cabeçalho da unidade: mesma identidade do Login/Dashboard ────────
        st.markdown(
            f'<img src="{_VALANDRO_LOGO_URI}" class="vd-brand-mark" alt="Valandro" />',
            unsafe_allow_html=True,
        )
        with st.container(key="vd-back-link"):
            if st.button("← Voltar à lista", key="btn_voltar"):
                st.session_state.selected_unit = None
                st.rerun()

        nome_exib = "Pátio — Operação" if is_patio else u["nome"]
        meta_parts = [_mes_label(mes_ref), _status_chip_html(status)]
        if u.get("contratante"):
            meta_parts.append(u["contratante"])
        meta_html = '<span class="vd-sep">·</span>'.join(meta_parts)
        st.markdown(
            f'<div class="vd-unit-name">{nome_exib}</div>'
            f'<div class="vd-unit-meta">{meta_html}</div>',
            unsafe_allow_html=True,
        )

        # Alerta de reajuste — nota inline, não banner genérico
        reajuste_mes = u.get("reajuste_mes")
        if reajuste_mes and int(mes_ref.split("-")[1]) == int(reajuste_mes):
            st.markdown(
                '<div class="vd-inline-note">Mês de reajuste contratual — verifique o novo '
                'Ponto de Equilíbrio antes de calcular.</div>',
                unsafe_allow_html=True,
            )

        st.divider()

        if is_patio:
            _detalhe_patio(uid, u, mes_ref, uid_map, resultados, run, status)
        else:
            _detalhe_simples(uid, u, mes_ref, uid_map, resultados, run, status)


# ─── detalhe: unidade simples ─────────────────────────────────────────────────

def _detalhe_simples(uid: str, u: dict, mes_ref: str,
                     uid_map: dict, resultados: dict, run: dict, status: str):
    """Estação de trabalho da operadora para uma unidade: leitura sequencial
    (dado importado → parâmetro → resultado) seguida da ação imediata
    (Calcular) e, só então, da decisão final (Gerar PDF / Aprovar / Reabrir).
    A próxima ação esperada é sempre a que carrega o peso visual primário —
    sem stepper ou assistente, só o botão certo ficando em destaque a cada
    etapa."""
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

    def _diff_html(chave: str) -> str | None:
        """Comparação valor anterior → valor atual, exibida apenas quando o
        parâmetro mudou em relação à competência anterior. Substitui o antigo
        aviso de texto (não depende de mensagem de alerta isolada)."""
        if not _alterado(chave):
            return None
        ant, atu = params_ant.get(chave), params_atual.get(chave)
        return (
            f'<span class="vd-param-old">{_fmt(float(ant))}</span>'
            f'<span class="vd-param-arrow">→</span>'
            f'<span class="vd-param-new">{_fmt(float(atu))}</span>'
        )

    # ── Dados importados: só as evidências que existem, sem coluna vazia ─────
    evidencias = [("Faturamento", _fmt(fat_importado) if fat_importado else "—")]
    if tc in ("COM_ALIQUOTA_CUMUL", "PATIO_MANUTENCAO"):
        evidencias.append(("Saldo Acumulado", _fmt(get_saldo_acumulado(uid))))

    ev_total = 0.0
    if u.get("tipo_relatorio") == "com_eventos":
        ev = eventos_parser.load_uid(mes_ref, uid)
        if ev:
            ev_total = eventos_parser.get_total_competencia(ev, mes_ref)
            ev_mes = eventos_parser.get_eventos_competencia(ev, mes_ref)
            evidencias.append(("Eventos", f"{_fmt(ev_total)} · {len(ev_mes)} eventos"))
        else:
            evidencias.append(("Eventos", "Não carregados"))

    # Todo o raciocínio (dado → parâmetro → cálculo → resultado) vive num único
    # contêiner com ritmo vertical compacto — deve ler como uma continuidade,
    # não como blocos separados.
    with st.container(key="vd-fluxo-calculo", gap="xsmall"):
        st.markdown('<p class="section-title">Dados importados</p>', unsafe_allow_html=True)
        di_cols = st.columns(len(evidencias))
        for col, (lbl, val) in zip(di_cols, evidencias):
            col.metric(lbl, val)

        # Correção IPCA (MW Tristeza em janeiro)
        if u.get("prejuizo_correcao_anual") and int(mes_ref.split("-")[1]) == 1:
            saldo_atual = get_saldo_acumulado(uid)
            if saldo_atual < 0:
                with st.expander(f"Correção anual IPCA — saldo: {_fmt(saldo_atual)}", expanded=True):
                    ipca_pct = st.number_input(
                        "IPCA do ano anterior (%)",
                        min_value=0.0, max_value=50.0, step=0.01, format="%.2f",
                        key=f"ipca_corr_{uid}",
                    )
                    if st.button("Aplicar correção", key=f"btn_ipca_{uid}", type="primary"):
                        novo = corrigir_saldo_anual(uid, ipca_pct / 100.0)
                        st.success(f"Saldo corrigido: {_fmt(novo)}")
                        st.rerun()

        # ── Parâmetros: leitura sequencial, alterações comparadas inline ─────
        st.markdown('<p class="section-title">Parâmetros</p>', unsafe_allow_html=True)
        fat, pe_override, custos_extras = _inputs_parametros(
            uid, u, mes_ref, fat_importado, _diff_html
        )
        if ev_total > 0:
            custos_extras["custos_eventos"] = ev_total

        # ── Ação imediata: Calcular, logo após o último parâmetro ────────────
        unit_run = rm.get_unit_run(mes_ref, uid)
        _acao_calcular(mes_ref, uid, u, fat, pe_override, custos_extras, unit_run["status"])

        # ── Resultado: memória de cálculo — mesma estrutura já utilizada ─────
        st.markdown('<p class="section-title">Resultado</p>', unsafe_allow_html=True)
        r = resultados.get(uid) or rm.load_resultado_from_db(mes_ref, uid)
        if r is None:
            st.info("Preencha os parâmetros acima e clique em **Calcular**.")
        else:
            _mostrar_resultado_unit(r)

    # ── Barra de decisão final ────────────────────────────────────────────────
    st.divider()
    _barra_decisao_final(mes_ref, uid, r, resultados, unit_run)

    # ── Histórico ──────────────────────────────────────────────────────────────
    st.divider()
    _secao_historico_unificada(uid, unit_run)


def _inputs_parametros(uid: str, u: dict, mes_ref: str,
                        fat_importado: float | None,
                        _diff_html) -> tuple[float, float | None, dict]:
    tc = u.get("tipo_calculo", "")
    custos_extras: dict = {}

    # Faturamento (+ Faturamento Carregadores ou Receita de Selos, quando
    # aplicável, na mesma linha — melhor aproveitamento horizontal, sem criar
    # uma segunda coluna macro)
    tem_fat_car = bool(u.get("tem_faturamento_carregadores"))
    tem_selos = bool(u.get("tem_receita_selos"))
    fat_val = st.session_state.get(
        f"fat_{uid}",
        st.session_state.get("faturamentos", {}).get(uid, fat_importado or 0.0),
    )
    f1, f2 = st.columns(2) if (tem_fat_car or tem_selos) else (st.container(), None)
    with f1:
        fat = st.number_input(
            "Faturamento (R$)",
            min_value=0.0, step=100.0, format="%.2f",
            value=float(fat_val), key=f"fat_{uid}",
        )
    if tem_fat_car:
        with f2:
            fat_car = st.number_input(
                "Faturamento Carregadores (R$)",
                min_value=0.0, step=100.0, format="%.2f",
                value=float(st.session_state.get(f"fat_car_{uid}", 0.0)),
                key=f"fat_car_{uid}",
            )
            if fat_car > 0:
                custos_extras["fat_carregadores"] = fat_car
    elif tem_selos:
        with f2:
            # Fiergs: soma-se ao faturamento antes do restante do cálculo —
            # a memória de cálculo mostra a composição explícita, nunca soma
            # silenciosamente (item 3 da sprint v1.1.1).
            receita_selos = st.number_input(
                "Receita de Selos (R$)",
                min_value=0.0, step=100.0, format="%.2f",
                value=float(st.session_state.get(f"selos_{uid}", 0.0)),
                key=f"selos_{uid}",
            )
            if receita_selos > 0:
                custos_extras["receita_selos"] = receita_selos

    # Ponto de Equilíbrio (+ Base Cálculo Taxa de Cobrança, quando ambos
    # existem, na mesma linha)
    pe_default = float(u.get("ponto_equilibrio", 0.0))
    has_pe = (pe_default > 0 or tc in (
        "COM_ALIQUOTA", "COM_ALIQUOTA_CUMUL", "COM_ALIQUOTA_SPLIT",
        "COM_FAIXAS", "PERCENTUAL_SIMPLES", "COM_ALIQUOTA_REPASSE_DUPLO",
    )) and tc != "PATIO_MANUTENCAO"
    tem_base_tc = bool(u.get("tem_base_taxa_cobranca"))
    pe_override = None

    if has_pe and tem_base_tc:
        p_cols = st.columns(2)
    elif has_pe or tem_base_tc:
        p_cols = [st.container()]
    else:
        p_cols = []

    p_idx = 0
    if has_pe:
        with p_cols[p_idx]:
            pe_override = st.number_input(
                "Ponto de Equilíbrio (R$)",
                min_value=0.0, step=100.0, format="%.2f",
                value=float(st.session_state.get(f"pe_{uid}", pe_default)),
                key=f"pe_{uid}",
            )
            diff = _diff_html("ponto_equilibrio")
            if diff:
                st.markdown(f'<div class="vd-param-diff">{diff}</div>', unsafe_allow_html=True)
        p_idx += 1
    if tem_base_tc:
        with p_cols[p_idx]:
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
        n = min(4, len(custos_mensais))
        cc = st.columns(n)
        for i, (k, v) in enumerate(custos_mensais.items()):
            chave_db = f"custos_mensais.{k}"
            with cc[i % n]:
                val = st.number_input(
                    _custo_label_ui(k),
                    min_value=0.0, step=10.0, format="%.2f",
                    value=float(st.session_state.get(f"custo_{uid}_{k}", v)),
                    key=f"custo_{uid}_{k}",
                )
                diff = _diff_html(chave_db)
                if diff:
                    st.markdown(f'<div class="vd-param-diff">{diff}</div>', unsafe_allow_html=True)
                custos_extras[k] = val

    # Custos variáveis
    custos_variaveis = u.get("custos_variaveis") or {}
    if custos_variaveis:
        st.caption("**Custos variáveis:**")
        n = min(4, len(custos_variaveis))
        cv = st.columns(n)
        for i, (k, v) in enumerate(custos_variaveis.items()):
            chave_db = f"custos_variaveis.{k}"
            with cv[i % n]:
                val = st.number_input(
                    _custo_label_ui(k),
                    min_value=0.0, step=10.0, format="%.2f",
                    value=float(st.session_state.get(f"cv_{uid}_{k}", v)),
                    key=f"cv_{uid}_{k}",
                )
                diff = _diff_html(chave_db)
                if diff:
                    st.markdown(f'<div class="vd-param-diff">{diff}</div>', unsafe_allow_html=True)
                custos_extras[k] = val

    # Rascunho de trabalho: persiste o estado atual de todos os campos acima
    # a cada rerender — ou seja, a cada alteração feita pela operadora.
    _salvar_rascunho(uid, mes_ref, _chaves_estado_unidade(uid, u))

    return fat, pe_override, custos_extras


def _acao_calcular(mes_ref: str, uid: str, u: dict,
                    fat: float, pe_override: float | None, custos_extras: dict,
                    status: str):
    """Ação de rotina, posicionada logo após o último parâmetro — reduz a
    distância entre preencher e calcular. Mesma lógica de app.engine.calcular
    já existente; nenhuma regra de cálculo foi alterada."""
    c1, _ = st.columns([1, 3])
    with c1:
        if st.button("Calcular", key=f"act_calc_{uid}", use_container_width=True,
                     type="primary" if status in ("pendente", "reaberto") else "secondary"):
            if fat <= 0:
                st.error("Informe o faturamento.")
            else:
                try:
                    resultado = calcular(uid, mes_ref, fat,
                                         custos_extras=custos_extras or None,
                                         pe_override=pe_override)
                    _salvar_resultado_session(uid, fat, resultado)
                    st.session_state[f"params_usados_{uid}"] = _coletar_params_usados(
                        uid, u, pe_override, custos_extras)
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")


def _barra_decisao_final(mes_ref: str, uid: str, r, resultados: dict, unit_run: dict):
    """Gerar PDF / Baixar PDF / Aprovar / Reabrir — mesma lógica de workflow
    já existente (nenhuma regra de aprovação, reabertura ou geração de PDF foi
    alterada). Aprovar só recebe peso visual de ação primária quando já existe
    um resultado calculado (r); Reabrir, por desfazer uma aprovação, recebe
    tratamento visual distinto de uma ação sem risco como Baixar PDF."""
    status = unit_run["status"]

    # Uma única ferramenta de trabalho — não três caixas independentes.
    with st.container(key="vd-decisao-final"):
        ac1, ac2, ac3, ac4 = st.columns(4)

        # Gerar PDF
        with ac1:
            if st.button("Gerar PDF", key=f"act_pdf_{uid}", use_container_width=True):
                r_atual = resultados.get(uid) or rm.load_resultado_from_db(mes_ref, uid)
                if r_atual is None:
                    st.error("Calcule antes de gerar o PDF.")
                else:
                    try:
                        rm.generate_report(mes_ref, uid, r_atual)
                        st.success("PDF gerado.")
                        st.rerun()
                    except Exception as e:
                        rm.mark_error(mes_ref, uid, str(e))
                        st.error(f"Erro: {e}")

        # Baixar PDF (se existir)
        with ac2:
            pdf_path = unit_run.get("pdf_path")
            if pdf_path and Path(pdf_path).exists():
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        "Baixar PDF", data=f,
                        file_name=Path(pdf_path).name,
                        mime="application/pdf",
                        key=f"act_dl_{uid}",
                        use_container_width=True,
                    )

        # Aprovar (PDF + salva + parâmetros + aprovação + volta)
        with ac3:
            if status in ("pendente", "gerado", "revisado", "reaberto", "erro"):
                if st.button("Aprovar", key=f"act_apr_{uid}",
                             type="primary" if r is not None else "secondary",
                             use_container_width=True):
                    r_atual = resultados.get(uid) or rm.load_resultado_from_db(mes_ref, uid)
                    if r_atual is None:
                        st.error("Calcule antes de aprovar.")
                    else:
                        try:
                            r_atual.status = "aprovado"
                            r_atual.mes_referencia = mes_ref
                            salvar_lancamento(r_atual)
                            rm.generate_report(mes_ref, uid, r_atual)
                            params = st.session_state.get(f"params_usados_{uid}")
                            if not params:
                                from app.models import _extrair_editaveis
                                u_cfg = get_unit_com_params(uid, mes_ref)
                                params = {}
                                _extrair_editaveis(u_cfg, params)
                            if params:
                                salvar_parametros(uid, mes_ref, params, alterado_por="aprovacao")
                            rm.mark_approved(mes_ref, uid)
                            # A partir daqui, os parâmetros vigentes (aprovados)
                            # são a fonte de verdade — o rascunho de trabalho
                            # desta competência não é mais necessário.
                            from app.models import limpar_rascunho_unidade
                            limpar_rascunho_unidade(uid, mes_ref)
                            st.session_state.selected_unit = None
                            st.rerun()
                        except Exception as e:
                            rm.mark_error(mes_ref, uid, str(e))
                            st.error(f"Erro na aprovação: {e}")

        # Reabrir — desfaz uma aprovação: tratamento visual distinto
        with ac4:
            if status == "aprovado":
                with st.container(key="vd-danger-action"):
                    if st.button("Reabrir", key=f"act_reab_{uid}", use_container_width=True):
                        try:
                            rm.reopen(mes_ref, uid)
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))


# ─── histórico da unidade ─────────────────────────────────────────────────────

def _secao_historico_unificada(uid: str, unit_run: dict):
    """Histórico da unidade em um único ponto da página, com dois sub-blocos
    sem ambiguidade de nome: versões desta competência e competências
    anteriores. Dados e lógica de ambos são exatamente os já existentes —
    apenas reunidos visualmente."""
    import pandas as pd

    with st.expander("Histórico", expanded=False):
        # ── Versões desta competência (workflow: gerar/revisar/aprovar) ─────
        st.markdown('<p class="vd-hist-sub">Versões desta competência</p>', unsafe_allow_html=True)
        tc1, tc2, tc3 = st.columns(3)
        tc1.caption(f"Gerado: {_ts(unit_run.get('last_generated_at'))}")
        tc2.caption(f"Revisado: {_ts(unit_run.get('last_reviewed_at'))}")
        tc3.caption(f"Aprovado: {_ts(unit_run.get('last_approved_at'))}")
        versions = unit_run.get("versions", [])
        if versions:
            for v in reversed(versions):
                vc1, vc2, vc3 = st.columns([1, 3, 1])
                vc1.caption(f"v{v['version']}")
                vc2.caption(f"{_ts(v['created_at'])} — {v['status_at_time']}")
                vp = v.get("pdf_path", "")
                if vp and Path(vp).exists():
                    with open(vp, "rb") as f:
                        vc3.download_button("PDF", data=f, file_name=Path(vp).name,
                                            mime="application/pdf",
                                            key=f"dl_v{v['version']}_{uid}",
                                            use_container_width=True)
        else:
            st.caption("Nenhuma versão gerada ainda nesta competência.")

        # ── Competências anteriores (DRE por mês) ───────────────────────────
        lancamentos = _get_historico_lancamentos(uid)
        sub_label = (
            f"Competências anteriores ({len(lancamentos)})" if lancamentos
            else "Competências anteriores"
        )
        st.markdown(f'<p class="vd-hist-sub">{sub_label}</p>', unsafe_allow_html=True)
        if not lancamentos:
            st.caption("Nenhum fechamento registrado ainda.")
            return

        # Monta DRE na mesma ordem de _mostrar_resultado_unit — mesma lógica
        # de sempre, sem alteração de linhas ou ordem.
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
        st.dataframe(df, use_container_width=True)

        # Exportar CSV
        csv = df.to_csv().encode("utf-8")
        st.download_button(
            "Exportar CSV",
            data=csv,
            file_name=f"historico_{uid}.csv",
            mime="text/csv",
            key=f"csv_hist_{uid}",
            use_container_width=True,
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

    # Rascunho de trabalho do Pátio — mesmo mecanismo das unidades simples.
    _salvar_rascunho("patio", mes_ref, _CHAVES_PATIO)

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
        if st.button("Calcular Pátio", type="primary", key="calc_patio", use_container_width=True):
            if fat <= 0:
                st.error("Informe o faturamento.")
            else:
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
                status_real = rm.get_unit_run(mes_ref, "patio_real")["status"]
                status_maiojama = rm.get_unit_run(mes_ref, "patio_maiojama")["status"]
                if _patio_precisa_confirmar_recalculo(status_real, status_maiojama):
                    _dialog_confirmar_recalculo_patio(mes_ref, fat, extras, status_real, status_maiojama)
                else:
                    _executar_calculo_patio(mes_ref, fat, extras)

    st.divider()
    _barra_acoes_patio(mes_ref, resultados, run)


def _patio_precisa_confirmar_recalculo(status_real: str, status_maiojama: str) -> bool:
    """True quando recalcular o Pátio afetaria silenciosamente um contratante
    já aprovado — os campos compartilhados (faturamento total, outros
    serviços, carregadores) alimentam o cálculo de REAL e MAIOJAMA ao mesmo
    tempo, mesmo que só um deles tenha sido reaberto."""
    return status_real == "aprovado" or status_maiojama == "aprovado"


def _patio_deve_limpar_rascunho(status_real: str, status_maiojama: str) -> bool:
    """O rascunho sintético 'patio' só é limpo quando os DOIS contratantes
    estiverem aprovados na competência — se apenas um estiver, o outro ainda
    pode precisar dos mesmos campos compartilhados para ser calculado/aprovado."""
    return status_real == "aprovado" and status_maiojama == "aprovado"


def _executar_calculo_patio(mes_ref: str, fat: float, extras: dict):
    try:
        resultado = calcular("patio", mes_ref, fat, extras_patio=extras)
        _salvar_resultado_session("patio", fat, resultado)
        st.rerun()
    except Exception as e:
        st.error(f"Erro: {e}")


@st.dialog("Confirmar recálculo do Pátio")
def _dialog_confirmar_recalculo_patio(mes_ref: str, fat: float, extras: dict,
                                       status_real: str, status_maiojama: str):
    """Não recalcula silenciosamente: avisa explicitamente que os campos
    compartilhados do Pátio também alimentam o cálculo do contratante já
    aprovado, antes de prosseguir."""
    aprovados = []
    if status_real == "aprovado":
        aprovados.append("REAL")
    if status_maiojama == "aprovado":
        aprovados.append("MAIOJAMA")
    nomes = " e ".join(aprovados)
    st.write(
        f"**{nomes}** já está aprovado nesta competência. Os campos compartilhados "
        "(faturamento total, outros serviços, carregadores) alimentam o cálculo dos "
        f"dois contratantes ao mesmo tempo — recalcular agora também recalcula os "
        f"valores de {nomes}, mesmo que não tenha sido reaberto."
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()
    with c2:
        if st.button("Recalcular mesmo assim", type="primary", use_container_width=True):
            _executar_calculo_patio(mes_ref, fat, extras)


def _barra_acoes_patio(mes_ref: str, resultados: dict, run: dict):
    r_patio = resultados.get("patio")
    for sub_uid, split_id in [("patio_real", "real"), ("patio_maiojama", "maiojama")]:
        ur = rm.get_unit_run(mes_ref, sub_uid)
        status = ur["status"]
        st.markdown(
            f'**{_display_name(sub_uid)}**  <span class="vd-sep">·</span>  {_status_chip_html(status)}',
            unsafe_allow_html=True,
        )

        with st.container(key=f"vd-decisao-final-{sub_uid}"):
            bc1, bc2, bc3, bc4 = st.columns(4)
            with bc1:
                if st.button("Gerar PDF", key=f"wf_gen_{sub_uid}", use_container_width=True):
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
                        st.download_button("Baixar PDF", data=f, file_name=Path(pdf_path).name,
                                           mime="application/pdf",
                                           key=f"wf_dl_{sub_uid}", use_container_width=True)

            with bc3:
                if status in ("pendente", "gerado", "revisado", "reaberto", "erro") and r_patio:
                    if st.button("Aprovar", key=f"wf_apr_{sub_uid}",
                                 type="primary", use_container_width=True):
                        split_r = r_patio.real if split_id == "real" else r_patio.maiojama
                        split_r.status = "aprovado"
                        split_r.mes_referencia = mes_ref
                        salvar_lancamento(split_r)
                        try:
                            rm.generate_report(mes_ref, sub_uid, split_r,
                                               patio_split_id=split_id, patio_resultado=r_patio)
                            rm.mark_approved(mes_ref, sub_uid)
                            # Limpa o rascunho compartilhado só quando REAL e
                            # MAIOJAMA já estiverem os dois aprovados nesta
                            # competência — enquanto só um estiver, o outro
                            # ainda pode precisar dos mesmos campos.
                            outro_uid = "patio_maiojama" if sub_uid == "patio_real" else "patio_real"
                            outro_status = rm.get_unit_run(mes_ref, outro_uid)["status"]
                            status_real = "aprovado" if sub_uid == "patio_real" else outro_status
                            status_maiojama = "aprovado" if sub_uid == "patio_maiojama" else outro_status
                            if _patio_deve_limpar_rascunho(status_real, status_maiojama):
                                from app.models import limpar_rascunho_unidade
                                limpar_rascunho_unidade("patio", mes_ref)
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

            with bc4:
                if status == "aprovado":
                    with st.container(key=f"vd-danger-action-{sub_uid}"):
                        if st.button("Reabrir", key=f"wf_reab_{sub_uid}", use_container_width=True):
                            try:
                                rm.reopen(mes_ref, sub_uid)
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

        st.divider()


# ─── resultado visual ─────────────────────────────────────────────────────────

def _mostrar_resultado_unit(r: ResultadoUnidade):
    """Memória de cálculo — mesma estrutura e ordem de linhas já utilizadas
    pela Lyon Park. Os cards que repetiam a primeira e a última linha desta
    tabela (Faturamento/Resultado/Aluguel) foram removidos: a leitura desses
    valores passa a acontecer uma única vez, aqui."""
    import pandas as pd
    extras = r.extras or {}

    aluguel_label = "Saldo a Pagar" if extras.get("saldo_a_pagar") is not None else "Repasse / Aluguel"
    aluguel_val = extras.get("saldo_a_pagar", r.aluguel_calculado)

    # Métricas que não pertencem à memória de cálculo (não fazem parte da DRE)
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
    receita_selos = extras.get("receita_selos", 0.0)
    fat_carregadores = extras.get("fat_carregadores", 0.0)
    rows = []
    if receita_selos:
        # Fiergs: composição explícita — nunca soma silenciosamente.
        rows.append(("Faturamento", _fmt(r.faturamento - receita_selos)))
        rows.append(("Receita de Selos", _fmt(receita_selos)))
        rows.append(("Receita Bruta", _fmt(r.faturamento)))
        if r.subtotal and r.subtotal != r.faturamento:
            rows.append(("(-) Impostos / ISS", _fmt(r.faturamento - r.subtotal)))
            rows.append(("Subtotal", _fmt(r.subtotal)))
    elif fat_carregadores:
        # In 1183: Total Faturamento = Estacionamento + Carregadores — mesma
        # composição explícita já usada no PDF (_prestacao_padrao).
        rows.append(("Faturamento Estacionamento", _fmt(r.faturamento - fat_carregadores)))
        rows.append(("(+) Faturamento Carregadores", _fmt(fat_carregadores)))
        rows.append(("Total Faturamento", _fmt(r.faturamento)))
        if r.subtotal and r.subtotal != r.faturamento:
            rows.append(("(-) Impostos / ISS", _fmt(r.faturamento - r.subtotal)))
            rows.append(("Subtotal", _fmt(r.subtotal)))
    elif r.subtotal and r.subtotal != r.faturamento:
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
            column_config={
                "": st.column_config.TextColumn("", width="large"),
                "Valor": st.column_config.TextColumn("Valor", width="medium"),
            },
        )


def _mostrar_resultado_patio(r: ResultadoPatio):
    # Um contratante abaixo do outro — evita a rolagem horizontal que a
    # exibição lado a lado forçava dentro da coluna de resultado (item 7 da
    # sprint v1.1.1). Nenhuma regra de cálculo foi alterada, só o layout.
    st.caption("**REAL (53,52%)**")
    _mostrar_resultado_unit(r.real)
    st.divider()
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
        sheet = fat_data.get("sheet")
        nao_map = fat_data.get("nao_mapeados") or []
        sem_fat = fat_data.get("sem_fat") or []

        c1, c2 = st.columns([5, 1])
        with c1:
            linha = f"{n} unidades importadas · Total {_fmt(total)}"
            if sheet:
                linha += f' · aba "{sheet}"'
            st.markdown(f'<div class="vd-upload-ok">{linha}</div>', unsafe_allow_html=True)

            # Avisos permanecem visíveis enquanto houver pendência de importação —
            # não dependem do instante exato do upload.
            avisos = []
            if sem_fat:
                nomes = [_display_name(u) for u in sem_fat]
                if len(nomes) > 6:
                    avisos.append(f"{len(nomes)} unidades sem faturamento nesta planilha")
                else:
                    avisos.append("Sem faturamento na planilha: " + ", ".join(nomes))
            if nao_map:
                avisos.append(
                    "Sem correspondência no sistema: " + ", ".join(a["nome"] for a in nao_map)
                )
            if avisos:
                linhas_aviso = "".join(f'<div class="vd-upload-warn">{a}</div>' for a in avisos)
                st.markdown(f'<div class="vd-upload-warn-group">{linhas_aviso}</div>', unsafe_allow_html=True)
        with c2:
            if st.button("Substituir", key="btn_sub_fat", use_container_width=True):
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
                st.markdown(
                    f'<div class="vd-upload-ok">{len(ev_mes)} eventos · {_fmt(total_ev)}</div>',
                    unsafe_allow_html=True,
                )
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
        st.success(f"Eventos importados | {_fmt(total_ev)}")
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
    fat_path = RUNS_DIR / mes_ref / "processed" / "faturamento.json"
    if fat_path.exists():
        fat_path.unlink()
    if "faturamentos" in st.session_state:
        st.session_state.faturamentos = {}


def _limpar_ev_uid(mes_ref: str, uid: str):
    p = RUNS_DIR / mes_ref / "processed" / f"eventos_{uid}.json"
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


@st.dialog("Aprovar todas as unidades geradas")
def _dialog_confirmar_aprovar_todos(mes_ref: str, todos_uids: list):
    """Confirmação antes da aprovação em massa — reduz risco de clique errado.
    Não altera a lógica de aprovação: apenas intercala uma etapa de confirmação
    antes de chamar a mesma função _aprovar_todos_gerados já existente."""
    st.write("Deseja realmente aprovar todas as unidades geradas?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()
    with c2:
        if st.button("Aprovar", type="primary", use_container_width=True):
            _aprovar_todos_gerados(mes_ref, todos_uids)
            st.rerun()


def _download_zip(mes_ref: str, todos_uids: list, run: dict):
    disponiveis = [
        uid for uid in todos_uids
        if run.get(uid, {}).get("status") in ("gerado", "revisado", "aprovado")
        and run.get(uid, {}).get("pdf_path")
        and Path(run[uid]["pdf_path"]).exists()
    ]
    if not disponiveis:
        st.button("Baixar ZIP", disabled=True, use_container_width=True)
        return
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for uid in disponiveis:
            p = run[uid]["pdf_path"]
            zf.write(p, Path(p).name)
    buf.seek(0)
    st.download_button(
        f"Baixar ZIP ({len(disponiveis)} PDFs)",
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
