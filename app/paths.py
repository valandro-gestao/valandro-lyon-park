"""
Resolução centralizada de caminhos operacionais.

Todos os dados que precisam sobreviver a redeploys são derivados de DATA_DIR:
  - Produção (Render):   DATA_DIR=/mnt/data
  - Desenvolvimento:     DATA_DIR não definido → ./data (comportamento original)

data/seed.db    NÃO é o banco operacional — é apenas a origem da cópia inicial.
data/units.yaml NÃO é mais consultado em runtime para saber quais unidades
existem (isso é a tabela `unidades`, ver app.models.bootstrap_unidades_se_vazia
e migrations/0007) — continua sendo lido só como origem do bootstrap inicial
(quando a tabela está vazia) e como fonte de campos ainda não migrados para
tabela própria (ver app.engine._yaml_blocos).
"""
import logging
import shutil
import os
from pathlib import Path

_logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

DATA_DIR = Path(os.environ.get("DATA_DIR", "") or _PROJECT_ROOT / "data")
DB_PATH  = DATA_DIR / "db.sqlite"
RUNS_DIR = DATA_DIR / "runs"

# Banco seed incluído na imagem Docker (versionado em data/seed.db).
# Nunca é aberto diretamente pela aplicação — só serve como origem da cópia inicial.
_SEED_DB = _PROJECT_ROOT / "data" / "seed.db"

# Cadastro estrutural das unidades, versionado no repositório — origem do
# bootstrap inicial da tabela `unidades` (nunca sincronizado continuamente,
# ver app.models.bootstrap_unidades_se_vazia) e dos campos ainda não
# migrados para tabela própria (ver app.engine._yaml_blocos).
UNITS_YAML = _PROJECT_ROOT / "data" / "units.yaml"


def ensure_dirs() -> None:
    """Cria os diretórios operacionais necessários caso não existam."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def seed_db_if_missing() -> None:
    """
    Copia seed.db para DB_PATH se o banco operacional ainda não existir.

    Proteção explícita: se DB_PATH já existir, a função retorna imediatamente
    sem nenhuma ação — um banco operacional existente NUNCA é sobrescrito,
    independente do conteúdo do seed na imagem.
    """
    if DB_PATH.exists():
        _logger.info("Banco operacional encontrado.")
        _logger.info("Utilizando banco existente.")
        _logger.info("Caminho.....: %s", DB_PATH)
        return

    _logger.info("Banco operacional não encontrado.")

    if not _SEED_DB.exists():
        _logger.warning(
            "Seed não encontrado em %s. "
            "Um banco vazio será criado pelo init_db.",
            _SEED_DB,
        )
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    _logger.info("Inicializando banco a partir do seed.")
    _logger.info("Seed........: %s", _SEED_DB)
    _logger.info("Destino.....: %s", DB_PATH)

    shutil.copy2(_SEED_DB, DB_PATH)

    _logger.info("Inicialização concluída.")
