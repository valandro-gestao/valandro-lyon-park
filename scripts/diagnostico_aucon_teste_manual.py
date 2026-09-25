"""
Teste manual e isolado de leitura da API Aucon/eCloud.

NAO integrado ao Lyon Reports: nao importa nada de app/, nao abre nenhum
banco do projeto, nao escreve em lancamentos/unidades, nao roda migration.
Serve para coletar, de forma bruta e isolada por metodo, os seis retornos
que a Aucon indicou como necessarios para compor faturamento (Mensalidades,
Entradas de Caixa, Pagamentos, Recebimento de Creditos, Recebimento de
Conveniados, Recebimento de Correspondentes), para uma unidade e uma janela
de datas — sem somar, sem excluir e sem aplicar nenhuma regra de faturamento.

Credenciais: lidas de .env.aucon (na raiz do projeto, fora do git — ver
.env.aucon.example para o formato). Nao sao lidas de nenhum outro .env do
projeto nem de argumento de linha de comando.

Uso:
  .venv/bin/python scripts/diagnostico_aucon_teste_manual.py \\
    --inicio 2026-08-01 --fim 2026-08-31 --label 2026-08_mes_completo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_URL = "https://ecloud.net.br/erp/server/api"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "data" / "runs" / "diagnostico_aucon"
ENV_AUCON_PATH = PROJECT_ROOT / ".env.aucon"

# Os seis metodos indicados pela Aucon para compor faturamento.
# nome do arquivo -> path do endpoint (payload identico nos seis: CodigoFilial/DataInicial/DataFinal).
ENDPOINTS = {
    "mensalidades": "/wsaucon/mensalidades",
    "entradascaixa": "/wsaucon/entradascaixa",
    "pagamentos": "/wsaucon/pagamentos",
    "recebimento_credito": "/wsaucon/recebimento_credito",
    "recebimento_conveniados": "/wsaucon/recebimento_conveniados",
    "recebimento_correspondentes": "/wsaucon/recebimento_correspondentes",
}


def autenticar(username: str, password: str) -> str:
    resp = requests.post(
        f"{BASE_URL}/token",
        data={"username": username, "password": password, "grant_type": "password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Falha em /token: HTTP {resp.status_code}")
        print(f"Corpo retornado pela API: {resp.text}")
        try:
            corpo_erro = resp.json()
        except ValueError:
            corpo_erro = None
        if isinstance(corpo_erro, dict):
            if "error" in corpo_erro:
                print(f"error: {corpo_erro['error']}")
            if "error_description" in corpo_erro:
                print(f"error_description: {corpo_erro['error_description']}")
        resp.raise_for_status()

    corpo = resp.json()
    token = corpo.get("access_token")
    if not token:
        raise RuntimeError("Resposta de /token nao trouxe access_token.")
    return token


def buscar_endpoint(
    token: str, nome: str, path: str, codigo_filial: int, data_inicial: str, data_final: str
) -> list[dict]:
    payload = {
        "CodigoFilial": codigo_filial,
        "DataInicial": data_inicial,
        "DataFinal": data_final,
    }
    resp = requests.post(
        f"{BASE_URL}{path}",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    print(f"[{nome}] HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"[{nome}] Corpo retornado pela API: {resp.text}")
        resp.raise_for_status()
    return resp.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inicio", required=True, help="yyyy-MM-dd")
    parser.add_argument("--fim", required=True, help="yyyy-MM-dd")
    parser.add_argument(
        "--label",
        default=None,
        help="Nome da subpasta em data/runs/diagnostico_aucon/ (default: <inicio>_a_<fim>)",
    )
    parser.add_argument(
        "--codigo-filial",
        type=int,
        default=None,
        help="Sobrescreve AUCON_CODIGO_FILIAL de .env.aucon para esta execucao "
        "(nao e credencial, so o codigo numerico de filial).",
    )
    args = parser.parse_args()

    if not ENV_AUCON_PATH.exists():
        print(
            f"Arquivo {ENV_AUCON_PATH} nao encontrado. Copie .env.aucon.example "
            "para .env.aucon e preencha com as credenciais reais.",
            file=sys.stderr,
        )
        sys.exit(1)

    load_dotenv(dotenv_path=ENV_AUCON_PATH, override=True)

    username = os.environ.get("AUCON_USERNAME")
    password = os.environ.get("AUCON_PASSWORD")
    codigo_filial_raw = os.environ.get("AUCON_CODIGO_FILIAL")

    if not username or not password or (codigo_filial_raw is None and args.codigo_filial is None):
        print(
            "Defina AUCON_USERNAME, AUCON_PASSWORD e AUCON_CODIGO_FILIAL "
            f"em {ENV_AUCON_PATH} (ou passe --codigo-filial) antes de rodar.",
            file=sys.stderr,
        )
        sys.exit(1)

    codigo_filial = args.codigo_filial if args.codigo_filial is not None else int(codigo_filial_raw)
    data_inicial = f"{args.inicio}T00:00:00"
    data_final = f"{args.fim}T23:59:59"
    label = args.label or f"{args.inicio}_a_{args.fim}"

    print("Autenticando na API Aucon/eCloud (usuario e senha nao serao exibidos)...")
    token = autenticar(username, password)
    print("Autenticacao OK. Token obtido (nao exibido). Usando Authorization: Bearer <token>.")

    destino_dir = RUNS_DIR / label
    destino_dir.mkdir(parents=True, exist_ok=True)

    for nome, path in ENDPOINTS.items():
        print(
            f"Consultando {path} para CodigoFilial={codigo_filial}, "
            f"{data_inicial} a {data_final}..."
        )
        registros = buscar_endpoint(token, nome, path, codigo_filial, data_inicial, data_final)
        print(f"[{nome}] Registros retornados: {len(registros)}")

        destino = destino_dir / f"{nome}_codigofilial_{codigo_filial}.json"
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(registros, f, ensure_ascii=False, indent=2)
        print(f"[{nome}] JSON bruto salvo em: {destino}")

    print("Coleta dos seis metodos concluida.")


if __name__ == "__main__":
    main()
