"""
Client da API Aucon/eCloud — v1.3.0 (Integração de Faturamento).

Única fonte da regra de faturamento validada em homologação real de
agosto/2026 (9 unidades: Dom Pedro, Axis, Vasco da Gama, Viva Trindade,
Anitta Mall, FK, IN 1183, MW Tristeza, W Tower Caxias — todas reconciliadas
ao centavo com o faturamento aprovado no Lyon Reports): soma o campo
monetário dos seis métodos que a Aucon indicou para compor faturamento, no
mês completo da competência, excluindo qualquer registro com
MeioPagamento="CANCELADO". Não filtra por DataCompetencia/Competencia —
esses campos não representam o corte que reconciliou com o faturamento
aprovado (ex.: Recebimento de Conveniados aparece, na janela de um mês,
quase sempre com Competencia do mês ANTERIOR, e mesmo assim entra na soma).

Autenticação e formato de requisição idênticos aos já validados em
scripts/diagnostico_aucon_teste_manual.py (script de diagnóstico manual,
que continua existindo separadamente — não importa nada daqui, nem este
módulo depende dele).

Credenciais: variáveis de ambiente AUCON_USERNAME/AUCON_PASSWORD (Render
secrets em produção — nunca banco, código, logs ou tela de Administração),
lidas com o mesmo padrão já usado por app.paths (os.environ.get), sem
python-dotenv/.env.aucon dentro de app/ — isso continua exclusivo do
script de diagnóstico local.
"""
from __future__ import annotations

import calendar
import os
import time
from dataclasses import dataclass
from datetime import datetime

import requests

BASE_URL = "https://ecloud.net.br/erp/server/api"

# nome do endpoint -> (path, campo monetário relevante na resposta).
# Campos conferidos na documentação e nos testes reais de homologação;
# "recebimento_credito" nunca teve dado real não-vazio nos testes feitos —
# ValorRecebido é o campo mais próximo de "recebido" na documentação,
# mantido por analogia aos demais, sem confirmação empírica com valor != 0.
_ENDPOINTS: dict[str, tuple[str, str]] = {
    "mensalidades": ("/wsaucon/mensalidades", "Valor"),
    "entradascaixa": ("/wsaucon/entradascaixa", "Valor"),
    "pagamentos": ("/wsaucon/pagamentos", "Valor"),
    "recebimento_credito": ("/wsaucon/recebimento_credito", "ValorRecebido"),
    "recebimento_conveniados": ("/wsaucon/recebimento_conveniados", "Valor"),
    "recebimento_correspondentes": ("/wsaucon/recebimento_correspondentes", "Valor"),
}

_MARGEM_SEGURANCA_TOKEN_SEGUNDOS = 60


class AuconAuthError(Exception):
    """Falha ao autenticar em POST /token — precondição de todo o lote, não
    um erro de uma unidade isolada. Quem chama deve abortar o lote inteiro
    (nenhuma unidade é tocada), não tratar como falha por unidade."""


class AuconRespostaIncompletaError(Exception):
    """Algum dos seis endpoints falhou (timeout, HTTP != 200, corpo
    inválido). Nunca é somado parcialmente — a unidade inteira fica sem
    atualização nesta rodada, o faturamento existente não é tocado."""


@dataclass
class AuconResultado:
    """Resultado de uma consulta de faturamento a uma única filial/mês.
    `valor` já é o campo-base pronto para `Faturamento (R$)` (bruto menos
    cancelados) — nunca inclui Faturamento Carregadores nem qualquer outro
    campo específico de calculadora, que permanecem totalmente
    independentes desta integração."""
    codigo_filial: int
    valor: float
    bruto: float
    cancelados: float
    importado_em: str


# ─── autenticação, com cache/reuso de token em memória por processo ──────────

_token_cache: dict = {"token": None, "expira_em": 0.0}


def _autenticar() -> str:
    username = os.environ.get("AUCON_USERNAME")
    password = os.environ.get("AUCON_PASSWORD")
    if not username or not password:
        raise AuconAuthError("AUCON_USERNAME/AUCON_PASSWORD não configurados no ambiente.")

    try:
        resp = requests.post(
            f"{BASE_URL}/token",
            data={"username": username, "password": password, "grant_type": "password"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
    except requests.RequestException as e:
        raise AuconAuthError(f"Falha de rede ao autenticar na Aucon: {e}") from e

    if resp.status_code != 200:
        raise AuconAuthError(f"Falha em /token: HTTP {resp.status_code}")

    corpo = resp.json()
    token = corpo.get("access_token")
    if not token:
        raise AuconAuthError("Resposta de /token não trouxe access_token.")

    expires_in = float(corpo.get("expires_in") or 0)
    _token_cache["token"] = token
    _token_cache["expira_em"] = time.time() + max(expires_in - _MARGEM_SEGURANCA_TOKEN_SEGUNDOS, 0)
    return token


def _obter_token() -> str:
    """Reusa o token em cache enquanto válido — evita autenticar uma vez
    por unidade/endpoint num lote com dezenas de unidades. Cache é
    module-level (por processo); em múltiplos workers, cada um autentica
    independentemente — simplificação aceita para V1."""
    if _token_cache["token"] and time.time() < _token_cache["expira_em"]:
        return _token_cache["token"]
    return _autenticar()


def _resetar_cache_token() -> None:
    """Uso exclusivo de testes — força a próxima chamada a reautenticar."""
    _token_cache["token"] = None
    _token_cache["expira_em"] = 0.0


# ─── consulta aos seis endpoints ──────────────────────────────────────────────

def _buscar_endpoint(token: str, path: str, codigo_filial: int,
                      data_inicial: str, data_final: str) -> list[dict]:
    payload = {
        "CodigoFilial": codigo_filial,
        "DataInicial": data_inicial,
        "DataFinal": data_final,
    }
    try:
        resp = requests.post(
            f"{BASE_URL}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        raise AuconRespostaIncompletaError(f"Falha de rede em {path}: {e}") from e

    if resp.status_code != 200:
        raise AuconRespostaIncompletaError(f"Falha em {path}: HTTP {resp.status_code}")

    try:
        return resp.json()
    except ValueError as e:
        raise AuconRespostaIncompletaError(f"Resposta inválida em {path}: {e}") from e


def _periodo_mes_completo(mes_ref: str) -> tuple[str, str]:
    """(DataInicial, DataFinal) cobrindo o mês inteiro de `mes_ref`
    ("2026-08"), no formato exigido pela API ("yyyy-MM-ddTHH:mm:ss")."""
    ano, mes = int(mes_ref[:4]), int(mes_ref[5:7])
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    inicio = f"{ano:04d}-{mes:02d}-01T00:00:00"
    fim = f"{ano:04d}-{mes:02d}-{ultimo_dia:02d}T23:59:59"
    return inicio, fim


def buscar_faturamento_aucon(codigo_filial: int, mes_ref: str) -> AuconResultado:
    """
    Regra validada em homologação (agosto/2026): soma o campo monetário dos
    seis métodos que a Aucon indicou para compor faturamento, no mês
    completo de `mes_ref`, excluindo qualquer registro com
    MeioPagamento="CANCELADO" em QUALQUER um dos seis endpoints — não só em
    Pagamentos, onde foi observado até agora. Não aplica nenhum filtro por
    DataCompetencia/Competencia.

    Levanta AuconRespostaIncompletaError se qualquer um dos seis endpoints
    falhar — nunca retorna uma soma parcial de "5 de 6". Levanta
    AuconAuthError se a autenticação falhar (deve abortar o lote inteiro,
    não só esta unidade — ver app.ui.fechamento).
    """
    token = _obter_token()
    data_inicial, data_final = _periodo_mes_completo(mes_ref)

    bruto = 0.0
    cancelados = 0.0
    for _nome, (path, campo) in _ENDPOINTS.items():
        registros = _buscar_endpoint(token, path, codigo_filial, data_inicial, data_final)
        for r in registros:
            v = float(r.get(campo) or 0.0)
            bruto += v
            if r.get("MeioPagamento") == "CANCELADO":
                cancelados += v

    valor = round(bruto - cancelados, 2)
    return AuconResultado(
        codigo_filial=codigo_filial,
        valor=valor,
        bruto=round(bruto, 2),
        cancelados=round(cancelados, 2),
        importado_em=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
