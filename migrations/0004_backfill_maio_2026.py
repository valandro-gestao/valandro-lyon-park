"""
Backfill pontual da competência 2026-05, para as unidades que ficaram de
fora tanto do lançamento real da ferramenta quanto do bootstrap da migração
0002 (ver scripts/extrair_historico_lancamentos.py — MES_CORTE = "2026-05"
era um limite exclusivo que presumia, incorretamente, que toda unidade já
tinha 2026-05 real em `lancamentos`).

Lê migrations/data/historico_lancamentos_2026_05.json (gerado por
scripts/extrair_maio_2026.py a partir da mesma planilha histórica, reaproveitando
os mesmos mapeamentos de coluna já verificados) e insere `lancamentos` para
(unidade_id, "2026-05") **somente quando essa linha ainda não existir**.

Não sobrescreve nenhum lançamento real já existente — a_schneider,
anitta_mall, fiergs, patio_real e patio_maiojama já têm 2026-05 real e são
preservados sem qualquer alteração.

Não modifica migrations/0002 nem 0003, nem
migrations/data/historico_lancamentos.json. É uma migração independente,
adicional, seguindo exatamente o mesmo padrão da 0002.

Idempotente por construção: antes de cada inserção, verifica se
(unidade_id, "2026-05") já existe — correr de novo (mesmo direto, sem passar
pelo runner/schema_migrations) não duplica nem sobrescreve nada.
"""
import json
from pathlib import Path

DADOS_PATH = Path(__file__).parent / "data" / "historico_lancamentos_2026_05.json"
MES_ALVO = "2026-05"


def apply(conn):
    if not DADOS_PATH.exists():
        raise RuntimeError(
            f"Arquivo de dados não encontrado: {DADOS_PATH}. "
            "Gere-o com scripts/extrair_maio_2026.py antes de aplicar esta migração."
        )

    with open(DADOS_PATH, encoding="utf-8") as f:
        historico_maio = json.load(f)

    existentes = {
        row["unidade_id"]
        for row in conn.execute(
            "SELECT unidade_id FROM lancamentos WHERE mes_referencia=?", (MES_ALVO,)
        )
    }

    inseridos = 0
    preservados = 0

    for unidade_id, registros in historico_maio.items():
        for r in registros:
            if r["mes_referencia"] != MES_ALVO:
                continue  # o arquivo é só de maio/2026, mas não confia cegamente
            if unidade_id in existentes:
                preservados += 1
                continue

            resultado_dict = {
                "unidade_id": unidade_id,
                "mes_referencia": MES_ALVO,
                "faturamento": r["faturamento"],
                "aliquota_imposto": 0.0,
                "subtotal": 0.0,
                "ponto_equilibrio": 0.0,
                "custos": {},
                "resultado": r.get("resultado") if r.get("resultado") is not None else 0.0,
                "prejuizo_acumulado_entrada": 0.0,
                "prejuizo_acumulado_saida": 0.0,
                "aluguel_calculado": r.get("aluguel_calculado", 0.0),
                "splits": {},
                "extras": r.get("extras") or {},
                "observacoes": "Restaurado do histórico anterior ao Lyon Reports (migration 0004 — backfill pontual de 2026-05).",
                "status": "aprovado",
            }

            conn.execute(
                "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    unidade_id,
                    MES_ALVO,
                    r["faturamento"],
                    json.dumps(resultado_dict, ensure_ascii=False),
                    "aprovado",
                ),
            )
            existentes.add(unidade_id)
            inseridos += 1

    print(f"  backfill_maio_2026: {inseridos} unidade(s) recebeu(ram) o backfill de {MES_ALVO}, "
          f"{preservados} já tinham lançamento real (preservado).")
