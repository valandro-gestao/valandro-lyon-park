"""Inicializa o banco de dados e insere saldos iniciais."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import init_db
from app.engine import seed_saldos_iniciais

if __name__ == "__main__":
    init_db()
    seed_saldos_iniciais()
    from app.paths import DB_PATH
    print(f"Banco de dados inicializado em {DB_PATH}")
