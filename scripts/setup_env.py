#!/usr/bin/env python3
"""
Gera o arquivo .env com AUTH_USERS_YAML formatado corretamente.
Uso: .venv/bin/python scripts/setup_env.py
"""
import os
import re
import secrets
import sys

try:
    import bcrypt
except ImportError:
    sys.exit("Erro: bcrypt não instalado. Rode: pip install bcrypt")


ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")


def gerar_hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt(12)).decode()


def main():
    print("=== Lyon Park — Configuração de autenticação (.env) ===\n")

    if os.path.exists(ENV_PATH):
        resp = input(".env já existe. Sobrescrever? [s/N] ").strip().lower()
        if resp != "s":
            print("Cancelado.")
            return

    print("Informe os dados do usuário operador:\n")
    nome = input("Nome de exibição (ex: Operador Lyon Park): ").strip()
    if not nome:
        nome = "Operador Lyon Park"

    senha = input("Senha (será convertida em hash bcrypt): ").strip()
    if not senha:
        sys.exit("Erro: senha não pode ser vazia.")

    print("\nGerando hash bcrypt... ", end="", flush=True)
    pwd_hash = gerar_hash(senha)
    print("OK")

    cookie_key = secrets.token_hex(32)

    yaml_block = (
        f"credentials:\n"
        f"  usernames:\n"
        f"    operador:\n"
        f"      name: {nome}\n"
        f"      password: {pwd_hash}\n"
        f"cookie:\n"
        f"  name: lyon_auth\n"
        f"  key: {cookie_key}\n"
        f"  expiry_days: 7"
    )

    env_content = (
        f"AUTH_USERS_YAML='{yaml_block}'\n"
        f"DATA_DIR=\n"
        f"APP_ENV=development\n"
        f"DEBUG_AUTH=0\n"
    )

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(env_content)

    print(f"\n.env criado em: {os.path.abspath(ENV_PATH)}")
    print("Para validar o login, rode:")
    print("  .venv/bin/streamlit run main.py")
    print("\nPara ativar diagnóstico na UI, edite .env e setar DEBUG_AUTH=1")


if __name__ == "__main__":
    main()
