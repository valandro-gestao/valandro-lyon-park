"""Lyon Park — Fechamento Mensal"""
import base64
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


def _asset_data_uri(filename: str) -> str:
    """Lê um arquivo de assets/ e retorna como data URI base64 (sem chamada de rede)."""
    _path = os.path.join(os.path.dirname(__file__), "assets", filename)
    with open(_path, "rb") as _f:
        _b64 = base64.b64encode(_f.read()).decode()
    return f"data:image/png;base64,{_b64}"


# CSS exclusivo da tela de login. Só é injetado quando o usuário não está
# autenticado (ver bloco de roteamento abaixo) — não afeta nenhuma outra tela.
# Tokens e pilha tipográfica seguem docs/DESIGN_LANGUAGE.md (seção 4). Nenhuma
# fonte é carregada por CDN: usa-se stack de sistema como fallback até a
# estratégia de auto-hospedagem de fontes ser definida para o portfólio Valandro.
_LOGIN_CSS = """
<style>
:root {
  --vd-navy:      #1B3A6B;
  --vd-navy-mid:  #2E6DA4;
  --vd-ink:       #1F2937;
  --vd-muted:     #6B7280;
  --vd-faint:     #9CA3AF;
  --vd-border:    #E2E5EA;
  --vd-red:       #DC2626;
  --vd-red-bg:    #FDECEA;
  --vd-font-display: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --vd-font-body:    -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

.vd-brand {
  max-width: 380px;
  margin: 0 auto;
  padding-top: clamp(56px, 14vh, 140px);
}
.vd-brand img { height: 42px; display: block; margin-bottom: 16px; }
.vd-brand .vd-rule { height: 1px; background: var(--vd-border); width: 100%; }
.vd-brand .vd-context {
  margin-top: 10px;
  font-family: var(--vd-font-body);
  font-size: 0.72rem;
  color: var(--vd-faint);
  letter-spacing: .15px;
}
.vd-brand .vd-context .vd-dot { color: var(--vd-faint); margin: 0 6px; }

div[data-testid="stForm"] {
  max-width: 380px;
  margin: 0 auto;
  padding-top: 2.75rem;
  border: none;
  background: transparent;
}
div[data-testid="stForm"] h3 {
  font-family: var(--vd-font-display);
  font-size: 1.55rem;
  font-weight: 600;
  color: var(--vd-ink);
  margin-bottom: 2rem;
  letter-spacing: -.1px;
}
div[data-testid="stForm"] label p {
  font-family: var(--vd-font-body);
  font-size: 0.78rem;
  color: var(--vd-muted);
  font-weight: 500;
}
div[data-testid="stTextInput"] { margin-bottom: 6px; }
div[data-testid="stForm"] input {
  font-family: var(--vd-font-body);
  font-size: 0.95rem;
  border-radius: 4px;
  border: 1px solid var(--vd-border);
  padding: 13px 14px !important;
  line-height: 1.3;
  box-sizing: border-box;
}
div[data-testid="stForm"] input:focus {
  border-color: var(--vd-navy-mid);
  box-shadow: 0 0 0 1px var(--vd-navy-mid);
}
div[data-testid="stFormSubmitButton"] { margin-top: 10px; }
div[data-testid="stFormSubmitButton"] button {
  width: 100%;
  min-height: 48px;
  background: var(--vd-navy);
  color: #fff;
  border: none;
  border-radius: 4px;
  font-weight: 600;
  letter-spacing: .1px;
  padding: 0.85rem 0;
  line-height: 1.3;
  display: flex;
  align-items: center;
  justify-content: center;
}
div[data-testid="stFormSubmitButton"] button:hover { background: var(--vd-navy-mid); }
div[data-testid="stFormSubmitButton"] button * { color: #fff; line-height: 1.3; }
div[data-testid="stAlert"] {
  max-width: 380px;
  margin: 0.85rem auto 0;
  padding: 10px 14px;
  border-radius: 4px;
  border-left: 3px solid var(--vd-red);
  background: var(--vd-red-bg);
}
</style>
"""


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

else:
    # ── Tela de login ───────────────────────────────────────────────────────
    # Identidade principal: Valandro (fabricante do produto). Lyon Park aparece
    # apenas como contexto operacional/cliente — o sistema não é white-label.
    # Nenhuma regra de autenticação é alterada aqui: apenas layout e os rótulos
    # em português dos campos nativos do streamlit-authenticator (fields=...).
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)

    _col_esq, _col_centro, _col_dir = st.columns([1, 1, 1])
    with _col_centro:
        st.markdown(
            f'''<div class="vd-brand">
                <img src="{_asset_data_uri("valandro_logo.png")}" alt="Valandro" />
                <div class="vd-rule"></div>
                <div class="vd-context">Lyon Park<span class="vd-dot">·</span>Fechamento mensal</div>
            </div>''',
            unsafe_allow_html=True,
        )
        _authenticator.login(
            location="main",
            fields={
                "Form name": "Acesso à operação",
                "Username": "Usuário",
                "Password": "Senha",
                "Login": "Entrar",
            },
        )
        if st.session_state.get("authentication_status") is False:
            st.error("Usuário ou senha incorretos.")

# status None → apenas o formulário de login está visível (renderizado por _authenticator.login)
