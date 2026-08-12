"""Lyon Park — Fechamento Mensal"""
import os
import re
import yaml
import streamlit as st
import streamlit_authenticator as stauth
from datetime import date
from dotenv import load_dotenv

# Carrega .env se existir (desenvolvimento local).
# Em produção (Render), as variáveis já estão no processo — load_dotenv não sobrescreve.
load_dotenv(override=False)

st.set_page_config(
    page_title="Lyon Park — Fechamento",
    page_icon="🅿️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Remove sidebar completamente via CSS
st.markdown("""
<style>
[data-testid="stSidebar"]        { display: none !important; }
[data-testid="collapsedControl"] { display: none !important; }
section[data-testid="stSidebarContent"] { display: none !important; }
</style>
""", unsafe_allow_html=True)


# ── Autenticação ──────────────────────────────────────────────────────────────
# Configuração carregada exclusivamente via variável de ambiente.
# Nenhuma credencial é hardcoded ou impressa em log.

_auth_yaml = os.environ.get("AUTH_USERS_YAML", "").strip()

if not _auth_yaml:
    st.error(
        "⚠️ Configuração de autenticação ausente.  \n"
        "Defina a variável de ambiente **AUTH_USERS_YAML** antes de iniciar a aplicação.  \n"
        "Consulte o arquivo `.env.example` para o formato esperado."
    )
    st.stop()

try:
    _auth_config = yaml.safe_load(_auth_yaml)
except Exception as _exc:
    st.error(f"⚠️ Erro ao carregar configuração de autenticação: {_exc}")
    st.stop()

# ── Diagnóstico temporário (remover após validar login) ───────────────────────
_DEBUG_AUTH = os.environ.get("DEBUG_AUTH", "").lower() in ("1", "true", "yes")
if _DEBUG_AUTH:
    _usernames = list((_auth_config.get("credentials") or {}).get("usernames", {}).keys())
    st.info(f"[DEBUG] Usuários carregados: {_usernames}")
    for _u in _usernames:
        _pwd = (_auth_config["credentials"]["usernames"][_u].get("password") or "")
        _is_hash = bool(re.match(r'^\$2[aby]\$\d+\$.{53}$', _pwd))
        st.info(
            f"[DEBUG] '{_u}': len_password={len(_pwd)}, "
            f"é_hash_bcrypt={_is_hash}"
        )
    _cookie = _auth_config.get("cookie", {})
    st.info(
        f"[DEBUG] Cookie: name={_cookie.get('name')!r}, "
        f"key_len={len(_cookie.get('key', ''))}, "
        f"expiry_days={_cookie.get('expiry_days')}"
    )
# ─────────────────────────────────────────────────────────────────────────────

_authenticator = stauth.Authenticate(
    credentials=_auth_config["credentials"],
    cookie_name=_auth_config["cookie"]["name"],
    cookie_key=_auth_config["cookie"]["key"],
    cookie_expiry_days=int(_auth_config["cookie"]["expiry_days"]),
    auto_hash=False,  # senhas já chegam pré-hasheadas com bcrypt
)

_authenticator.login(location="main")


# ── Roteamento por status de autenticação ─────────────────────────────────────

if st.session_state.get("authentication_status") is True:
    # st.session_state["username"] → identificador do login (uso futuro: alterado_por, auditoria)
    # st.session_state["name"]     → nome amigável do usuário autenticado

    # Botão de logout: posicionado no canto direito, fora do fluxo da aplicação
    _col_app, _col_logout = st.columns([11, 1])
    with _col_logout:
        _authenticator.logout("Sair", location="main", key="btn_logout")

    # ── Inicialização do banco e aplicação principal ───────────────────────────
    # Importações dentro do bloco autenticado: nenhum dado é carregado antes do login
    from app.models import init_db
    init_db()
    from app.ui.fechamento import tela_fechamento

    hoje = date.today()
    if "sel_ano" not in st.session_state:
        st.session_state.sel_ano = hoje.year
    if "sel_mes" not in st.session_state:
        st.session_state.sel_mes = hoje.month - 1 if hoje.month > 1 else 12

    mes_ref = f"{st.session_state.sel_ano}-{st.session_state.sel_mes:02d}"
    tela_fechamento(mes_ref)

elif st.session_state.get("authentication_status") is False:
    st.error("Usuário ou senha incorretos.")

# status None → apenas o formulário de login está visível (renderizado por _authenticator.login)
