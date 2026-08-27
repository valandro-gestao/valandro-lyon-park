"""
Aplica as migrações pendentes do banco operacional (ver migrations/).

Uso local (aplica em ./data/db.sqlite, criado a partir de data/seed.db se
ainda não existir):
  .venv/bin/python scripts/migrate.py

Uso em produção (Render — aplica no db.sqlite real, em /mnt/data):
  DATA_DIR=/mnt/data .venv/bin/python scripts/migrate.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from migrations.runner import run_all

if __name__ == "__main__":
    run_all()
