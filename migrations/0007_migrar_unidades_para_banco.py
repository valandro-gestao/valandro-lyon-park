"""
Migra a fonte de verdade ESTRUTURAL das unidades de `data/units.yaml` para
uma tabela própria (`unidades`) no banco operacional — primeiro passo da
v1.2.0 (Administração da Plataforma).

Até aqui, `app.engine.load_units()` lia `data/units.yaml` diretamente a cada
boot: criar ou editar uma unidade exigia editar o arquivo, commitar e fazer
deploy. Esta migração não muda esse arquivo nem o que ele significa para
quem já opera o sistema — ela só formaliza, no banco, os campos que definem
a IDENTIDADE de cada unidade (nome, contratante, ativo, início, qual
calculadora, qual template de relatório), preparando o terreno para a tela
de Administração da etapa seguinte, que ainda não existe.

Deliberadamente NÃO duplica parâmetro operacional nenhum (alíquota,
percentual, ponto de equilíbrio, despesas, faixas, splits, repasses,
custos) — isso já vive em `parametros_vigentes` desde a v1.0.0, via
`seed_parametros_from_yaml`/`_extrair_editaveis`, e continua exatamente
como está. Os blocos aninhados ainda não migrados para uma tabela própria
(splits do Pátio, faixas, custos_mensais/variaveis) continuam sendo lidos
do YAML por `app.engine.load_units()` como "shape legado" — isso é uma
limitação conhecida desta etapa, não um esquecimento: o editor dessas
listas é objeto da etapa seguinte (schemas dinâmicos por calculadora),
explicitamente fora do escopo daqui.

`tipo_relatorio` é persistido porque NÃO é derivável de `tipo_calculo` —
confirmado inspecionando as 23 unidades: COM_FAIXAS aparece com
tipo_relatorio "com_eventos" (Fiergs) e "padrao" (Monza, NL 2800, Ekos,
OKA); COM_ALIQUOTA_CUMUL aparece com "com_eventos" (ILP) e "padrao" (todas
as demais). Tratar como derivado perderia essa distinção real.

Não duplica a lógica de carga: reaproveita
`app.models.bootstrap_unidades_se_vazia`, a MESMA função que
`app.models.init_db()` já chama automaticamente sempre que a tabela
`unidades` está vazia — isso existe para que uma instalação nova nunca
fique com 0 unidades disponíveis entre o deploy e a execução manual desta
migração (ver docstring da própria função para o motivo). Esta migração
formaliza esse bootstrap como um passo auditável e versionado do histórico
de deploy — na prática, ao rodar `scripts/migrate.py` em produção, o
`run_all()` já chama `init_db()` antes de qualquer migration, então o
bootstrap normalmente já terá acontecido antes desta migration executar; a
função é segura de chamar de novo (só age se a tabela ainda estiver
vazia) e o log abaixo reflete isso.

`CREATE TABLE IF NOT EXISTS` aqui é defesa em profundidade — `init_db()` já
cria essa tabela — não custa nada e mantém esta migration self-contained
(auditável isoladamente, sem depender de ler outro arquivo para saber o
schema que ela pressupõe).

Idempotente: `bootstrap_unidades_se_vazia` só insere quando a tabela está
completamente vazia — nunca faz merge parcial nem sincroniza uma unidade
"faltante" se já houver qualquer linha (mesmo uma criada manualmente, sem
bloco YAML correspondente). Não altera nenhuma outra tabela.
"""
from app.models import bootstrap_unidades_se_vazia


def apply(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unidades (
            id             TEXT PRIMARY KEY,
            nome           TEXT NOT NULL,
            contratante    TEXT NOT NULL,
            ativo          INTEGER NOT NULL DEFAULT 1,
            inicio         TEXT NOT NULL,
            tipo_calculo   TEXT NOT NULL,
            tipo_relatorio TEXT NOT NULL DEFAULT 'padrao',
            criado_em      TEXT DEFAULT (datetime('now')),
            atualizado_em  TEXT DEFAULT (datetime('now'))
        )
    """)

    inseridas = bootstrap_unidades_se_vazia(conn)

    if inseridas:
        print(f"  migrar_unidades_para_banco: {inseridas} unidade(s) inserida(s) (bootstrap inicial).")
    else:
        total = conn.execute("SELECT COUNT(*) AS c FROM unidades").fetchone()["c"]
        print(f"  migrar_unidades_para_banco: nenhuma alteração — tabela já continha {total} "
              f"unidade(s) (bootstrap já havia rodado via init_db(), ou a tabela não estava vazia).")
