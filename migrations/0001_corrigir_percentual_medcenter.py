"""
Corrige a vigência do percentual_contratante do Medcenter.

O parâmetro foi seedado com 85% desde 2020-01, mas o valor contratual correto
até a competência 2026-06 era 75%. A partir de 2026-07 o contrato passa a
valer 85% — esse já era o valor seedado, só a vigência estava errada.

Usa exclusivamente a tabela parametros_vigentes já existente
(competencia_inicio/competencia_fim), sem tabela nova nem tela de
parametrização:
  - fecha a vigência aberta antes de 2026-07, corrigindo seu valor para 0.75;
  - garante uma vigência a partir de 2026-07 com 0.85.

Lançamentos já aprovados (tabela `lancamentos`) não são tocados por esta
migração — relatórios históricos não mudam. Afeta apenas o percentual usado
em cálculos futuros de competências ainda não aprovadas.

Idempotente: verifica o estado atual antes de cada alteração, então pode ser
executada mais de uma vez (ou contra uma base onde a correção já tenha sido
aplicada manualmente) sem duplicar vigências nem sobrescrever um valor já
correto.
"""
from app.models import _mes_anterior

UNIDADE = "medcenter"
PARAMETRO = "percentual_contratante"
CORTE = "2026-07"            # primeira competência com 85%
VALOR_HISTORICO = 0.75       # valor real até 2026-06
VALOR_ATUAL = 0.85            # valor a partir de 2026-07


def apply(conn):
    rows = conn.execute(
        "SELECT id, valor, competencia_inicio, competencia_fim FROM parametros_vigentes "
        "WHERE unidade_id=? AND parametro=? ORDER BY competencia_inicio",
        (UNIDADE, PARAMETRO),
    ).fetchall()

    if not rows:
        # Unidade ainda não seedada nesta base (ex.: banco novo, antes do
        # primeiro get_unit_com_params('medcenter', ...)). Cria as duas
        # vigências diretamente, para que a correção já valha desde o seed.
        fim_historico = _mes_anterior(CORTE)
        conn.execute(
            "INSERT INTO parametros_vigentes "
            "(unidade_id, parametro, valor, tipo_dado, descricao, "
            " competencia_inicio, competencia_fim, alterado_por) "
            "VALUES (?, ?, ?, 'percentual', 'Percentual do Contratante', '2020-01', ?, 'migration_0001')",
            (UNIDADE, PARAMETRO, str(VALOR_HISTORICO), fim_historico),
        )
        conn.execute(
            "INSERT INTO parametros_vigentes "
            "(unidade_id, parametro, valor, tipo_dado, descricao, "
            " competencia_inicio, alterado_por) "
            "VALUES (?, ?, ?, 'percentual', 'Percentual do Contratante', ?, 'migration_0001')",
            (UNIDADE, PARAMETRO, str(VALOR_ATUAL), CORTE),
        )
        return

    abertas = [r for r in rows if r["competencia_fim"] is None]
    ja_tem_corte = any(r["competencia_inicio"] == CORTE for r in rows)

    if abertas:
        atual = abertas[-1]
        if atual["competencia_inicio"] < CORTE and float(atual["valor"]) != VALOR_HISTORICO:
            fim_historico = _mes_anterior(CORTE)
            conn.execute(
                "UPDATE parametros_vigentes SET valor=?, competencia_fim=?, alterado_por=? "
                "WHERE id=?",
                (str(VALOR_HISTORICO), fim_historico, "migration_0001", atual["id"]),
            )
        # Se a vigência aberta já começa em CORTE ou depois, ou já está em
        # VALOR_HISTORICO, não há nada a corrigir nela.

    if not ja_tem_corte:
        conn.execute(
            "INSERT INTO parametros_vigentes "
            "(unidade_id, parametro, valor, tipo_dado, descricao, "
            " competencia_inicio, alterado_por) "
            "VALUES (?, ?, ?, 'percentual', 'Percentual do Contratante', ?, 'migration_0001')",
            (UNIDADE, PARAMETRO, str(VALOR_ATUAL), CORTE),
        )
