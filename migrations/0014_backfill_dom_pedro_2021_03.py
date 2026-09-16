"""
Backfill defensivo de dom_pedro/2021-03 em `lancamentos` — homologação
set/2026, ponto 1 (revisado após investigação adicional).

Causa raiz: março/2021 EXISTE na planilha histórica original ("Lyon -
Dados para Relatórios.xlsx", aba "Dom Pedro", linha 6) — Faturamento=0,00,
Resultado=-9950,00 (= -PE, com Subtotal=0 — mesma fórmula usada em todos
os outros meses da mesma coluna). A linha foi descartada do bootstrap
original por scripts/extrair_historico_lancamentos.py: seu filtro
`if fat is None or fat == 0: continue` trata "faturamento zero" e
"faturamento ausente" como a mesma coisa — nenhum outro mês de Dom Pedro
em 2021 tem faturamento zero, então este foi o único mês afetado por essa
confusão (ver correção/documentação dessa regra na própria docstring do
script de extração, revisada junto com esta migração).

Decisão de arquitetura (revisão explícita da operadora): NÃO introduz
nenhuma tabela nem caminho de leitura especial. `lancamentos` continua
sendo a única fonte mensal e `historico_anual` continua sendo,
exclusivamente, um agregado derivado dela (mesma regra genérica já usada
por 0006/0011/0012/0013) — nenhuma precedência nem exceção em
app.models.get_historico_anual(). Com este único lançamento restaurado,
o agregado de 2021 fecha sozinho, sem nenhum caso especial:
    12 competências, Faturamento 18299,24, Resultado -104089,03
    (bate exato com o valor confirmado pela operadora), Repasse 0,00,
    quantidade_meses=12 (rótulo "2021", sem "(11 meses)" —
    app.reporter._formatar_ano_label: >=12 meses não leva parênteses).

Campos gravados: faturamento/resultado vêm direto da planilha; custos, na
MESMA convenção minimalista do bootstrap original (migration 0002):
scripts/extrair_historico_lancamentos.py só extrai faturamento/resultado/
aluguel_calculado da planilha para "abas mês em linha" como Dom Pedro —
aliquota_imposto/subtotal/ponto_equilibrio/custos NUNCA foram carregados
da planilha para nenhum mês de Dom Pedro (ficam 0.0/{} em todo o
histórico, mesmo a planilha tendo Alíquota Fixa e PE preenchidos em toda
linha) — não seria consistente inventar esses valores só para março.

`prejuizo_acumulado_entrada/saida` é diferente: a planilha de Dom Pedro
NUNCA teve uma coluna própria de saldo acumulado (ao contrário de W
Tower) — em TODO o histórico da unidade, esses dois campos sempre foram
puramente derivados da cadeia mensal, nunca lidos de fonte alguma (ver
migration 0011: reconstrói a cadeia inteira andando retroativamente a
partir da âncora oficial de maio/2026). "Preservar a convenção do
histórico" aqui significa continuar essa MESMA derivação, não repetir o
placeholder 0.0/0.0 que a migration 0002 usava só porque, na época, a
cadeia real ainda não existia para NINGUÉM — gravar 0.0/0.0 hoje, com a
cadeia de todos os meses vizinhos já reconstruída pela 0011, quebraria a
identidade `entrada + resultado = saída` bem no meio da série, exatamente
o tipo de inconsistência que a 0011 evitou para todos os outros meses.

Por isso: `prejuizo_acumulado_entrada` de março/2021 é lido diretamente
da SAÍDA já gravada em fevereiro/2021 (o mês imediatamente anterior,
cadeia já corrigida pela migration 0011 — nunca recalculada, só lida) e
`prejuizo_acumulado_saida` = entrada + resultado de março (mesma
identidade usada em toda a cadeia). Isso preserva a identidade de março
consigo mesmo e a continuidade com fevereiro. A migration 0011 já tinha
rodado (sem saber de março) e fixou a entrada de abril/2021 como igual à
saída de fevereiro/2021 (o "salto" que ela documentou) — inserir março
agora, sem retroceder e recalcular abril em diante, deixa uma
descontinuidade cosmética conhecida e documentada entre a saída de março
(recém-calculada) e a entrada de abril (já fixada por 0011), de
exatamente -9950,00 (o resultado de março). Nenhum lançamento anterior a
CADEIA_SALDO_DESDE ("2026-06") alimenta a cadeia real de cálculo (ver
app.models.get_saldo_entrada) — sem efeito funcional algum. Uma
reconciliação completa da cadeia de prejuízo de Dom Pedro recalculando
abril/2021 em diante, se um dia for necessária, é trabalho separado, fora
do escopo desta correção pontual (que só restaura o lançamento que
faltava).

Comportamento (mesmo padrão defensivo da migration 0012):
  - só insere (dom_pedro, 2021-03) se a competência ainda não existir em
    `lancamentos`, e só se fevereiro/2021 já existir (fonte da entrada
    por continuidade) — sem fevereiro, aborta sem gravar nada;
  - se já existir, COMPARA faturamento/resultado contra os valores da
    planilha (0,00 / -9950,00) e reporta "já existe — igual" ou "já
    existe — DIVERGENTE" — nunca sobrescreve;
  - depois (inserindo ou não), reconstrói `historico_anual` — só de
    dom_pedro — a partir de TODOS os lançamentos já existentes da
    unidade, mesma regra de agregação de 0006/0011/0012/0013.

Idempotente: uma segunda execução encontra a competência já inserida e
conferida ("já existe — igual") e não grava nada novo em `lancamentos`;
`historico_anual` é recalculado para o mesmo resultado.

Não toca nenhuma outra competência, nenhuma outra unidade,
`parametros_vigentes` nem `saldos_acumulados`.
"""
import json
from collections import defaultdict

UNIDADE_ID = "dom_pedro"
MES_ANTERIOR = "2021-02"
MES_REFERENCIA = "2021-03"
TOLERANCIA = 0.005  # meio centavo

FATURAMENTO_OFICIAL = 0.00
RESULTADO_OFICIAL = -9950.00


def _inserir_lancamento(conn) -> None:
    row = conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
        (UNIDADE_ID, MES_REFERENCIA),
    ).fetchone()

    if row is not None:
        atual = json.loads(row["resultado_json"])
        diverge = (
            atual.get("faturamento") is None or abs(atual["faturamento"] - FATURAMENTO_OFICIAL) > TOLERANCIA
            or atual.get("resultado") is None or abs(atual["resultado"] - RESULTADO_OFICIAL) > TOLERANCIA
        )
        if diverge:
            print(f"  backfill_dom_pedro_2021_03: {MES_REFERENCIA} já existe com valor DIVERGENTE "
                  f"(banco: faturamento={atual.get('faturamento')!r} resultado={atual.get('resultado')!r}; "
                  f"planilha: faturamento={FATURAMENTO_OFICIAL!r} resultado={RESULTADO_OFICIAL!r}) — "
                  "NÃO sobrescrito, decisão manual necessária.")
        else:
            print(f"  backfill_dom_pedro_2021_03: {MES_REFERENCIA} já existe e confere com a planilha "
                  "— nada a fazer.")
        return

    row_anterior = conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
        (UNIDADE_ID, MES_ANTERIOR),
    ).fetchone()
    if row_anterior is None:
        print(f"  backfill_dom_pedro_2021_03: {MES_ANTERIOR} não encontrado — não há como "
              f"determinar a entrada de prejuízo por continuidade. NADA foi gravado.")
        return
    entrada = json.loads(row_anterior["resultado_json"]).get("prejuizo_acumulado_saida")
    if entrada is None:
        print(f"  backfill_dom_pedro_2021_03: {MES_ANTERIOR} não tem prejuizo_acumulado_saida — "
              f"NADA foi gravado.")
        return
    saida = round(entrada + RESULTADO_OFICIAL, 2)

    resultado_dict = {
        "unidade_id": UNIDADE_ID,
        "mes_referencia": MES_REFERENCIA,
        "faturamento": FATURAMENTO_OFICIAL,
        "aliquota_imposto": 0.0,
        "subtotal": 0.0,
        "ponto_equilibrio": 0.0,
        "custos": {},
        "resultado": RESULTADO_OFICIAL,
        "prejuizo_acumulado_entrada": entrada,
        "prejuizo_acumulado_saida": saida,
        "aluguel_calculado": 0.0,
        "splits": {},
        "extras": {},
        "observacoes": (
            "Restaurado do histórico anterior ao Lyon Reports (planilha "
            "\"Dados para Relatórios\", aba \"Dom Pedro\") — competência ausente do "
            "bootstrap original (migration 0002) por ter Faturamento=0,00 na planilha, "
            "que scripts/extrair_historico_lancamentos.py descartava incorretamente "
            "como \"sem dado\" (ver migration 0014)."
        ),
        "status": "aprovado",
    }
    conn.execute(
        "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (UNIDADE_ID, MES_REFERENCIA, FATURAMENTO_OFICIAL,
         json.dumps(resultado_dict, ensure_ascii=False), "aprovado"),
    )
    print(f"  backfill_dom_pedro_2021_03: {MES_REFERENCIA} inserido "
          f"(faturamento={FATURAMENTO_OFICIAL}, resultado={RESULTADO_OFICIAL}, "
          f"prejuizo_acumulado_entrada={entrada}, prejuizo_acumulado_saida={saida}).")


def _reconstruir_historico_anual_dom_pedro(conn) -> None:
    """Mesma regra de agregação de migrations 0006/0011/0012/0013 — escopada
    só a dom_pedro, nunca toca o historico_anual de outra unidade."""
    rows = conn.execute(
        "SELECT mes_referencia, resultado_json FROM lancamentos WHERE unidade_id=? ORDER BY mes_referencia",
        (UNIDADE_ID,),
    ).fetchall()
    if not rows:
        return

    anos = defaultdict(lambda: {
        "faturamento": 0.0, "resultado": 0.0, "aluguel_calculado": 0.0,
        "quantidade_meses": 0,
    })
    for r in rows:
        dados = json.loads(r["resultado_json"])
        ano = int(r["mes_referencia"].split("-")[0])
        extras = dados.get("extras") or {}
        repasse_outros = extras.get("repasse_outros") or 0.0

        anos[ano]["faturamento"] += dados.get("faturamento") or 0.0
        anos[ano]["resultado"] += dados.get("resultado") or 0.0
        anos[ano]["aluguel_calculado"] += (dados.get("aluguel_calculado") or 0.0) + repasse_outros
        anos[ano]["quantidade_meses"] += 1

    for ano in sorted(anos):
        agregado = anos[ano]
        agregado["faturamento"] = round(agregado["faturamento"], 2)
        agregado["resultado"] = round(agregado["resultado"], 2)
        agregado["aluguel_calculado"] = round(agregado["aluguel_calculado"], 2)
        conn.execute("""
            INSERT INTO historico_anual (unidade_id, ano, dados_json)
            VALUES (?, ?, ?)
            ON CONFLICT(unidade_id, ano)
            DO UPDATE SET dados_json=excluded.dados_json
        """, (UNIDADE_ID, ano, json.dumps(agregado, ensure_ascii=False)))

    print(f"  historico_anual recalculado para {UNIDADE_ID}: {len(anos)} ano(s).")


def apply(conn):
    _inserir_lancamento(conn)
    _reconstruir_historico_anual_dom_pedro(conn)
