#!/usr/bin/env python3
"""
Diagnóstico READ-ONLY de produção — aprovações de workflow sem lançamento
correspondente.

Procura, em todas as competências que têm um `runs/{mês}/status.json`,
unidades cujo workflow está `aprovado` mas cujo estado consolidado não bate:

  SEM_LANCAMENTO           workflow `aprovado`, nenhuma linha em `lancamentos`
                           para (unidade, competência). É o defeito dos antigos
                           atalhos "Aprovar todos" e "Aprovar" rápido da lista,
                           que só chamavam `run_manager.mark_approved`.
  LANCAMENTO_NAO_APROVADO  workflow `aprovado`, linha em `lancamentos` com
                           status diferente de `aprovado`.
  SEM_PDF                  workflow `aprovado`, mas o PDF registrado em
                           `pdf_path` não existe em disco. Não é o defeito
                           acima; entra aqui porque o PDF definitivo é uma das
                           condições de elegibilidade do futuro envio de
                           rascunhos de e-mail.

Seção informativa (não é inconsistência): unidades com lançamento `aprovado`
cujo workflow NÃO está `aprovado` (ex.: `reaberto`, ou `gerado` depois de
"Gerar PDF" numa unidade já aprovada). São esperadas; aparecem porque essas
unidades não seriam elegíveis ao envio.

Só faz SELECT e só lê arquivos. Abre o banco em modo read-only (URI `?mode=ro`
do SQLite + `PRAGMA query_only=ON` — o próprio SQLite recusa qualquer escrita
nessa conexão) e nunca importa `app.*` (sem init_db()/seed/efeito colateral
de import). Só biblioteca padrão — roda com o `python3` do sistema. NÃO corrige
nada: apenas relata. Competências históricas importadas por migration (sem
`runs/{mês}/status.json`) ficam fora do escopo por construção.

Uso (Render Shell):
    python3 scripts/diagnostico_aprovacao_inconsistente.py > /tmp/diag_aprov.txt; \
        sed -n '/SINALIZADORES/,$p' /tmp/diag_aprov.txt

Por padrão lê de $DATA_DIR/db.sqlite e $DATA_DIR/runs (em produção
DATA_DIR=/mnt/data). Para apontar para outro local:
    python3 scripts/diagnostico_aprovacao_inconsistente.py /caminho/db.sqlite [/caminho/runs]
A seção "SINALIZADORES", no fim da saída, resume os achados.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path


def _resolver_caminhos() -> tuple[Path, Path]:
    data_dir = Path(os.environ.get("DATA_DIR") or "/mnt/data")
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else data_dir / "db.sqlite"
    runs = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        db.parent / "runs" if len(sys.argv) > 1 else data_dir / "runs")
    return db, runs


def _conectar_ro(caminho: Path) -> sqlite3.Connection:
    if not caminho.exists():
        sys.exit(f"Banco não encontrado em {str(caminho)!r}. Passe o caminho correto como argumento.")
    conn = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _linha(char="=", n=78):
    print(char * n)


def _titulo(txt):
    print()
    _linha()
    print(txt)
    _linha()


def _pdf_existe(mes: str, runs: Path, pdf_path: str | None) -> tuple[bool, str]:
    """True se o PDF registrado existe. O `pdf_path` do status.json é absoluto
    na máquina que o gravou; se a verificação roda numa cópia em outro lugar,
    tenta o mesmo nome de arquivo em runs/{mês}/reports/ ao lado do banco."""
    if not pdf_path:
        return False, "sem pdf_path registrado"
    if os.path.exists(pdf_path):
        return True, "ok"
    alternativo = runs / mes / "reports" / Path(pdf_path).name
    if alternativo.exists():
        return True, f"ok (resolvido em {alternativo})"
    return False, f"arquivo ausente: {pdf_path}"


def main():
    db_path, runs_dir = _resolver_caminhos()
    conn = _conectar_ro(db_path)

    print(f"banco: {db_path}")
    print(f"runs:  {runs_dir}")

    lanc = {
        (r["unidade_id"], r["mes_referencia"]): r["status"]
        for r in conn.execute("SELECT unidade_id, mes_referencia, status FROM lancamentos")
    }

    competencias = sorted(p for p in runs_dir.glob("*/status.json")) if runs_dir.is_dir() else []
    if not competencias:
        print("\nNenhum runs/*/status.json encontrado — nada a verificar.")

    total_wf = 0
    total_aprovados = 0
    achados: list[tuple[str, str, str, str, str]] = []   # (classe, mês, uid, wf, detalhe)
    informativos: list[tuple[str, str, str, str]] = []   # (mês, uid, wf, lanc)
    ilegiveis: list[str] = []

    _titulo("VERIFICAÇÃO POR COMPETÊNCIA")
    for arq in competencias:
        mes = arq.parent.name
        try:
            run = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            ilegiveis.append(f"{mes}: {e}")
            print(f"{mes}: status.json ilegível ({e})")
            continue

        aprovados_mes = 0
        for uid, info in sorted(run.items()):
            if not isinstance(info, dict):
                continue
            wf = info.get("status")
            total_wf += 1
            st_lanc = lanc.get((uid, mes))

            if wf == "aprovado":
                aprovados_mes += 1
                total_aprovados += 1
                if st_lanc is None:
                    achados.append(("SEM_LANCAMENTO", mes, uid, wf,
                                    "nenhuma linha em lancamentos"))
                elif st_lanc != "aprovado":
                    achados.append(("LANCAMENTO_NAO_APROVADO", mes, uid, wf,
                                    f"lancamentos.status={st_lanc!r}"))
                existe, detalhe = _pdf_existe(mes, runs_dir, info.get("pdf_path"))
                if not existe:
                    achados.append(("SEM_PDF", mes, uid, wf, detalhe))
            elif st_lanc == "aprovado":
                informativos.append((mes, uid, wf or "?", st_lanc))

        print(f"{mes}: {len(run)} unidade(s) no workflow, {aprovados_mes} aprovada(s)")

    _titulo("INCONSISTÊNCIAS (workflow `aprovado`)")
    if not achados:
        print("  (nenhuma)")
    for classe, mes, uid, wf, detalhe in sorted(achados, key=lambda a: (a[0], a[1], a[2])):
        print(f"  [{classe:<24}] {mes}  {uid:<18} workflow={wf}  {detalhe}")

    _titulo("INFORMATIVO — lançamento aprovado, workflow não aprovado (esperado)")
    if not informativos:
        print("  (nenhum)")
    for mes, uid, wf, st_lanc in sorted(informativos):
        print(f"  {mes}  {uid:<18} workflow={wf:<9} lancamentos.status={st_lanc}")

    _titulo("SINALIZADORES")
    por_classe = {}
    for classe, *_ in achados:
        por_classe[classe] = por_classe.get(classe, 0) + 1
    print(f"competências com status.json lidas: {len(competencias) - len(ilegiveis)}"
          f" (ilegíveis: {len(ilegiveis)})")
    print(f"unidades/PDFs no workflow: {total_wf}   com workflow aprovado: {total_aprovados}")
    for classe in ("SEM_LANCAMENTO", "LANCAMENTO_NAO_APROVADO", "SEM_PDF"):
        n = por_classe.get(classe, 0)
        marca = "!!" if n and classe != "SEM_PDF" else ("! " if n else "ok")
        print(f"  [{marca}] {classe:<24} {n}")
    print(f"  [..] informativos (lançamento aprovado, workflow não aprovado): {len(informativos)}")
    if ilegiveis:
        print("  [!!] status.json ilegíveis: " + "; ".join(ilegiveis))
    if not achados and not ilegiveis:
        print("\nResultado: nenhuma inconsistência encontrada.")
    else:
        print("\nResultado: há itens acima. Este script NÃO corrige nada; a decisão "
              "sobre cada caso é manual.")


if __name__ == "__main__":
    main()
