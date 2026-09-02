"""
Administração > Unidades — cadastro e edição dos dados ESTRUTURAIS das
unidades (nome, contratante, início, modelo de cálculo, tipo de relatório,
status) e, na aba Parâmetros, dos parâmetros ESCALARES e BOOLEANOS
vigência-tracked de cada modelo. Deliberadamente separada do fluxo
operacional de fechamento (app.ui.fechamento) — reaproveita a mesma
linguagem visual (_CSS, marca Valandro) sem redesenhar nada.

Ainda NÃO cobre (próxima subetapa): editor de campos compostos (`faixas`,
`faixas_aluguel`, `splits`, `repasses`, mapas dinâmicos de custos) — esses
aparecem na aba Parâmetros em modo leitura, com indicação explícita de que
a edição vem na etapa seguinte. Uma unidade criada aqui nasce
"Em configuração" (ativo=0, sem nenhuma linha em parametros_vigentes) e só
pode ser ativada manualmente (na aba Dados da Unidade) depois de ter algum
parâmetro definido.

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
import re
import unicodedata
from datetime import date

import streamlit as st

from app.ui.fechamento import _CSS, _VALANDRO_LOGO_URI
from app.calculadora_labels import (
    TIPO_CALCULO_LABELS, TIPO_CALCULO_DESCRICOES, TIPO_RELATORIO_LABELS,
    TIPOS_CALCULO_PARA_CADASTRO, TIPOS_RELATORIO_PARA_CADASTRO,
)
from app.calculadora_schema import campos_do_tipo, campo_por_chave
from app.models import (
    listar_unidades_admin, get_unidade, criar_unidade, atualizar_unidade,
    unidade_id_existe, unidade_possui_lancamentos, status_unidade,
    unidades_exemplo_por_tipo, get_parametros_vigentes, salvar_parametros,
    get_historico_parametros, validar_configuracao_unidade,
    seed_parametros_from_yaml, _resolver_valor_schema, _campo_obrigatorio_efetivo,
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
    # Contêiner (lista_estruturada/mapa_dinamico): o tipo_dado do campo aqui
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


def _detalhar_composto(campo: dict, valor_atual):
    """Renderiza em modo leitura (nunca JSON cru) o valor vigente de um campo
    `lista_estruturada` ou `mapa_dinamico` — as próprias faixas/splits/repasses/
    rubricas de custo, cuja edição fica para a próxima subetapa."""
    natureza = campo.get("natureza")
    if natureza == "lista_estruturada":
        if not valor_atual:
            st.caption("Nenhum item cadastrado.")
            return
        item_schema = campo.get("item_schema", [])
        linhas = []
        for item in valor_atual:
            if not item_schema:
                linhas.append({"Item": _formatar_valor("texto", item)})
                continue
            linha = {}
            for sub in item_schema:
                v = item.get(sub["chave"]) if isinstance(item, dict) else None
                linha[sub["label"]] = _formatar_valor(sub.get("tipo_dado", "texto"), v)
            linhas.append(linha)
        st.table(linhas)
    elif natureza == "mapa_dinamico":
        if not valor_atual:
            st.caption("Nenhuma rubrica cadastrada.")
            return
        tipo_valor = campo.get("tipo_valor_item", "moeda")
        linhas = [
            {"Rubrica": str(k).replace("_", " ").title(), "Valor": _formatar_valor(tipo_valor, v)}
            for k, v in valor_atual.items()
        ]
        st.table(linhas)


def _aba_parametros(uid: str, u: dict):
    tipo_calculo = u["tipo_calculo"]
    campos = campos_do_tipo(tipo_calculo)

    if not campos:
        st.info(
            "Este modelo de cálculo ainda não tem parâmetros mapeados nesta tela "
            "(ex.: Operação de Pátio, com estrutura própria)."
        )
        return

    hoje_aaaa_mm = date.today().strftime("%Y-%m")

    st.markdown("**Competência de referência**")
    st.caption("Define qual configuração vigente é exibida e validada abaixo.")
    competencia_ref = _competencia_picker(
        "Mês", f"param_ref_{uid}",
        st.session_state.get(f"param_ref_valor_{uid}", hoje_aaaa_mm),
    )
    st.session_state[f"param_ref_valor_{uid}"] = competencia_ref

    # Semeia o baseline do YAML no banco (idempotente — só preenche o que
    # ainda não existe, nunca sobrescreve vigência já salva) para que esta
    # tela reflita exatamente o mesmo estado que app.engine.get_unit_com_params
    # já usa no cálculo real — evita campo aparentando "vazio" numa unidade
    # legada cujo valor real ainda só existe no YAML.
    seed_parametros_from_yaml(uid, load_units().get(uid, {}))
    params_atuais = get_parametros_vigentes(uid, competencia_ref)

    erros = validar_configuracao_unidade(uid, competencia_ref)
    if erros:
        st.error(f"⚠ Configuração incompleta em {_fmt_competencia(competencia_ref)}")
        for e in erros:
            st.markdown(f"- {e}")
    else:
        st.success(f"✓ Configuração completa em {_fmt_competencia(competencia_ref)}")
        if not u["ativo"]:
            st.caption(
                'Esta unidade está pronta para ser ativada — use o campo "Unidade ativa" '
                "na aba **Dados da Unidade**."
            )

    st.divider()

    st.markdown("**Parâmetros do modelo**")
    valores_editados = {}
    for campo in campos:
        chave = campo["chave"]
        natureza = campo.get("natureza", "escalar")
        valor_atual = _resolver_valor_schema(params_atuais, chave)
        widget_key = f"param_{uid}_{competencia_ref}_{chave}"

        if natureza in ("lista_estruturada", "mapa_dinamico"):
            st.markdown(f"**{campo['label']}**")
            if campo.get("descricao"):
                st.caption(campo["descricao"])
            st.write(_formatar_valor(campo.get("tipo_dado", "json"), valor_atual))
            _detalhar_composto(campo, valor_atual)
            st.caption("🔒 Edição disponível na próxima etapa.")
            st.write("")
            continue

        obrig = _campo_obrigatorio_efetivo(campo, params_atuais)
        tipo_dado = campo.get("tipo_dado", "texto")
        label = campo["label"] + (" *" if obrig else "")

        if tipo_dado == "booleano":
            novo_valor = st.toggle(
                label, value=bool(valor_atual), key=widget_key, help=campo.get("descricao"),
            )
        elif tipo_dado == "percentual":
            valor_ui = _pct_armazenado_para_ui(valor_atual)
            novo_valor_ui = st.number_input(
                f"{label} (%)", value=valor_ui, step=0.5, format="%.2f",
                key=widget_key, help=campo.get("descricao"),
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
        valores_editados[chave] = novo_valor

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

    if st.button("Salvar parâmetros", type="primary", key=f"param_salvar_{uid}", disabled=not pode_salvar):
        usuario = st.session_state.get("username") or "administracao"
        salvar_parametros(uid, vigente_a_partir, valores_editados, alterado_por=usuario)
        load_units(force=True)
        st.session_state.admin_msg = (
            f"Parâmetros salvos — vigentes a partir de {_fmt_competencia(vigente_a_partir)}."
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
                # Sub-chave de mapa_dinamico (ex. "custos_variaveis.sistema_perto"):
                # o campo do schema é o mapa inteiro ("Custos Variáveis") — sem a
                # rubrica específica, entradas de rubricas diferentes ficariam com
                # o mesmo rótulo no histórico.
                if campo_schema.get("natureza") == "mapa_dinamico" and "." in chave:
                    rubrica = chave.split(".", 1)[1].replace("_", " ").title()
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
