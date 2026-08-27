"""
Executor de migrações do banco operacional.

Cada migração é um arquivo `NNNN_nome.py` neste diretório, com uma função
`apply(conn)` que aplica a mudança usando a conexão sqlite3 recebida (a mesma
conexão de app.models.get_db() — respeita DATA_DIR, então funciona tanto
contra data/seed.db quanto contra o db.sqlite de produção, dependendo do
ambiente em que é executado).

Migrações já aplicadas ficam registradas na tabela `schema_migrations` e
nunca são reaplicadas pelo runner. Além disso, cada migração deve ser segura
de rodar mais de uma vez por conta própria (defesa em profundidade) — ver o
padrão em 0001_corrigir_percentual_medcenter.py.

Não substitui nem antecipa Alembic (reservado para a migração a Supabase em
v2.0.0 — decisão 9.4/registro de decisões do Padrão Tecnológico Valandro).
É uma estrutura mínima para o SQLite atual, focada em correções de dados e
de vigência como a que originou este mecanismo.
"""
import importlib.util
from pathlib import Path

from app.models import get_db, init_db

MIGRATIONS_DIR = Path(__file__).parent


def _garantir_tabela(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            aplicada_em TEXT DEFAULT (datetime('now'))
        )
    """)


def _descobrir_migracoes():
    """Migrações disponíveis, em ordem, a partir dos arquivos NNNN_nome.py.
    Carregadas por caminho de arquivo (não por import de pacote) porque
    nomes começando com dígito não são identificadores Python válidos."""
    migracoes = []
    for arquivo in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.py")):
        migration_id = arquivo.stem
        spec = importlib.util.spec_from_file_location(migration_id, arquivo)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        if not hasattr(modulo, "apply"):
            raise RuntimeError(f"Migração {migration_id} não define apply(conn).")
        migracoes.append((migration_id, modulo))
    return migracoes


def aplicadas(conn) -> set[str]:
    """Ids de migrações já registradas como aplicadas nesta base."""
    _garantir_tabela(conn)
    return {row["id"] for row in conn.execute("SELECT id FROM schema_migrations")}


def pendentes(conn) -> list[str]:
    """Ids de migrações disponíveis que ainda não foram aplicadas nesta base."""
    ja_aplicadas = aplicadas(conn)
    return [mid for mid, _ in _descobrir_migracoes() if mid not in ja_aplicadas]


def run_all(verbose: bool = True) -> list[str]:
    """
    Aplica todas as migrações pendentes, em ordem, numa única transação.
    Retorna os ids efetivamente aplicados nesta execução — lista vazia se
    não havia nenhuma pendente (chamada segura de repetir).
    """
    init_db()  # garante que o schema principal (tabelas base) já existe
    aplicadas_agora = []
    with get_db() as conn:
        ja_aplicadas = aplicadas(conn)
        for migration_id, modulo in _descobrir_migracoes():
            if migration_id in ja_aplicadas:
                continue
            if verbose:
                print(f"Aplicando {migration_id}...")
            modulo.apply(conn)
            conn.execute("INSERT INTO schema_migrations (id) VALUES (?)", (migration_id,))
            aplicadas_agora.append(migration_id)
            if verbose:
                print(f"  OK — {migration_id} aplicada.")
    if verbose and not aplicadas_agora:
        print("Nenhuma migração pendente.")
    return aplicadas_agora
