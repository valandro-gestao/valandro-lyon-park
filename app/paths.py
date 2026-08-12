"""
Resolução centralizada de caminhos operacionais.

Todos os dados que precisam sobreviver a redeploys são derivados de DATA_DIR:
  - Produção (Render):   DATA_DIR=/mnt/data
  - Desenvolvimento:     DATA_DIR não definido → ./data (comportamento original)

data/units.yaml NÃO passa por aqui — é configuração estrutural versionada no repositório.
"""
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

DATA_DIR = Path(os.environ.get("DATA_DIR", "") or _PROJECT_ROOT / "data")
DB_PATH  = DATA_DIR / "db.sqlite"
RUNS_DIR = DATA_DIR / "runs"


def ensure_dirs() -> None:
    """Cria os diretórios operacionais necessários caso não existam."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
