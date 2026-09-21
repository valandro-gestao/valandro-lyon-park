"""
Diagnóstico READ-ONLY de produção — homologação set/2026, 3ª rodada
(Viva Trindade/Investimentos, FIERGS/rubricas, EKOS-OKA/Taxa de Cobrança).

Só faz SELECT. Abre o banco em modo read-only (URI `?mode=ro` do SQLite —
o próprio SQLite recusa qualquer escrita nessa conexão, não é uma
convenção de código) e nunca importa `app.*` (evita qualquer efeito
colateral de import, como init_db()/seed_db_if_missing() tentando criar
ou copiar arquivo). Não usa nenhuma dependência além da biblioteca padrão
do Python — roda com o `python3` do sistema, sem precisar do venv do
projeto.

Uso (Render Shell):
    python3 scripts/diagnostico_producao_set2026.py

Por padrão lê de $DATA_DIR/db.sqlite (mesma resolução de app.paths); em
produção DATA_DIR=/mnt/data. Se DATA_DIR não estiver no ambiente do
shell, usa /mnt/data diretamente. Para apontar para outro arquivo:
    python3 scripts/diagnostico_producao_set2026.py /caminho/para/db.sqlite
"""
import json
import os
import sqlite3
import sys


def _resolver_db_path() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    data_dir = os.environ.get("DATA_DIR") or "/mnt/data"
    return os.path.join(data_dir, "db.sqlite")


def _conectar_ro(caminho: str) -> sqlite3.Connection:
    if not os.path.exists(caminho):
        sys.exit(f"Banco não encontrado em {caminho!r}. Passe o caminho correto como argumento.")
    uri = f"file:{caminho}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _linha(char="=", n=78):
    print(char * n)


def _titulo(txt):
    print()
    _linha()
    print(txt)
    _linha()


def _fmt_valor(v):
    try:
        parsed = json.loads(v)
        return json.dumps(parsed, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return v


def dump_parametros_vigentes(conn, unidade_id: str, filtro_parametro: str | None = None):
    sql = ("SELECT id, parametro, valor, tipo_dado, competencia_inicio, competencia_fim, "
           "alterado_em, alterado_por FROM parametros_vigentes WHERE unidade_id=?")
    params = [unidade_id]
    if filtro_parametro:
        sql += " AND parametro LIKE ?"
        params.append(filtro_parametro)
    sql += " ORDER BY parametro, competencia_inicio"
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        print(f"  (nenhuma linha de parametros_vigentes para {unidade_id!r}"
              + (f", filtro {filtro_parametro!r}" if filtro_parametro else "") + ")")
        return
    for r in rows:
        print(f"  [id={r['id']:>5}] {r['parametro']:<40} "
              f"{r['competencia_inicio']} -> {r['competencia_fim'] or 'ABERTA':<10} "
              f"valor={_fmt_valor(r['valor'])!s:<50} "
              f"tipo={r['tipo_dado']!s:<12} alterado_em={r['alterado_em']} por={r['alterado_por']}")


def dump_lancamentos(conn, unidade_id: str, meses: list[str]):
    for mes in meses:
        row = conn.execute(
            "SELECT id, faturamento, status, resultado_json, criado_em FROM lancamentos "
            "WHERE unidade_id=? AND mes_referencia=?",
            (unidade_id, mes),
        ).fetchone()
        print(f"  --- {mes} ---")
        if row is None:
            print("    (nenhum lançamento para esta competência)")
            continue
        dados = json.loads(row["resultado_json"])
        extras = dados.get("extras") or {}
        print(f"    id={row['id']} status={row['status']} criado_em={row['criado_em']}")
        print(f"    faturamento={dados.get('faturamento')} resultado={dados.get('resultado')} "
              f"subtotal={dados.get('subtotal')} ponto_equilibrio={dados.get('ponto_equilibrio')}")
        print(f"    prejuizo_acumulado_entrada={dados.get('prejuizo_acumulado_entrada')} "
              f"prejuizo_acumulado_saida={dados.get('prejuizo_acumulado_saida')}")
        print(f"    aluguel_calculado={dados.get('aluguel_calculado')}")
        print(f"    extras.investimentos={extras.get('investimentos')} "
              f"extras.outras_despesas={extras.get('outras_despesas')}")
        print(f"    custos={dados.get('custos')}")
        print(f"    extras completo={json.dumps(extras, ensure_ascii=False)}")


def dump_rascunhos(conn, unidade_id: str):
    rows = conn.execute(
        "SELECT mes_referencia, dados_json, atualizado_em FROM rascunhos_unidade "
        "WHERE unidade_id=? ORDER BY mes_referencia",
        (unidade_id,),
    ).fetchall()
    if not rows:
        print(f"  (nenhum rascunho pendente para {unidade_id!r} — bom sinal, "
              f"nada para _restaurar_rascunho repopular)")
        return
    for r in rows:
        dados = json.loads(r["dados_json"])
        campos_relevantes = {k: v for k, v in dados.items() if "investimentos" in k or "outras_despesas" in k
                              or "custos_variaveis" in k or "custos_mensais" in k or k.startswith("fat_")}
        print(f"  {r['mes_referencia']} atualizado_em={r['atualizado_em']}")
        print(f"    campos com investimentos/outras_despesas/custos/faturamento: {campos_relevantes}")
        print(f"    dados_json completo: {json.dumps(dados, ensure_ascii=False)}")


def dump_unidade(conn, unidade_id: str):
    row = conn.execute("SELECT * FROM unidades WHERE id=?", (unidade_id,)).fetchone()
    if row is None:
        print(f"  unidades.{unidade_id}: AUSENTE (não existe na tabela `unidades`)")
        return
    print(f"  unidades.{unidade_id}: {dict(row)}")


def main():
    caminho = _resolver_db_path()
    print(f"Banco (read-only): {caminho}")
    conn = _conectar_ro(caminho)

    _titulo("0. schema_migrations — confirma quais migrations foram aplicadas neste banco")
    rows = conn.execute("SELECT id, aplicada_em FROM schema_migrations ORDER BY id").fetchall()
    for r in rows:
        print(f"  {r['id']:<55} aplicada_em={r['aplicada_em']}")
    print(f"  total: {len(rows)} migration(s) aplicada(s)")

    _titulo("1. VIVA TRINDADE — Investimentos / Outras Despesas / cadeia de prejuízo")
    dump_unidade(conn, "viva_trindade")
    print("-- parametros_vigentes: custos_variaveis.investimentos --")
    dump_parametros_vigentes(conn, "viva_trindade", "custos_variaveis.investimentos")
    print("-- parametros_vigentes: custos_variaveis.outras_despesas --")
    dump_parametros_vigentes(conn, "viva_trindade", "custos_variaveis.outras_despesas")
    print("-- parametros_vigentes: saldo_acumulado_inicial (âncora da cadeia) --")
    dump_parametros_vigentes(conn, "viva_trindade", "saldo_acumulado_inicial")
    print("-- lancamentos: maio a setembro/2026 (cadeia completa ao redor de julho) --")
    dump_lancamentos(conn, "viva_trindade", ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"])
    print("-- rascunhos_unidade (draft de trabalho — PRIORIDADE sobre o valor do lançamento "
          "no default do widget; se houver um rascunho antigo de antes do deploy do fix, "
          "ele pode estar repopulando um valor obsoleto ao reabrir) --")
    dump_rascunhos(conn, "viva_trindade")

    _titulo("2. FIERGS — histórico completo de custos_variaveis (mapa_rubricas)")
    dump_unidade(conn, "fiergs")
    print("-- parametros_vigentes: custos_variaveis (bloco atômico, formato novo) --")
    dump_parametros_vigentes(conn, "fiergs", "custos_variaveis")
    print("-- parametros_vigentes: custos_variaveis.* (dot-notation legado) --")
    dump_parametros_vigentes(conn, "fiergs", "custos_variaveis.%")
    print("-- lancamentos: competência mais recente com lançamento --")
    row = conn.execute(
        "SELECT MAX(mes_referencia) AS mes FROM lancamentos WHERE unidade_id='fiergs'"
    ).fetchone()
    if row and row["mes"]:
        dump_lancamentos(conn, "fiergs", [row["mes"]])
    else:
        print("  (fiergs não tem nenhum lançamento ainda)")
    print("-- rascunhos_unidade (mesma checagem de prioridade que na Viva) --")
    dump_rascunhos(conn, "fiergs")

    _titulo("3. EKOS / OKA / TERRENO OKA — comparação campo a campo")
    for uid in ("ekos", "oka", "terreno_oka"):
        print(f"\n### {uid} ###")
        dump_unidade(conn, uid)
        print("  -- todos os parametros_vigentes --")
        dump_parametros_vigentes(conn, uid)

    conn.close()
    print()
    _linha()
    print("FIM — nenhuma escrita foi feita (conexão aberta em mode=ro).")
    _linha()


if __name__ == "__main__":
    main()
