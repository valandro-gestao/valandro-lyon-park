"""
Relatório de auditoria do histórico mensal (`lancamentos`) após o bootstrap
da sprint v1.1.2 — primeira e última competência, quantidade de meses, e
lacunas por unidade. Não altera nada; só lê.

Uso:
  .venv/bin/python scripts/relatorio_historico_mensal.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import init_db, get_db
from app.engine import get_unit, get_unidades_ativas


def _nome(uid: str) -> str:
    if uid == "patio_real":
        return "Pátio — REAL"
    if uid == "patio_maiojama":
        return "Pátio — MAIOJAMA"
    try:
        return get_unit(uid)["nome"]
    except Exception:
        return uid


def _competencias_esperadas(inicio: str, fim: str) -> list[str]:
    ano, mes = int(inicio[:4]), int(inicio[5:7])
    fim_ano, fim_mes = int(fim[:4]), int(fim[5:7])
    out = []
    while (ano, mes) <= (fim_ano, fim_mes):
        out.append(f"{ano:04d}-{mes:02d}")
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1
    return out


def main():
    init_db()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT unidade_id, mes_referencia FROM lancamentos ORDER BY unidade_id, mes_referencia"
        ).fetchall()

    por_unidade: dict[str, list[str]] = {}
    for r in rows:
        por_unidade.setdefault(r["unidade_id"], []).append(r["mes_referencia"])

    uids_com_relatorio = set()
    for u in get_unidades_ativas():
        if u.get("tipo_calculo") == "PATIO_OPERACAO":
            uids_com_relatorio.update({"patio_real", "patio_maiojama"})
        else:
            uids_com_relatorio.add(u["id"])

    print("=" * 60)
    print("AUDITORIA DO HISTÓRICO MENSAL (lancamentos)")
    print("=" * 60)
    print()

    sem_historico = []
    inconsistencias = []

    for uid in sorted(uids_com_relatorio, key=_nome):
        competencias = sorted(por_unidade.get(uid, []))
        nome = _nome(uid)
        if not competencias:
            sem_historico.append(nome)
            continue

        primeira, ultima = competencias[0], competencias[-1]
        esperadas = _competencias_esperadas(primeira, ultima)
        faltantes = sorted(set(esperadas) - set(competencias))

        print(nome)
        print(f"{primeira} → {ultima}")
        print(f"{len(competencias)} competências")
        if faltantes:
            print(f"  ⚠ competências faltantes ({len(faltantes)}): {', '.join(faltantes)}")
            inconsistencias.append(f"{nome}: faltam {', '.join(faltantes)}")
        print()

    print("-" * 60)
    if sem_historico:
        print(f"Unidades sem histórico ({len(sem_historico)}):")
        for nome in sem_historico:
            print(f"  - {nome}")
    else:
        print("Nenhuma unidade ativa sem histórico.")

    print()
    if inconsistencias:
        print(f"Inconsistências encontradas ({len(inconsistencias)}):")
        for msg in inconsistencias:
            print(f"  - {msg}")
    else:
        print("Nenhuma lacuna de competência encontrada dentro dos períodos com histórico.")


if __name__ == "__main__":
    main()
