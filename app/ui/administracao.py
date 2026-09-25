"""
Administração > Unidades — cadastro e edição dos dados ESTRUTURAIS das
unidades (nome, contratante, início, modelo de cálculo, tipo de relatório,
status) e, na aba Parâmetros, dos parâmetros ESCALARES e BOOLEANOS
vigência-tracked de cada modelo. Deliberadamente separada do fluxo
operacional de fechamento (app.ui.fechamento) — reaproveita a mesma
linguagem visual (_CSS, marca Valandro) sem redesenhar nada.

Status: dois eixos SEPARADOS, nunca misturados numa heurística única —
status operacional (`status_operacional`: "ativa"/"inativa", direto do
campo `ativo`) e status de configuração (`status_configuracao`:
"completa"/"incompleta"/"nao_aplicavel", direto de
`validar_configuracao_unidade`). "Em configuração" continua existindo só
como linguagem de UX na lista — é a apresentação de "inativa + incompleta"
juntas, nunca uma regra técnica própria. Uma unidade criada aqui nasce
`ativo=0`; ativar/inativar é sempre uma ação explícita da operadora (aba
Dados da Unidade), nunca automática — nem ao salvar parâmetros, nem por
falha de validação numa unidade já ativa. Ver `pode_ativar_unidade`
(app.models) para a regra completa (competência >= início estrutural +
configuração completa naquela competência).

Datas (`st.date_input`, campo "Início da operação"): `format="DD/MM/YYYY"`
é o único ajuste de localização nativamente suportado pelo Streamlit
1.58 — controla só o texto exibido no campo, não o idioma do calendário.
Nomes de mês e abreviação dos dias da semana no popup do calendário
continuam em inglês; não há parâmetro de locale/idioma para isso, e
nenhuma solução via CSS/JS foi aplicada aqui (seria frágil e quebraria em
atualizações do componente).

Competência (aba Parâmetros): representada só por mês/ano (dois
`st.selectbox`), nunca por `st.date_input` — uma competência não tem "dia",
e o componente de data do Streamlit não tem um modo "só mês" nativo. Ver
`_competencia_picker`.

Percentual (aba Parâmetros): armazenamento interno continua decimal
(0.15), exibição na UI é percentual (15,00%) — conversão centralizada em
`_pct_armazenado_para_ui`/`_pct_ui_para_armazenado`, nunca duplicada
inline. Limitação conhecida: o widget `st.number_input` em si usa ponto
como separador decimal (ex. "15.00"), não vírgula — não há locale pt-BR
nativo no componente; a formatação com vírgula (`_formatar_valor`) é usada
nos textos de leitura (histórico, valores compostos), não dentro do campo
editável em si.
"""
import hashlib
import json
import re
import unicodedata
from datetime import date

import pandas as pd
import streamlit as st

from app.ui.fechamento import _CSS, _VALANDRO_LOGO_URI
from app.calculadora_labels import (
    TIPO_CALCULO_LABELS, TIPO_CALCULO_DESCRICOES, TIPO_RELATORIO_LABELS,
    TIPOS_CALCULO_PARA_CADASTRO, TIPOS_RELATORIO_PARA_CADASTRO,
)
from app.calculadora_schema import (
    campos_do_tipo, campo_por_chave, validacoes_do_tipo,
    resolver_valor, campo_obrigatorio_efetivo,
    validar_estrutura_lista, validar_regra_cruzada,
)
from app.models import (
    listar_unidades_admin, get_unidade, criar_unidade, atualizar_unidade,
    unidade_id_existe, unidade_possui_lancamentos,
    status_operacional, status_configuracao, pode_ativar_unidade,
    unidades_exemplo_por_tipo, get_parametros_vigentes, salvar_parametros,
    get_historico_parametros, validar_configuracao_unidade,
    seed_parametros_from_yaml, definir_aucon_codigo_filial,
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

# Status OPERACIONAL — "ativa"/"inativa", direto de status_operacional().
_STATUS_LABELS = {"ativa": "Ativa", "inativa": "Inativa"}
_STATUS_CSS_GRUPO = {"ativa": "admin-ativa", "inativa": "admin-inativa"}


def _status_chip(status: str) -> str:
    grupo = _STATUS_CSS_GRUPO.get(status, "admin-inativa")
    label = _STATUS_LABELS.get(status, status)
    return f'<span class="vd-status vd-status--{grupo}"><span class="vd-status-dot"></span>{label}</span>'


# Status de CONFIGURAÇÃO — eixo separado, direto de status_configuracao().
_CONFIG_LABELS = {
    "completa": "Configuração completa",
    "incompleta": "Configuração incompleta",
    "nao_aplicavel": "Configuração não aplicável",
}
_CONFIG_CSS_GRUPO = {"completa": "admin-ativa", "incompleta": "admin-config", "nao_aplicavel": "admin-inativa"}
_CONFIG_ICONE = {"completa": "✓", "incompleta": "⚠"}


def _config_chip(status_config: str) -> str:
    grupo = _CONFIG_CSS_GRUPO.get(status_config, "admin-inativa")
    label = _CONFIG_LABELS.get(status_config, status_config)
    icone = _CONFIG_ICONE.get(status_config, "—")
    return f'<span class="vd-status vd-status--{grupo}"><span class="vd-status-dot"></span>{icone} {label}</span>'


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
        # Filtro é só sobre o eixo OPERACIONAL (ativa/inativa) — configuração
        # completa/incompleta é um eixo separado, mostrado por linha (badge),
        # nunca uma opção de filtro própria. "Em configuração" (inativa +
        # incompleta) continua existindo como legenda na própria linha, não
        # como categoria de filtro — ver comentário abaixo, junto ao badge.
        filtro = st.radio(
            "Filtro de status", ["Todas", "Ativas", "Inativas"],
            horizontal=True, label_visibility="collapsed", key="admin_filtro",
        )
    with col_novo:
        if st.button("+ Nova Unidade", type="primary", use_container_width=True, key="admin_nova_btn"):
            st.session_state.admin_view = "nova"
            st.rerun()

    filtro_status = {"Todas": None, "Ativas": "ativa", "Inativas": "inativa"}[filtro]

    linhas = []
    for u in listar_unidades_admin():
        operacional = status_operacional(u)
        if filtro_status and operacional != filtro_status:
            continue
        # max(competência atual, início) — nunca avalia uma unidade nova
        # como "incompleta" num mês anterior ao início dela (rodada de
        # correção Nilo Square).
        config = status_configuracao(u, _competencia_avaliacao_padrao(u))
        linhas.append((u, operacional, config))

    if not linhas:
        st.info("Nenhuma unidade neste filtro.")
        return

    for u, operacional, config in linhas:
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
            st.markdown(_status_chip(operacional), unsafe_allow_html=True)
            st.markdown(_config_chip(config), unsafe_allow_html=True)
            if operacional == "inativa" and config == "incompleta":
                # "Em configuração" como linguagem de UX — só a apresentação
                # de "inativa + incompleta" juntas, nunca uma regra própria.
                st.caption("Em configuração")
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
    inicio = st.date_input(
        "Início da operação", value=date.today(), format="DD/MM/YYYY", key="admin_nova_inicio",
    )

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

    aba_dados, aba_parametros = st.tabs(["Dados da Unidade", "Parâmetros"])
    with aba_dados:
        _aba_dados_unidade(uid, u)
    with aba_parametros:
        _aba_parametros(uid, u)


def _aba_dados_unidade(uid: str, u: dict):
    st.caption(f"Identificador: `{u['id']}` — não pode ser alterado")

    nome = st.text_input("Nome da unidade", value=u["nome"], key=f"admin_edit_nome_{uid}")
    contratante = st.text_input("Contratante", value=u["contratante"], key=f"admin_edit_contratante_{uid}")
    try:
        inicio_atual = date.fromisoformat(u["inicio"])
    except (TypeError, ValueError):
        inicio_atual = date.today()
    inicio = st.date_input(
        "Início da operação", value=inicio_atual, format="DD/MM/YYYY", key=f"admin_edit_inicio_{uid}",
    )

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

    st.markdown("**Integração Aucon/eCloud**")
    aucon_atual = u.get("aucon_codigo_filial")
    aucon_str = st.text_input(
        "Código de filial na Aucon (opcional)",
        value=str(aucon_atual) if aucon_atual else "",
        key=f"admin_edit_aucon_{uid}",
        help="Deixe em branco se esta unidade não usa integração Aucon/eCloud. "
             "Preenchido, habilita a busca automática de faturamento no Fechamento.",
    )

    st.divider()
    if st.button("Salvar alterações", type="primary", key=f"admin_edit_salvar_{uid}"):
        erros = []
        if not nome.strip():
            erros.append("Informe o nome da unidade.")
        if not contratante.strip():
            erros.append("Informe o contratante.")
        aucon_valor: int | None = None
        aucon_str_limpo = aucon_str.strip()
        if aucon_str_limpo:
            try:
                aucon_valor = int(aucon_str_limpo)
            except ValueError:
                erros.append("Código de filial na Aucon deve ser um número inteiro.")
        if erros:
            for e in erros:
                st.error(e)
            return

        # Nunca inclui `ativo` aqui — ativar/inativar é sempre uma ação
        # explícita e separada (ver _secao_status_ativacao), nunca um efeito
        # colateral de salvar os dados estruturais.
        atualizar_unidade(
            uid, nome=nome.strip(), contratante=contratante.strip(),
            inicio=inicio.isoformat(), tipo_calculo=tipo_calculo,
            tipo_relatorio=tipo_relatorio,
        )
        # Setter dedicado (não atualizar_unidade): aqui None significa
        # "desvincular da Aucon", uma escrita real — diferente do
        # contrato de atualizar_unidade, onde None significa "não mexer".
        definir_aucon_codigo_filial(uid, aucon_valor)
        load_units(force=True)
        st.session_state.admin_msg = "Alterações salvas."
        st.rerun()

    st.divider()
    _secao_status_ativacao(uid, u)


def _secao_status_ativacao(uid: str, u: dict):
    """Ativar/inativar é sempre uma ação explícita e imediata (não faz
    parte de "Salvar alterações", nem de salvar parâmetros). A competência
    usada para validar a ativação é a mesma "Competência de referência" já
    selecionada na aba Parâmetros — evita duas competências divergentes
    fazendo papéis parecidos. Funciona mesmo antes de a aba Parâmetros ter
    sido aberta nesta sessão: o valor default (mês atual) é o mesmo dos
    dois lados, e o session_state persiste entre reruns — na primeira
    renderização da tela ambas as abas ainda calculam o mesmo default; nas
    seguintes, o valor já refletido aqui é exatamente o que a operadora
    escolheu na aba Parâmetros, mesmo que esta função rode antes dela no
    mesmo script (o valor foi gravado no rerun anterior)."""
    st.markdown("**Status**")
    operacional = status_operacional(u)
    st.markdown(_status_chip(operacional), unsafe_allow_html=True)

    competencia = st.session_state.get(f"param_ref_valor_{uid}", _competencia_avaliacao_padrao(u))
    inicio_mes = (u.get("inicio") or "")[:7]

    if inicio_mes and competencia < inicio_mes:
        # A unidade sequer existia operacionalmente nesta competência —
        # não faz sentido listar Alíquota/PE/etc. como pendências dela.
        # Rodada de correção Nilo Square (início 01/10/2026 avaliado antes
        # em 09/2026, mês anterior ao início).
        st.info(f"Unidade ainda não estava em operação nesta competência. Início: {_fmt_competencia(inicio_mes)}.")
    else:
        erros_config = validar_configuracao_unidade(uid, competencia)
        config = status_configuracao(u, competencia)
        if config == "completa":
            st.success(f"✓ Configuração completa em {_fmt_competencia(competencia)}")
        elif config == "incompleta":
            st.warning(f"⚠ Configuração incompleta em {_fmt_competencia(competencia)}")
            for e in erros_config:
                st.markdown(f"- {e}")
        else:
            st.caption(f"Configuração não avaliada para este modelo de cálculo em {_fmt_competencia(competencia)}.")

    st.caption(
        f"Configuração avaliada em: {_fmt_competencia(competencia)} — a mesma \"Competência de "
        "referência\" selecionada na aba **Parâmetros**. Mude-a lá para avaliar outro mês."
    )

    if operacional == "ativa":
        if st.button("Inativar unidade", key=f"admin_inativar_{uid}"):
            atualizar_unidade(uid, ativo=False)
            load_units(force=True)
            st.session_state.admin_msg = "Unidade inativada."
            st.rerun()
        return

    # Inativa: só pode ativar se pode_ativar_unidade não apontar bloqueio
    # algum (início estrutural + configuração completa) NESSA competência.
    # pode_ativar_unidade() = [mensagem de início, quando aplicável] +
    # erros_config (os mesmos já listados acima) — aqui só mostramos a
    # parte que ainda não apareceu (início), para não duplicar a lista.
    bloqueios = pode_ativar_unidade(uid, competencia)
    bloqueios_inicio = [b for b in bloqueios if b not in erros_config]
    if bloqueios:
        for b in bloqueios_inicio:
            st.error(b)
        st.button("Ativar unidade", disabled=True, key=f"admin_ativar_{uid}")
        st.caption("Corrija os pontos acima para habilitar a ativação.")
    else:
        st.info(f"Configuração válida para {_fmt_competencia(competencia)}. Unidade pronta para ativação.")
        if st.button("Ativar unidade", type="primary", key=f"admin_ativar_{uid}"):
            atualizar_unidade(uid, ativo=True)
            load_units(force=True)
            st.session_state.admin_msg = (
                f"Unidade ativada (configuração validada para {_fmt_competencia(competencia)})."
            )
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# PARÂMETROS E VIGÊNCIAS
# ═══════════════════════════════════════════════════════════════════════════

_MESES_ABREV = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _competencia_picker(label: str, key_prefix: str, competencia_atual: str) -> str:
    """Seletor de competência em MM/AAAA — dois `st.selectbox` (mês/ano), nunca
    um datepicker diário: competência não tem "dia". Recebe/retorna sempre no
    formato interno "AAAA-MM"."""
    try:
        ano_atual, mes_atual = int(competencia_atual[:4]), int(competencia_atual[5:7])
    except (TypeError, ValueError, IndexError):
        hoje = date.today()
        ano_atual, mes_atual = hoje.year, hoje.month

    c1, c2 = st.columns([2, 1])
    with c1:
        mes = st.selectbox(
            label, list(range(1, 13)), index=mes_atual - 1,
            format_func=lambda m: _MESES_ABREV[m - 1], key=f"{key_prefix}_mes",
        )
    with c2:
        anos = list(range(2020, date.today().year + 3))
        idx_ano = anos.index(ano_atual) if ano_atual in anos else anos.index(date.today().year)
        ano = st.selectbox(
            "Ano", anos, index=idx_ano, key=f"{key_prefix}_ano", label_visibility="hidden",
        )
    return f"{ano}-{mes:02d}"


def _fmt_competencia(aaaa_mm: str) -> str:
    try:
        ano, mes = aaaa_mm.split("-")
        return f"{mes}/{ano}"
    except Exception:
        return aaaa_mm or "—"


def _competencia_avaliacao_padrao(u: dict) -> str:
    """Competência padrão para avaliar "configuração completa/incompleta"
    de uma unidade — `max(competência atual, início da operação)`.
    Homologação set/2026 (Nilo Square): antes desta correção, o padrão era
    sempre "hoje", então uma unidade nova cujo início ainda está no futuro
    era avaliada (e mostrada como "incompleta") num mês em que ela sequer
    existia operacionalmente. `pode_ativar_unidade` (app.models) já tinha
    essa proteção para a ATIVAÇÃO — esta função estende o mesmo princípio
    para a AVALIAÇÃO/exibição (chip da lista e aba Parâmetros), sem alterar
    `pode_ativar_unidade` em si."""
    hoje_aaaa_mm = date.today().strftime("%Y-%m")
    inicio_mes = (u.get("inicio") or "")[:7]
    return max(hoje_aaaa_mm, inicio_mes) if inicio_mes else hoje_aaaa_mm


def _pct_armazenado_para_ui(valor) -> float:
    """0.15 (decimal armazenado em parametros_vigentes) -> 15.0 (percentual
    exibido no campo). Ponto único de conversão — nunca duplicar este cálculo
    inline em outro lugar da tela."""
    if valor is None:
        return 0.0
    return round(float(valor) * 100, 4)


def _pct_ui_para_armazenado(valor_ui) -> float:
    """15.0 (percentual digitado na UI) -> 0.15 (decimal armazenado). Inverso
    exato de `_pct_armazenado_para_ui`."""
    return round(float(valor_ui or 0.0) / 100, 6)


def _formatar_valor(tipo_dado: str, valor) -> str:
    """Formata um valor de parâmetro para exibição amigável (nunca JSON cru),
    usado tanto na leitura de campos compostos quanto no histórico."""
    if valor is None:
        return "—"
    # Contêiner (lista_estruturada/mapa_rubricas): o tipo_dado do campo aqui
    # descreve o VALOR interno de cada item, não o campo em si — nunca tentar
    # formatar o dict/list inteiro como escalar (senão cai no repr Python cru).
    if isinstance(valor, list):
        return f"{len(valor)} item(ns) cadastrado(s)" if valor else "Nenhum item cadastrado"
    if isinstance(valor, dict):
        return f"{len(valor)} rubrica(s) cadastrada(s)" if valor else "Nenhuma rubrica cadastrada"
    if tipo_dado == "percentual":
        try:
            return f"{float(valor) * 100:.2f}%".replace(".", ",")
        except (TypeError, ValueError):
            return str(valor)
    if tipo_dado == "moeda":
        try:
            texto = f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"R$ {texto}"
        except (TypeError, ValueError):
            return str(valor)
    if tipo_dado == "booleano":
        return "Sim" if valor else "Não"
    if tipo_dado == "inteiro":
        try:
            return str(int(valor))
        except (TypeError, ValueError):
            return str(valor)
    return str(valor)


def _formatar_item_composto(campo: dict, item: dict) -> str:
    """Uma linha de um campo lista_estruturada/mapa_rubricas (uma rubrica,
    uma faixa, um split...) formatada para a tela de revisão — sempre nome
    e valor de cada sub-campo, na mesma ordem do item_schema, nunca o dict
    Python cru. Ignora o sub-campo gerado automaticamente (id técnico) —
    não é informação que a operadora precisa conferir."""
    partes = []
    for sub in campo.get("item_schema", []):
        if sub.get("gerado_automaticamente"):
            continue
        valor = item.get(sub["chave"]) if isinstance(item, dict) else None
        partes.append(f"{sub['label']}: {_formatar_valor(sub.get('tipo_dado', 'texto'), valor)}")
    return " · ".join(partes) if partes else "(sem sub-campos)"


def _renderizar_revisao_alteracoes(campos: list, valores_editados: dict) -> None:
    """Mostra exatamente o que `salvar_parametros` vai gravar — campo a
    campo, e para lista_estruturada/mapa_rubricas, item a item (nome e
    valor) — nunca um resumo tipo "3 item(ns) cadastrado(s)". Usada pelo
    fluxo de revisão em duas etapas (ver _aba_parametros) para os campos
    dinâmicos, e reaproveitável por qualquer outra tela que precise do
    mesmo tipo de conferência antes de salvar."""
    if not valores_editados:
        st.caption("Nenhuma alteração — os valores atuais serão apenas reafirmados.")
        return
    campos_por_chave = {c["chave"]: c for c in campos}
    for chave, valor in valores_editados.items():
        campo = campos_por_chave.get(chave)
        label = campo["label"] if campo else chave
        natureza = campo.get("natureza", "escalar") if campo else "escalar"
        st.markdown(f"**{label}**")
        if natureza in ("lista_estruturada", "mapa_rubricas"):
            if not valor:
                st.caption("Lista vazia.")
            else:
                for item in valor:
                    st.write(f"- {_formatar_item_composto(campo, item)}")
        else:
            st.write(_formatar_valor(campo.get("tipo_dado", "texto") if campo else "texto", valor))


def _editor_mapa_rubricas(uid, competencia_ref, campo, valor_atual, params_atuais, tipo_calculo):
    """Editor de um campo `mapa_rubricas` (custos_mensais/custos_variaveis,
    v1.2.0 — rubricas dinâmicas). Não é um editor novo: normaliza o valor
    atual (dict legado OU lista nova — ver app.rubricas.normalizar_rubricas)
    para a forma plana que `_editor_lista_estruturada` já sabe editar, e
    delega inteiramente para ela — mesma grade, mesmo id oculto gerado por
    slug, mesma unicidade, mesmo add/remove de linhas já usados por
    splits/repasses. `mapa_rubricas` só existe como conceito de schema
    (ver app.calculadora_schema); não existe caminho de UI próprio."""
    from app.rubricas import normalizar_rubricas, para_persistencia
    valor_normalizado = para_persistencia(normalizar_rubricas(valor_atual))
    return _editor_lista_estruturada(
        uid, competencia_ref, campo, valor_normalizado, params_atuais, tipo_calculo,
    )


# ─── editor genérico de listas estruturadas (faixas, splits, repasses) ───────
#
# Dirigido inteiramente por SCHEMAS_POR_TIPO/item_schema — nenhum "if
# tipo_calculo == ..." aqui. O que diferencia faixas de splits/repasses na
# tela é só o que o próprio schema declara: item_schema (colunas), minimo/
# maximo por sub-campo, estrutura_ordenada (faixas) e o sub-campo marcado
# gerado_automaticamente (id técnico de splits/repasses, nunca editável).

def _pct_para_ui_editor(valor):
    return None if valor is None else _pct_armazenado_para_ui(valor)


def _valor_para_armazenado_editor(sub: dict, valor):
    """Converte o valor de uma célula do st.data_editor de volta para a
    representação interna (percentual decimal, moeda float, texto stripado).
    NaN (célula em branco numa coluna numérica) vira None — é assim que o
    pandas representa "vazio" numa coluna float; None é o que o resto do
    sistema (e o "Sem limite" das faixas) espera."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    tipo_dado = sub.get("tipo_dado", "texto")
    if tipo_dado == "percentual":
        return _pct_ui_para_armazenado(valor)
    if tipo_dado == "moeda":
        return float(valor)
    if isinstance(valor, str):
        valor = valor.strip()
        return valor or None
    return valor


# Nota fixa de formato, anexada a TODO campo percentual da tela de
# Administração (escalar ou coluna de tabela) — ponto único de texto,
# nunca duplicado. Resolve a ambiguidade "digito 80 ou 0,80?" (homologação
# set/2026, EKOS): o valor é sempre armazenado internamente como fração
# decimal (0.80), mas a UI SEMPRE pede o número em pontos percentuais
# (80) — nunca a fração. Ver _pct_armazenado_para_ui/_pct_ui_para_armazenado,
# ponto único de conversão.
_AJUDA_FORMATO_PERCENTUAL = "Digite em pontos percentuais, de 0 a 100 — ex.: 80 para 80%. Não digite a fração (0,80)."


def _column_config_editor(sub: dict):
    tipo_dado = sub.get("tipo_dado", "texto")
    obrigatorio = bool(sub.get("obrigatorio"))
    escala = 100 if tipo_dado == "percentual" else 1
    kwargs = {}
    if sub.get("minimo") is not None:
        kwargs["min_value"] = sub["minimo"] * escala
    if sub.get("maximo") is not None:
        kwargs["max_value"] = sub["maximo"] * escala

    if tipo_dado == "percentual":
        return st.column_config.NumberColumn(
            sub["label"], format="%.2f%%", step=0.5, required=obrigatorio,
            help=_AJUDA_FORMATO_PERCENTUAL, **kwargs
        )
    if tipo_dado == "moeda":
        # step define a PRECISÃO de edição da célula no st.data_editor (não é
        # só o incremento das setinhas) — com um step inteiro (100.0, valor
        # anterior), o editor bloqueia a digitação do próprio separador
        # decimal, mesmo que a coluna seja float64 (confirmado ao vivo:
        # homologação set/2026, FIERGS — "Teste despesa A/B" sem casas
        # decimais digitáveis). 0.01 = a mesma precisão de "R$ %.2f".
        return st.column_config.NumberColumn(
            sub["label"], format="R$ %.2f", step=0.01, required=obrigatorio, **kwargs
        )
    return st.column_config.TextColumn(sub["label"], required=obrigatorio)


def _gerar_id_unico(nome, ids_usados: set) -> str:
    base = _gerar_id_sugerido(str(nome or "")) or "item"
    novo_id, sufixo = base, 2
    while novo_id in ids_usados:
        novo_id = f"{base}_{sufixo}"
        sufixo += 1
    ids_usados.add(novo_id)
    return novo_id


def _celula_vazia(valor) -> bool:
    return valor is None or valor == "" or (isinstance(valor, float) and pd.isna(valor))


def _fingerprint(valor) -> str:
    """Hash curto e determinístico do valor PERSISTIDO de um campo composto
    (lista_estruturada/mapa_rubricas) — usado para tornar a key dos widgets
    de edição (data_editor e companhia) sensível ao conteúdo, não só à
    identidade (unidade, competência, campo).

    IMPORTANTE (revisado na homologação set/2026, FIERGS — não trate isto
    como a correção das linhas que "desapareciam"): a causa raiz comprovada
    daquele bug é outra — uma célula do `st.data_editor` ainda em edição
    ativa (aberta, nunca confirmada com Enter/Tab/clique fora) só sincroniza
    seu valor para o Python num rerun POSTERIOR ao clique que o dispara,
    nunca no mesmo. Reproduzido ao vivo, com `st.data_editor` de verdade
    (não bypassado), inclusive DENTRO de `st.form` — `st.form` não resolve
    esse caso, porque o problema é a célula em si nunca ter sido
    "confirmada", não a falta de agrupamento de widgets. A correção real é
    o fluxo de revisão em duas etapas (ver `_aba_parametros`): "Revisar
    alterações" força o ciclo de rerun que consolida a edição pendente, e a
    revisão sempre mostra fielmente o que será gravado antes de confirmar.

    O que este fingerprint continua resolvendo, de verdade: sem ele, a key
    do widget era estática (só unidade+competência+campo) — depois de um
    save bem-sucedido that muda o valor persistido, reabrir a mesma tela
    reconstruía o data_editor com a MESMA key de antes, e o Streamlit podia
    reconciliar o `df` fresco do banco contra estado interno antigo do
    componente em vez de simplesmente adotá-lo. Incluir o fingerprint aqui
    garante que, sempre que o valor persistido mudar, o próximo render use
    uma key DIFERENTE — o widget nasce do zero com o dado fresco, sem
    nenhuma reconciliação implícita. Continua válido e não foi removido."""
    bruto = json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.md5(bruto.encode("utf-8")).hexdigest()[:10]


def _linhas_para_dataframe(itens: list, colunas: list, campo_id: str | None):
    """Monta o DataFrame de entrada do data_editor. Quando há campo_id, ele
    entra como uma coluna REAL do DataFrame (não um estado paralelo) — é
    ocultado da grade via column_config={campo_id: None}, mas o Streamlit
    devolve seu valor junto com cada linha em qualquer edição, exclusão ou
    inserção. É esse mecanismo nativo — não a posição da linha — que garante
    a identidade: confirmado empiricamente que excluir uma linha do meio
    NÃO desloca o id das linhas seguintes (ver retorno desta etapa)."""
    linhas = []
    for item in itens:
        linha = {
            sub["label"]: (
                _pct_para_ui_editor(item.get(sub["chave"]))
                if sub.get("tipo_dado") == "percentual" else item.get(sub["chave"])
            )
            for sub in colunas
        }
        if campo_id:
            linha[campo_id] = item.get(campo_id)
        linhas.append(linha)
    colunas_df = [s["label"] for s in colunas] + ([campo_id] if campo_id else [])
    df = pd.DataFrame(linhas, columns=colunas_df)
    for sub in colunas:
        if sub.get("tipo_dado") in ("percentual", "moeda"):
            # pd.to_numeric infere int64 sempre que TODOS os valores atuais
            # são inteiros (inclusive coluna vazia, sem nenhum item ainda) —
            # ex.: 100 e 200. Com a coluna int64, o st.data_editor aceita
            # digitar um valor decimal na célula (visualmente), mas TRUNCA
            # de volta para inteiro ao devolver o DataFrame editado
            # (confirmado ao vivo: 123.45 digitado -> 123 persistido).
            # .astype("float64") garante que um valor com centavos digitado
            # nunca seja truncado, mesmo quando os valores atuais são todos
            # "redondos" — sem isso, o fix de step (_column_config_editor)
            # sozinho não basta.
            df[sub["label"]] = pd.to_numeric(df[sub["label"]], errors="coerce").astype("float64")
    return df


def _dataframe_para_itens(df_editado, colunas: list, campo_id: str | None) -> list:
    """Reconstrói os itens internos a partir do DataFrame editado. Uma linha
    sem id (célula da coluna técnica vazia/NaN — sempre o caso de uma linha
    recém-adicionada, já que o operador nunca a edita) ganha um id novo,
    gerado do "nome" uma única vez; uma linha com id já presente preserva
    exatamente esse valor, não importa em qual posição ela caiu depois de
    edições/exclusões/inclusões de outras linhas."""
    ids_usados = set()
    if campo_id and campo_id in df_editado.columns:
        ids_usados = {v for v in df_editado[campo_id].tolist() if not _celula_vazia(v)}

    itens = []
    for _, row in df_editado.iterrows():
        item = {sub["chave"]: _valor_para_armazenado_editor(sub, row[sub["label"]]) for sub in colunas}
        if campo_id:
            id_atual = row.get(campo_id)
            if _celula_vazia(id_atual):
                item[campo_id] = _gerar_id_unico(item.get("nome"), ids_usados)
            else:
                item[campo_id] = id_atual
            item = {campo_id: item.pop(campo_id), **item}
        itens.append(item)
    return itens


def _editor_tabela_simples(uid: str, competencia_ref: str, campo: dict, valor_atual: list, colunas: list, campo_id: str | None):
    """Editor padrão (splits, repasses): uma linha por item, todas as
    colunas do item_schema editáveis, id técnico presente no DataFrame mas
    oculto da grade."""
    df = _linhas_para_dataframe(valor_atual, colunas, campo_id)
    column_config = {sub["label"]: _column_config_editor(sub) for sub in colunas}
    if campo_id:
        column_config[campo_id] = None  # coluna técnica: presente nos dados, nunca exibida

    st.caption(
        "Clique na última linha (em branco) para adicionar. Selecione uma linha pelo "
        "checkbox à esquerda e pressione Delete para remover."
    )
    # A key inclui um fingerprint do valor vigente — ver _fingerprint: sem
    # isso, salvar e recarregar (mesma competência) reabre o data_editor com
    # a MESMA key de antes, e o Streamlit reconcilia o df novo (já persistido)
    # contra o estado interno ainda pendente da rodada anterior, em vez de
    # simplesmente adotar o valor fresco do banco.
    editor_key = f"param_editor_{uid}_{competencia_ref}_{campo['chave']}_{_fingerprint(valor_atual)}"
    df_editado = st.data_editor(
        df, num_rows="dynamic", key=editor_key, use_container_width=True,
        hide_index=True, column_config=column_config,
    )
    return _dataframe_para_itens(df_editado, colunas, campo_id)


def _editor_faixas_com_limite(uid: str, competencia_ref: str, campo: dict, valor_atual: list, colunas: list, estrutura: dict):
    """Editor de listas com `estrutura_ordenada` (faixas, faixas_aluguel) —
    dirigido por esse metadado do schema, não por tipo_calculo ou nome do
    campo: qualquer lista_estruturada futura marcada da mesma forma ganha
    automaticamente esta UI. "Sem limite" é tratado como o que é — uma
    decisão de negócio (existe ou não uma faixa final aberta) — em vez de
    uma célula numérica vazia: o data_editor cobre só as faixas COM limite;
    a faixa final, se existir, é um checkbox + um campo de percentual à
    parte. Assume (como hoje em todo o schema) que uma lista com
    estrutura_ordenada tem exatamente 2 sub-campos: o limite e um outro
    (percentual) — se um dia houver um terceiro sub-campo aqui, este editor
    precisa ser revisto."""
    campo_limite = estrutura["campo_limite"]
    sub_limite = next(s for s in colunas if s["chave"] == campo_limite)
    outras = [s for s in colunas if s["chave"] != campo_limite]
    sub_percentual = outras[0]

    tem_sem_limite = bool(valor_atual) and valor_atual[-1].get(campo_limite) is None
    linhas_limitadas = valor_atual[:-1] if tem_sem_limite else list(valor_atual)
    item_sem_limite = valor_atual[-1] if tem_sem_limite else None

    df = _linhas_para_dataframe(linhas_limitadas, colunas, campo_id=None)
    column_config = {sub["label"]: _column_config_editor(sub) for sub in colunas}
    # Aqui "Até" é sempre exigido: a faixa sem limite é tratada à parte pelo
    # checkbox abaixo, então toda linha desta grade precisa de um limite real.
    # step=0.01 (não 100.0) pela mesma razão de _column_config_editor: um
    # step inteiro bloqueia a digitação do separador decimal na célula.
    column_config[sub_limite["label"]] = st.column_config.NumberColumn(
        sub_limite["label"], format="R$ %.2f", step=0.01, required=True, min_value=0.01,
    )

    st.caption(
        "Cadastre aqui as faixas COM limite superior, da menor para a maior. "
        "Clique na última linha (em branco) para adicionar. Selecione uma linha pelo "
        "checkbox à esquerda e pressione Delete para remover."
    )
    # Fingerprint do valor vigente na key — mesma razão de _editor_tabela_simples.
    editor_key = f"param_editor_{uid}_{competencia_ref}_{campo['chave']}_{_fingerprint(valor_atual)}"
    df_editado = st.data_editor(
        df, num_rows="dynamic", key=editor_key, use_container_width=True,
        hide_index=True, column_config=column_config,
    )
    itens = _dataframe_para_itens(df_editado, colunas, campo_id=None)

    _fp_sem_limite = _fingerprint([tem_sem_limite, item_sem_limite])
    toggle_key = f"param_semlimite_{uid}_{competencia_ref}_{campo['chave']}_{_fp_sem_limite}"
    tem_sem_limite_novo = st.checkbox(
        "Faixa final sem limite (vale para tudo que passar da última faixa acima)",
        value=tem_sem_limite, key=toggle_key,
    )
    if tem_sem_limite_novo:
        pct_key = f"param_semlimite_pct_{uid}_{competencia_ref}_{campo['chave']}_{_fp_sem_limite}"
        pct_default = _pct_armazenado_para_ui(item_sem_limite[sub_percentual["chave"]]) if item_sem_limite else 0.0
        pct_ui = st.number_input(
            f"{sub_percentual['label']} da faixa sem limite (%)", value=pct_default,
            step=0.5, format="%.2f", key=pct_key, help=_AJUDA_FORMATO_PERCENTUAL,
        )
        itens.append({campo_limite: None, sub_percentual["chave"]: _pct_ui_para_armazenado(pct_ui)})

    return itens


def _editor_lista_estruturada(
    uid: str, competencia_ref: str, campo: dict, valor_atual: list,
    params_atuais: dict, tipo_calculo: str,
):
    """Renderiza o editor de uma lista_estruturada e devolve (itens_editados,
    valido). Delega para `_editor_faixas_com_limite` quando o schema declara
    `estrutura_ordenada`, ou `_editor_tabela_simples` caso contrário — a
    escolha é sobre uma CAPACIDADE que o próprio campo declara, não sobre
    tipo_calculo ou nome do campo."""
    item_schema = campo.get("item_schema", [])
    campo_id = next((s["chave"] for s in item_schema if s.get("gerado_automaticamente")), None)
    colunas = [s for s in item_schema if s["chave"] != campo_id]
    valor_atual = valor_atual or []
    estrutura = campo.get("estrutura_ordenada")

    if estrutura:
        itens_editados = _editor_faixas_com_limite(uid, competencia_ref, campo, valor_atual, colunas, estrutura)
    else:
        itens_editados = _editor_tabela_simples(uid, competencia_ref, campo, valor_atual, colunas, campo_id)

    erros = list(validar_estrutura_lista(campo, itens_editados))
    if campo_obrigatorio_efetivo(campo, params_atuais) and not itens_editados:
        erros.append(f'Cadastre pelo menos uma linha em "{campo["label"]}".')

    if not erros:
        params_candidatos = dict(params_atuais)
        params_candidatos[campo["chave"]] = itens_editados
        for regra in validacoes_do_tipo(tipo_calculo):
            campos_regra = regra.get("campos") or [regra.get("campo")]
            if campo["chave"] in campos_regra:
                erros.extend(validar_regra_cruzada(regra, params_candidatos))

    for e in erros:
        st.error(e)

    return itens_editados, (len(erros) == 0)


def _aba_parametros(uid: str, u: dict):
    tipo_calculo = u["tipo_calculo"]
    campos = campos_do_tipo(tipo_calculo)

    if not campos:
        st.info(
            "Este modelo de cálculo ainda não tem parâmetros mapeados nesta tela "
            "(ex.: Operação de Pátio, com estrutura própria)."
        )
        return

    st.markdown("**Competência de referência**")
    st.caption("Define qual configuração vigente é exibida e validada abaixo.")
    competencia_ref = _competencia_picker(
        "Mês", f"param_ref_{uid}",
        st.session_state.get(f"param_ref_valor_{uid}", _competencia_avaliacao_padrao(u)),
    )
    st.session_state[f"param_ref_valor_{uid}"] = competencia_ref

    # Semeia o baseline do YAML no banco (idempotente — só preenche o que
    # ainda não existe, nunca sobrescreve vigência já salva) para que esta
    # tela reflita exatamente o mesmo estado que app.engine.get_unit_com_params
    # já usa no cálculo real — evita campo aparentando "vazio" numa unidade
    # legada cujo valor real ainda só existe no YAML.
    seed_parametros_from_yaml(uid, load_units().get(uid, {}))
    params_atuais = get_parametros_vigentes(uid, competencia_ref)

    inicio_mes = (u.get("inicio") or "")[:7]
    if inicio_mes and competencia_ref < inicio_mes:
        # Seletor não é bloqueado (o operador pode navegar livremente para
        # conferir/editar um mês anterior se quiser) — só a lista de
        # pendências não faz sentido para um mês em que a unidade sequer
        # existia. Rodada de correção Nilo Square.
        st.info(f"Unidade ainda não estava em operação nesta competência. Início: {_fmt_competencia(inicio_mes)}.")
    else:
        erros = validar_configuracao_unidade(uid, competencia_ref)
        if erros:
            st.error(f"⚠ Configuração incompleta em {_fmt_competencia(competencia_ref)}")
            for e in erros:
                st.markdown(f"- {e}")
        else:
            st.success(f"✓ Configuração completa em {_fmt_competencia(competencia_ref)}")
            if not u["ativo"]:
                st.caption(
                    'Esta unidade pode estar pronta para ativação — veja o botão "Ativar unidade" '
                    "na aba **Dados da Unidade** (a ativação também confere o início estrutural)."
                )

    # Percentual de Aluguel × Faixas de Aluguel são alternativas (COM_ALIQUOTA_CUMUL
    # — ver calculadora_schema.py) e o calculator sempre prioriza faixas_aluguel
    # quando ambos estão configurados (app.calculators.cumulativo). Isso nunca
    # foi validado como erro (algum_de só exige "pelo menos um") e não vamos
    # bloquear agora — só tornar visível o que já acontece hoje. Nenhum dos
    # dois parâmetros é alterado ou apagado por este aviso.
    if resolver_valor(params_atuais, "percentual_aluguel") and resolver_valor(params_atuais, "faixas_aluguel"):
        st.warning(
            "Faixas de Aluguel está configurado e tem prioridade. O Percentual de "
            "Aluguel não será utilizado no cálculo enquanto houver faixas configuradas."
        )

    st.divider()

    st.markdown("**Parâmetros do modelo**")
    valores_editados = {}
    compostos_invalidos = False
    # Snapshot CORRENTE: params_atuais (persistido) sobreposto pelo que já
    # foi digitado nesta mesma renderização, campo a campo, à medida que o
    # loop avança. Homologação set/2026 (Nilo Square) — a validação cruzada
    # "algum_de" (percentual_aluguel/faixas_aluguel) lia só params_atuais
    # (o banco, ANTES desta edição): digitar percentual_aluguel=70% pela
    # primeira vez e deixar faixas_aluguel vazia disparava "Informe o
    # percentual ou cadastre as faixas" mesmo com o percentual já digitado,
    # porque esse valor só existia em valores_editados, nunca em
    # params_atuais, no momento em que faixas_aluguel era validada. Como
    # percentual_aluguel vem antes de faixas_aluguel no schema (COM_
    # ALIQUOTA_CUMUL e COM_ALIQUOTA_CUMUL_DU), passar este snapshot
    # corrente — não params_atuais cru — resolve genericamente, sem tocar
    # schema nem regra de negócio.
    params_correntes = dict(params_atuais)
    for campo in campos:
        chave = campo["chave"]
        natureza = campo.get("natureza", "escalar")
        valor_atual = resolver_valor(params_atuais, chave)
        widget_key = f"param_{uid}_{competencia_ref}_{chave}"

        if natureza in ("lista_estruturada", "mapa_rubricas"):
            obrig = campo_obrigatorio_efetivo(campo, params_atuais)
            st.markdown(f"**{campo['label']}**" + (" *" if obrig else ""))
            if campo.get("descricao"):
                st.caption(campo["descricao"])
            if natureza == "mapa_rubricas":
                itens_editados, valido = _editor_mapa_rubricas(
                    uid, competencia_ref, campo, valor_atual, params_correntes, tipo_calculo,
                )
                from app.rubricas import normalizar_rubricas, para_persistencia
                valor_comparacao = para_persistencia(normalizar_rubricas(valor_atual))
            else:
                itens_editados, valido = _editor_lista_estruturada(
                    uid, competencia_ref, campo, valor_atual, params_correntes, tipo_calculo,
                )
                valor_comparacao = valor_atual or []
            params_correntes[chave] = itens_editados
            if not valido:
                compostos_invalidos = True
            elif itens_editados != valor_comparacao:
                valores_editados[chave] = itens_editados
            st.write("")
            continue

        obrig = campo_obrigatorio_efetivo(campo, params_atuais)
        tipo_dado = campo.get("tipo_dado", "texto")
        label = campo["label"] + (" *" if obrig else "")

        if tipo_dado == "booleano":
            novo_valor = st.toggle(
                label, value=bool(valor_atual), key=widget_key, help=campo.get("descricao"),
            )
        elif tipo_dado == "percentual":
            valor_ui = _pct_armazenado_para_ui(valor_atual)
            ajuda = campo.get("descricao")
            ajuda = f"{ajuda} {_AJUDA_FORMATO_PERCENTUAL}" if ajuda else _AJUDA_FORMATO_PERCENTUAL
            novo_valor_ui = st.number_input(
                f"{label} (%)", value=valor_ui, step=0.5, format="%.2f",
                key=widget_key, help=ajuda,
            )
            novo_valor = _pct_ui_para_armazenado(novo_valor_ui)
        elif tipo_dado == "moeda":
            novo_valor = st.number_input(
                f"{label} (R$)", value=float(valor_atual or 0.0), step=100.0, format="%.2f",
                min_value=0.0, key=widget_key, help=campo.get("descricao"),
            )
        elif tipo_dado == "inteiro":
            novo_valor = st.number_input(
                label, value=int(valor_atual or 0), step=1, format="%d",
                key=widget_key, help=campo.get("descricao"),
            )
        else:
            novo_valor = st.text_input(
                label, value=str(valor_atual) if valor_atual is not None else "",
                key=widget_key, help=campo.get("descricao"),
            )

        if campo.get("descricao"):
            st.caption(campo["descricao"])
        if campo.get("condicao"):
            # Metadado já existia no schema (ex.: taxa_cobranca só é
            # relevante quando "Tem Taxa de Cobrança" está ligado) mas nunca
            # tinha sido renderizado — o campo aparecia sem nenhuma indicação
            # de que dependia de outro toggle (homologação set/2026, EKOS).
            st.caption(f"ℹ️ {campo['condicao']}")
        valores_editados[chave] = novo_valor
        params_correntes[chave] = novo_valor

    st.divider()

    st.markdown("**Salvar alteração**")
    vigente_a_partir = _competencia_picker(
        "Vigente a partir de", f"param_vigencia_{uid}",
        st.session_state.get(f"param_vigencia_valor_{uid}", competencia_ref),
    )
    st.session_state[f"param_vigencia_valor_{uid}"] = vigente_a_partir
    st.info(f"As alterações passarão a valer a partir de **{_fmt_competencia(vigente_a_partir)}**.")

    # Competência de referência (o que está sendo visualizado/editado) e
    # "Vigente a partir de" (onde a nova vigência abre) são pickers
    # independentes de propósito — divergirem pode ser intencional (ex.:
    # revisar um mês antigo mas só querer aplicar a mudança adiante). Mas
    # salvar sem que o operador tenha percebido essa divergência salvaria os
    # valores da competência ERRADA como nova vigência. A chave do checkbox
    # inclui as duas competências: trocar qualquer uma das duas troca a
    # chave, o que faz o Streamlit recriar o widget e a confirmação volta a
    # ser "não marcada" — reset automático, sem estado manual para gerenciar.
    pode_salvar = True
    if competencia_ref != vigente_a_partir:
        st.warning(
            f"Você está visualizando os parâmetros de {_fmt_competencia(competencia_ref)}, "
            f"mas esta alteração passará a valer a partir de {_fmt_competencia(vigente_a_partir)}. "
            "Os valores exibidos serão usados para criar a nova vigência."
        )
        pode_salvar = st.checkbox(
            f"Confirmo que quero usar estes valores a partir de {_fmt_competencia(vigente_a_partir)}.",
            key=f"param_confirma_{uid}_{competencia_ref}_{vigente_a_partir}",
        )

    if compostos_invalidos:
        st.error(
            "Corrija os erros indicados acima nas listas (faixas/splits/repasses) "
            "antes de salvar."
        )
        pode_salvar = False

    # Fluxo em duas etapas (Revisar -> Confirmar) só para tipos de cálculo
    # que têm pelo menos um campo dinâmico (lista_estruturada/mapa_rubricas)
    # — homologação set/2026, FIERGS: uma célula do `st.data_editor` ainda
    # em edição ativa (aberta, nunca confirmada com Enter/Tab/clique fora)
    # só sincroniza seu valor para o Python num rerun POSTERIOR ao clique
    # que o dispara — nunca no mesmo. "Salvar parâmetros" direto podia
    # persistir uma grade sem a última linha/edição digitada, silenciosamente
    # (comprovado com uma reprodução mínima, dentro e fora de st.form — a
    # causa não é ausência de st.form). "Revisar alterações" primeiro força
    # exatamente o ciclo de rerun que consolida esse estado, e a revisão
    # sempre mostra fielmente o que será gravado — nunca relê os widgets no
    # momento de confirmar. Tipos sem nenhum campo dinâmico (PERCENTUAL_
    # SIMPLES, COM_ALIQUOTA) mantêm o salvamento direto — não têm esse risco.
    tem_campo_dinamico = any(
        c.get("natureza") in ("lista_estruturada", "mapa_rubricas") for c in campos
    )

    if not tem_campo_dinamico:
        if st.button("Salvar parâmetros", type="primary", key=f"param_salvar_{uid}", disabled=not pode_salvar):
            usuario = st.session_state.get("username") or "administracao"
            salvar_parametros(uid, vigente_a_partir, valores_editados, alterado_por=usuario)
            load_units(force=True)
            st.session_state.admin_msg = (
                f"Parâmetros salvos — vigentes a partir de {_fmt_competencia(vigente_a_partir)}."
            )
            st.rerun()
    else:
        st.caption(
            "Antes de revisar: finalize a edição da última célula das tabelas acima "
            "(pressione Enter ou Tab, ou clique fora da célula) — a revisão só "
            "reflete o que já foi confirmado na grade."
        )
        # Chave inclui as duas competências, mesmo padrão do checkbox de
        # confirmação acima — trocar qualquer uma delas descarta a revisão
        # pendente automaticamente (session_state[chave_nova] não existe).
        revisao_key = f"admin_revisao_{uid}_{competencia_ref}_{vigente_a_partir}"

        if st.button("Revisar alterações", type="primary", key=f"param_revisar_{uid}", disabled=not pode_salvar):
            st.session_state[revisao_key] = {
                "valores_editados": dict(valores_editados),
                "vigente_a_partir": vigente_a_partir,
            }
            st.rerun()

        snapshot = st.session_state.get(revisao_key)
        if snapshot is not None:
            with st.container(border=True):
                st.markdown(
                    f"**Revisão — será salvo, vigente a partir de "
                    f"{_fmt_competencia(snapshot['vigente_a_partir'])}:**"
                )
                _renderizar_revisao_alteracoes(campos, snapshot["valores_editados"])
                rc1, rc2 = st.columns(2)
                with rc1:
                    if st.button("Descartar revisão", key=f"param_revisao_cancelar_{uid}",
                                 use_container_width=True):
                        st.session_state.pop(revisao_key, None)
                        st.rerun()
                with rc2:
                    if st.button("Confirmar e salvar", type="primary",
                                 key=f"param_revisao_confirmar_{uid}", use_container_width=True):
                        usuario = st.session_state.get("username") or "administracao"
                        # Persiste exatamente o conteúdo apresentado na revisão —
                        # nunca relê os widgets/editores neste passo.
                        salvar_parametros(
                            uid, snapshot["vigente_a_partir"], snapshot["valores_editados"],
                            alterado_por=usuario,
                        )
                        load_units(force=True)
                        st.session_state.pop(revisao_key, None)
                        st.session_state.admin_msg = (
                            f"Parâmetros salvos — vigentes a partir de "
                            f"{_fmt_competencia(snapshot['vigente_a_partir'])}."
                        )
                        st.rerun()

    st.divider()
    _secao_historico(uid, tipo_calculo)


def _secao_historico(uid: str, tipo_calculo: str):
    with st.expander("Histórico de alterações"):
        historico = get_historico_parametros(uid)
        if not historico:
            st.caption("Nenhum parâmetro registrado ainda.")
            return

        linhas = []
        for h in historico:
            chave = h["parametro"]
            campo_schema = campo_por_chave(tipo_calculo, chave)
            tipo_dado = campo_schema["tipo_dado"] if campo_schema else (h.get("tipo_dado") or "texto")
            if campo_schema:
                label = campo_schema["label"]
                # Sub-chave dot-notation legada de mapa_rubricas (ex.
                # "custos_variaveis.sistema_perto"): só existe para unidades
                # nunca tocadas pelo editor novo (que grava um único
                # parâmetro "custos_variaveis" sem ponto) — sem isso, o
                # campo do schema é o mapa inteiro ("Custos Variáveis"), e
                # entradas de rubricas diferentes ficariam com o mesmo
                # rótulo no histórico.
                if campo_schema.get("natureza") == "mapa_rubricas" and "." in chave:
                    from app.rubricas import rotulo_exibicao
                    rubrica = rotulo_exibicao(chave.split(".", 1)[1])
                    label = f"{label} — {rubrica}"
                    tipo_dado = campo_schema.get("tipo_valor_item", tipo_dado)
            else:
                label = chave
            fim = h["competencia_fim"]
            linhas.append({
                "Parâmetro": label,
                "Valor": _formatar_valor(tipo_dado, h["valor"]),
                "Vigente desde": _fmt_competencia(h["competencia_inicio"]),
                "Vigente até": fim if fim == "Em aberto" else _fmt_competencia(fim),
                "Alterado em": h["alterado_em"],
                "Responsável": h["alterado_por"],
            })
        st.dataframe(linhas, use_container_width=True, hide_index=True)
