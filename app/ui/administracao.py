"""
Administração > Unidades — cadastro e edição dos dados ESTRUTURAIS das
unidades (nome, contratante, início, modelo de cálculo, tipo de relatório,
status). Deliberadamente separada do fluxo operacional de fechamento
(app.ui.fechamento) — reaproveita a mesma linguagem visual (_CSS, marca
Valandro) sem redesenhar nada.

Ainda NÃO cobre (etapa seguinte): editor de parâmetros por modelo,
vigências, faixas, splits, repasses, rubricas de custo dinâmicas. Uma
unidade criada aqui nasce "Em configuração" (ativo=0, sem nenhuma linha em
parametros_vigentes) e só pode ser ativada depois de ter algum parâmetro
definido — hoje ainda não existe uma tela dedicada para isso; a proteção
desta etapa é simplesmente não oferecer a opção de ativar enquanto não
houver nenhum parâmetro.
"""
import re
import unicodedata
from datetime import date

import streamlit as st

from app.ui.fechamento import _CSS, _VALANDRO_LOGO_URI
from app.calculadora_labels import (
    TIPO_CALCULO_LABELS, TIPO_CALCULO_DESCRICOES, TIPO_RELATORIO_LABELS,
    TIPOS_CALCULO_PARA_CADASTRO, TIPOS_RELATORIO_PARA_CADASTRO,
)
from app.models import (
    listar_unidades_admin, get_unidade, criar_unidade, atualizar_unidade,
    unidade_id_existe, unidade_possui_lancamentos, status_unidade,
    unidades_exemplo_por_tipo,
)
from app.engine import load_units

_ADMIN_CSS = """
<style>
.vd-status--admin-ativa .vd-status-dot   { background: var(--vd-green); }
.vd-status--admin-ativa                  { color: var(--vd-green); font-weight: 600; }
.vd-status--admin-config .vd-status-dot  { background: var(--vd-amber); }
.vd-status--admin-config                 { color: var(--vd-amber); }
.vd-status--admin-inativa .vd-status-dot { background: var(--vd-faint); }
.vd-status--admin-inativa                { color: var(--vd-muted); }
</style>
"""

_STATUS_LABELS = {
    "ativa": "Ativa",
    "em_configuracao": "Em configuração",
    "inativa": "Inativa",
}
_STATUS_CSS_GRUPO = {
    "ativa": "admin-ativa",
    "em_configuracao": "admin-config",
    "inativa": "admin-inativa",
}


def _status_chip(status: str) -> str:
    grupo = _STATUS_CSS_GRUPO.get(status, "admin-inativa")
    label = _STATUS_LABELS.get(status, status)
    return f'<span class="vd-status vd-status--{grupo}"><span class="vd-status-dot"></span>{label}</span>'


def _fmt_data(iso: str) -> str:
    try:
        ano, mes, dia = iso.split("-")
        return f"{dia}/{mes}/{ano}"
    except Exception:
        return iso or "—"


def _gerar_id_sugerido(nome: str) -> str:
    """snake_case sem acentos, a partir do nome — ex.: "Shopping São José"
    -> "shopping_sao_jose". Só uma sugestão: o operador pode ajustar antes
    de salvar (ver checkbox "Ajustar identificador manualmente")."""
    nome = unicodedata.normalize("NFKD", nome or "")
    nome = nome.encode("ascii", "ignore").decode("ascii").lower()
    nome = re.sub(r"[^a-z0-9]+", "_", nome).strip("_")
    return re.sub(r"_+", "_", nome)


def _voltar_ao_fechamento():
    st.session_state.area = "fechamento"
    st.session_state.pop("admin_view", None)
    st.session_state.pop("admin_editar_uid", None)
    st.rerun()


def _cabecalho(titulo: str):
    st.markdown(
        f'<img src="{_VALANDRO_LOGO_URI}" class="vd-brand-mark" alt="Valandro" />',
        unsafe_allow_html=True,
    )
    col_titulo, col_voltar = st.columns([4, 1])
    with col_titulo:
        st.markdown(
            f'<div class="vd-comp-label">Administração</div>'
            f'<div class="vd-comp-value">{titulo}</div>',
            unsafe_allow_html=True,
        )
    with col_voltar:
        if st.button("← Voltar ao Fechamento", key="admin_voltar_topo", use_container_width=True):
            _voltar_ao_fechamento()
    st.divider()


def tela_administracao_unidades():
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(_ADMIN_CSS, unsafe_allow_html=True)

    view = st.session_state.get("admin_view", "lista")
    if view == "nova":
        _tela_nova_unidade()
    elif view == "editar":
        _tela_editar_unidade(st.session_state.get("admin_editar_uid"))
    else:
        _tela_lista_unidades()


# ═══════════════════════════════════════════════════════════════════════════
# LISTA
# ═══════════════════════════════════════════════════════════════════════════

def _tela_lista_unidades():
    _cabecalho("Unidades")

    col_filtro, col_novo = st.columns([3, 1])
    with col_filtro:
        filtro = st.radio(
            "Filtro de status", ["Todas", "Ativas", "Em configuração", "Inativas"],
            horizontal=True, label_visibility="collapsed", key="admin_filtro",
        )
    with col_novo:
        if st.button("+ Nova Unidade", type="primary", use_container_width=True, key="admin_nova_btn"):
            st.session_state.admin_view = "nova"
            st.rerun()

    filtro_status = {
        "Todas": None, "Ativas": "ativa",
        "Em configuração": "em_configuracao", "Inativas": "inativa",
    }[filtro]

    linhas = []
    for u in listar_unidades_admin():
        status = status_unidade(u)
        if filtro_status and status != filtro_status:
            continue
        linhas.append((u, status))

    if not linhas:
        st.info("Nenhuma unidade neste filtro.")
        return

    for u, status in linhas:
        modelo = TIPO_CALCULO_LABELS.get(u["tipo_calculo"], u["tipo_calculo"])
        relatorio = TIPO_RELATORIO_LABELS.get(u["tipo_relatorio"], u["tipo_relatorio"])
        c1, c2, c3, c4 = st.columns([3, 3, 2, 1])
        with c1:
            st.markdown(f"**{u['nome']}**")
            st.caption(u["contratante"])
        with c2:
            st.write(modelo)
            st.caption(f"{relatorio} · Início {_fmt_data(u['inicio'])}")
        with c3:
            st.markdown(_status_chip(status), unsafe_allow_html=True)
        with c4:
            if st.button("Editar", key=f"admin_editar_{u['id']}", use_container_width=True):
                st.session_state.admin_view = "editar"
                st.session_state.admin_editar_uid = u["id"]
                st.rerun()
        st.divider()


# ═══════════════════════════════════════════════════════════════════════════
# AJUDA CONTEXTUAL DO MODELO DE CÁLCULO
# ═══════════════════════════════════════════════════════════════════════════

def _ajuda_modelos():
    with st.expander("Entenda os modelos de cálculo"):
        for t in TIPOS_CALCULO_PARA_CADASTRO:
            st.markdown(f"**{TIPO_CALCULO_LABELS[t]}**")
            st.caption(TIPO_CALCULO_DESCRICOES[t])
            exemplos = unidades_exemplo_por_tipo(t)
            if exemplos:
                st.caption(f"Usado atualmente em: {', '.join(exemplos)}.")
            st.write("")


def _descricao_modelo_selecionado(tipo_calculo: str):
    st.info(TIPO_CALCULO_DESCRICOES.get(tipo_calculo, ""))
    exemplos = unidades_exemplo_por_tipo(tipo_calculo)
    if exemplos:
        st.caption(f"Usado atualmente em: {', '.join(exemplos)}.")


# ═══════════════════════════════════════════════════════════════════════════
# NOVA UNIDADE
# ═══════════════════════════════════════════════════════════════════════════

def _tela_nova_unidade():
    _cabecalho("Nova Unidade")

    if st.button("Cancelar", key="admin_nova_cancelar"):
        st.session_state.admin_view = "lista"
        st.rerun()

    nome = st.text_input("Nome da unidade", key="admin_nova_nome")
    id_sugerido = _gerar_id_sugerido(nome)

    ajustar_id = st.checkbox("Ajustar identificador manualmente", key="admin_nova_ajustar_id")
    if ajustar_id:
        id_final = st.text_input(
            "Identificador da unidade",
            value=st.session_state.get("admin_nova_id_manual") or id_sugerido,
            key="admin_nova_id_manual",
            help="Só letras minúsculas, números e underscore. Não pode ser alterado depois de criada.",
        )
    else:
        id_final = id_sugerido
        st.caption(f"Identificador gerado: `{id_final or '—'}`")

    contratante = st.text_input("Contratante", key="admin_nova_contratante")
    inicio = st.date_input("Início da operação", value=date.today(), key="admin_nova_inicio")

    st.markdown("**Modelo de cálculo**")
    _ajuda_modelos()
    modelo_labels = [TIPO_CALCULO_LABELS[t] for t in TIPOS_CALCULO_PARA_CADASTRO]
    modelo_label_sel = st.selectbox(
        "Modelo de cálculo", modelo_labels, label_visibility="collapsed", key="admin_nova_modelo_label",
    )
    tipo_calculo = TIPOS_CALCULO_PARA_CADASTRO[modelo_labels.index(modelo_label_sel)]
    _descricao_modelo_selecionado(tipo_calculo)

    relatorio_labels = [TIPO_RELATORIO_LABELS[t] for t in TIPOS_RELATORIO_PARA_CADASTRO]
    relatorio_label_sel = st.selectbox("Tipo de relatório", relatorio_labels, key="admin_nova_relatorio_label")
    tipo_relatorio = TIPOS_RELATORIO_PARA_CADASTRO[relatorio_labels.index(relatorio_label_sel)]

    st.divider()
    if st.button("Salvar", type="primary", key="admin_nova_salvar"):
        erros = []
        if not nome.strip():
            erros.append("Informe o nome da unidade.")
        if not id_final:
            erros.append("Não foi possível gerar um identificador a partir do nome — ajuste o nome ou o identificador manualmente.")
        elif unidade_id_existe(id_final):
            erros.append(f"Já existe uma unidade com o identificador '{id_final}'. Ajuste o nome ou o identificador.")
        if not contratante.strip():
            erros.append("Informe o contratante.")

        if erros:
            for e in erros:
                st.error(e)
            return

        criar_unidade(
            id=id_final, nome=nome.strip(), contratante=contratante.strip(),
            inicio=inicio.isoformat(), tipo_calculo=tipo_calculo, tipo_relatorio=tipo_relatorio,
        )
        load_units(force=True)
        st.session_state.admin_view = "editar"
        st.session_state.admin_editar_uid = id_final
        st.session_state.admin_msg = (
            f"Unidade '{nome.strip()}' criada como **Em configuração**. "
            "Configure os parâmetros de cálculo antes de ativar esta unidade."
        )
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# EDITAR UNIDADE
# ═══════════════════════════════════════════════════════════════════════════

def _tela_editar_unidade(uid: str):
    u = get_unidade(uid) if uid else None
    if not u:
        st.error("Unidade não encontrada.")
        if st.button("Voltar", key="admin_editar_naoencontrada_voltar"):
            st.session_state.admin_view = "lista"
            st.rerun()
        return

    _cabecalho(f"Editar — {u['nome']}")

    msg = st.session_state.pop("admin_msg", None)
    if msg:
        st.success(msg)

    if st.button("← Voltar à lista", key="admin_editar_voltar_lista"):
        st.session_state.admin_view = "lista"
        st.rerun()

    st.caption(f"Identificador: `{u['id']}` — não pode ser alterado")

    nome = st.text_input("Nome da unidade", value=u["nome"], key=f"admin_edit_nome_{uid}")
    contratante = st.text_input("Contratante", value=u["contratante"], key=f"admin_edit_contratante_{uid}")
    try:
        inicio_atual = date.fromisoformat(u["inicio"])
    except (TypeError, ValueError):
        inicio_atual = date.today()
    inicio = st.date_input("Início da operação", value=inicio_atual, key=f"admin_edit_inicio_{uid}")

    st.markdown("**Modelo de cálculo**")
    tem_lancamentos = unidade_possui_lancamentos(uid)
    modelo_opcoes = list(TIPOS_CALCULO_PARA_CADASTRO)
    if u["tipo_calculo"] not in modelo_opcoes:
        modelo_opcoes.append(u["tipo_calculo"])  # ex.: PATIO_OPERACAO, na edição do Pátio
    modelo_labels = [TIPO_CALCULO_LABELS.get(t, t) for t in modelo_opcoes]
    idx_atual = modelo_opcoes.index(u["tipo_calculo"])

    if tem_lancamentos:
        st.selectbox(
            "Modelo de cálculo", modelo_labels, index=idx_atual, disabled=True,
            label_visibility="collapsed", key=f"admin_edit_modelo_disabled_{uid}",
        )
        st.caption("Não é possível alterar o modelo de uma unidade que já possui lançamento registrado.")
        tipo_calculo = u["tipo_calculo"]
    else:
        modelo_label_sel = st.selectbox(
            "Modelo de cálculo", modelo_labels, index=idx_atual,
            label_visibility="collapsed", key=f"admin_edit_modelo_{uid}",
        )
        tipo_calculo = modelo_opcoes[modelo_labels.index(modelo_label_sel)]
        if tipo_calculo in TIPO_CALCULO_DESCRICOES:
            st.caption(TIPO_CALCULO_DESCRICOES[tipo_calculo])

    relatorio_opcoes = list(TIPOS_RELATORIO_PARA_CADASTRO)
    if u["tipo_relatorio"] not in relatorio_opcoes:
        relatorio_opcoes.append(u["tipo_relatorio"])  # ex.: com_receitas_extras, na edição do Pátio
    relatorio_labels = [TIPO_RELATORIO_LABELS.get(t, t) for t in relatorio_opcoes]
    rel_idx_atual = relatorio_opcoes.index(u["tipo_relatorio"])
    relatorio_sel = st.selectbox(
        "Tipo de relatório", relatorio_labels, index=rel_idx_atual, key=f"admin_edit_relatorio_{uid}",
    )
    tipo_relatorio = relatorio_opcoes[relatorio_labels.index(relatorio_sel)]

    st.markdown("**Status**")
    status_atual = status_unidade(u)
    st.markdown(_status_chip(status_atual), unsafe_allow_html=True)
    if status_atual == "em_configuracao":
        st.warning("Configure os parâmetros de cálculo antes de ativar esta unidade.")
        ativo_novo = False
    else:
        ativo_novo = st.toggle("Unidade ativa", value=bool(u["ativo"]), key=f"admin_edit_ativo_{uid}")

    st.divider()
    if st.button("Salvar alterações", type="primary", key=f"admin_edit_salvar_{uid}"):
        erros = []
        if not nome.strip():
            erros.append("Informe o nome da unidade.")
        if not contratante.strip():
            erros.append("Informe o contratante.")
        if erros:
            for e in erros:
                st.error(e)
            return

        atualizar_unidade(
            uid, nome=nome.strip(), contratante=contratante.strip(),
            inicio=inicio.isoformat(), tipo_calculo=tipo_calculo,
            tipo_relatorio=tipo_relatorio, ativo=ativo_novo,
        )
        load_units(force=True)
        st.session_state.admin_msg = "Alterações salvas."
        st.rerun()
