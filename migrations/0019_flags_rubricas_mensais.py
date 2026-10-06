"""
Liga `tem_investimentos` / `tem_outras_despesas` para as unidades que HOJE
mostram esses campos no Fechamento só por terem uma linha histórica em
`parametros_vigentes` — homologação set/2026, 4ª rodada.

Investimentos e Outras Despesas deixaram de ser parâmetros com vigência
(são rubricas mensais: o valor pertence à competência). O que decide se o
campo aparece no Fechamento passou a ser a chave explícita da unidade
(`tem_investimentos` em COM_ALIQUOTA/COM_ALIQUOTA_CUMUL, `tem_outras_despesas`
em COM_ALIQUOTA_CUMUL), configurada na Administração — não mais a
presença de uma linha `custos_variaveis.<rubrica>` (ver
app.ui.fechamento._itens_custos_variaveis).

Para não fazer nenhum campo sumir em produção, esta migration preserva o
que já é exibido: para cada unidade desses tipos que tem uma linha
`custos_variaveis.investimentos` / `custos_variaveis.outras_despesas` (de
qualquer origem, inclusive a seed 0.0 da 0015) e ainda não tem a chave
`tem_<rubrica>` registrada, insere `tem_<rubrica> = true` (vigência desde
2020-01, `alterado_por='migration_0019'`).

Não altera nem apaga nenhuma linha existente (as linhas históricas das
rubricas continuam lá, para auditoria e para a 0018), não toca
`lancamentos`. Idempotente: só insere quando a chave `tem_<rubrica>` ainda
não existe para a unidade.
"""
import json

TIPOS = {
    "COM_ALIQUOTA": ("investimentos",),
    "COM_ALIQUOTA_CUMUL": ("outras_despesas", "investimentos"),
}
COMPETENCIA_INICIO = "2020-01"
ORIGEM = "migration_0019"


def apply(conn):
    ligadas = []
    for tipo, rubricas in TIPOS.items():
        unidades = conn.execute(
            "SELECT id FROM unidades WHERE tipo_calculo=?", (tipo,)
        ).fetchall()
        for u in unidades:
            for rid in rubricas:
                tem_linha_historica = conn.execute(
                    "SELECT 1 FROM parametros_vigentes WHERE unidade_id=? AND parametro=? LIMIT 1",
                    (u["id"], f"custos_variaveis.{rid}"),
                ).fetchone()
                ja_configurada = conn.execute(
                    "SELECT 1 FROM parametros_vigentes WHERE unidade_id=? AND parametro=? LIMIT 1",
                    (u["id"], f"tem_{rid}"),
                ).fetchone()
                if tem_linha_historica and not ja_configurada:
                    conn.execute(
                        "INSERT INTO parametros_vigentes "
                        "(unidade_id, parametro, valor, tipo_dado, descricao, "
                        " competencia_inicio, alterado_por) "
                        "VALUES (?, ?, ?, 'booleano', ?, ?, ?)",
                        (u["id"], f"tem_{rid}", json.dumps(True),
                         f"Tem {rid.replace('_', ' ').title()} (campo mensal no Fechamento) — "
                         "preserva o que a unidade já exibia",
                         COMPETENCIA_INICIO, ORIGEM),
                    )
                    ligadas.append(f"{u['id']}:tem_{rid}")
    print(f"  flags_rubricas_mensais: {len(ligadas)} chave(s) ligada(s) {ligadas}")
