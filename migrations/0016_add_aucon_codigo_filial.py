"""
Adiciona `unidades.aucon_codigo_filial` (v1.3.0 — Integração Aucon/eCloud).

Vínculo estável entre uma unidade Lyon e sua filial correspondente na
Aucon, validado empiricamente em homologação (reconciliação exata de
faturamento em 9 unidades reais de agosto/2026, seis endpoints + exclusão
de MeioPagamento="CANCELADO"). NULL = unidade sem integração Aucon
(continua no fluxo manual/planilha de faturamento, sem nenhuma mudança de
comportamento).

app.models.init_db() já adiciona esta coluna de forma idempotente (mesmo
padrão já usado para parametros_vigentes.tipo_dado/descricao) — esta
migração formaliza o mesmo passo como um registro auditável do histórico
de deploy, no mesmo espírito da migration 0007 para a criação de
`unidades` em si. Idempotente: se a coluna já existir (por já ter passado
por init_db()), não faz nada além de registrar a aplicação.

Nenhum dado é preenchido aqui — todas as unidades nascem com
aucon_codigo_filial=NULL; o preenchimento é uma ação manual na tela de
Administração, unidade por unidade, depois do deploy.
"""
import sqlite3


def apply(conn):
    try:
        conn.execute("ALTER TABLE unidades ADD COLUMN aucon_codigo_filial INTEGER")
        print("  add_aucon_codigo_filial: coluna 'aucon_codigo_filial' adicionada a 'unidades'.")
    except sqlite3.OperationalError:
        print("  add_aucon_codigo_filial: coluna 'aucon_codigo_filial' já existia — nada a fazer.")
