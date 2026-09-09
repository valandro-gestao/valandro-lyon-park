"""
Corrige o histórico legado (< 2026-06) de W Tower Caxias em `lancamentos`,
a partir de migrations/data/historico_wtower.json — gerado por
scripts/extrair_wtower.py a partir da planilha histórica original
("Lyon - Dados para Relatórios.xlsx", aba "W-Tower Caxias"). Esta migração
NUNCA lê o Excel diretamente — só o JSON já extraído e validado localmente
(ver docstring do script de extração para a resolução completa da
estrutura de colunas: totalizador de cada ano vem DEPOIS dos 12 meses que
resume, não antes — confirmação da operadora, set/2026).

Contexto: o histórico legado de W Tower (migrations 0002/0004) tem
`aluguel_calculado` errado em 28 das 53 competências 2022-01..2026-05, em
duas causas distintas — ambas já diagnosticadas e confirmadas pela
operadora:
  1. 17 meses (2022-03..2023-12): o bootstrap calculou repasse
     mês-a-mês (max(0, percentual × resultado)), ignorando que a unidade
     ainda estava em prejuízo acumulado real durante todo esse período —
     mesma causa-raiz já corrigida para Dom Pedro/MW Tristeza na migration
     0011 (mas W Tower ficou de fora dela — ver seu docstring: "W Tower não
     tem âncora oficial confirmada nem os valores mensais de
     fundo_recomposicao — fica de fora, aguardando esses dois dados").
     Agora esses dois dados existem, vindos da planilha.
  2. 11 meses (2024-06..2025-03): `aluguel_calculado` já é o valor BRUTO
     correto (Aluguel a Pagar), mas o Fundo de Recomposição contratual
     (717,38/mês) nunca foi descontado — o repasse líquido real (Saldo a
     Pagar) é menor.
  3. 1 mês (2024-01, mês de virada): repasse foi calculado sobre o
     resultado cheio (14208,60), não só sobre o excedente após quitar o
     prejuízo remanescente — o valor correto é 80% de 7340,64, não de
     14208,60.

`resultado` está correto em 100% das competências (nunca alterado por esta
migração). Também não são alterados: faturamento, subtotal, custos,
observações, status — só os campos explicitamente listados abaixo.

Reconstrução (determinística, sem aproximação — todo valor vem direto do
JSON, já validado célula-a-célula contra a planilha e contra a regra oficial
confirmada pela operadora):
  1. Carrega os lançamentos com 2022-01 <= mes_referencia <= 2026-05, em
     ordem cronológica. Nunca toca mes_referencia < 2022-01 (2021 permanece
     como está — a planilha não tem suporte direto para esses meses, essa é
     uma decisão deliberada, não uma lacuna a preencher) nem
     mes_referencia >= 2026-06 (cadeia real, ver app.models.
     CADEIA_SALDO_DESDE — já ignora todo lançamento legado).
  2. Valida ANTES de gravar qualquer coisa:
       a. toda competência no intervalo tem um registro correspondente no
          JSON (mesma contagem, mesmas competências, sem lacuna);
       b. o `resultado` já gravado em cada lançamento bate (meio centavo)
          com o `resultado` do JSON — confirma que estamos corrigindo a
          competência certa, nunca gravando por cima de um lançamento que
          não corresponde à mesma fonte;
       c. a cadeia de prejuízo do JSON tem exatamente um mês de virada
          (saída chega a 0 pela primeira vez) e é 2024-01;
       d. o JSON tem `extras.fundo_recomposicao` presente exatamente nos
          10 meses 2024-06..2025-03, e ausente em todos os outros.
     Se qualquer validação falhar, a migração inteira é abortada — nada é
     gravado.
  3. Só então aplica os UPDATEs — e só nos lançamentos cujo valor atual
     difere do valor-fonte (dentro da tolerância); uma competência já
     correta não é regravada.

Campos alterados por lançamento corrigido (dentro de `resultado_json`):
  - prejuizo_acumulado_entrada / prejuizo_acumulado_saida
  - aluguel_calculado (sempre o valor BRUTO — "Aluguel a Pagar" da
    planilha, a mesma semântica que o calculator ao vivo usa:
    app.calculators.cumulativo resolve `aluguel` como bruto e só DEPOIS
    calcula extras["saldo_a_pagar"] = aluguel - fundo_recomposicao)
  - extras["fundo_recomposicao"] (valor POSITIVO, 717.38 — convenção do
    sistema; a planilha grava a linha como negativo, o script de extração
    já inverte o sinal) e extras["saldo_a_pagar"] (valor líquido real, só
    presente nos 10 meses com Fundo — mesma condição em que o calculator ao
    vivo grava esses dois campos, ver cumulativo.py: só entra em `extras`
    quando fundo_recomposicao != 0). Fora desses 10 meses, nenhum dos dois
    campos é gravado em `extras` — mesmo comportamento que o calculator ao
    vivo teria produzido.
  Os demais campos de `extras` (nenhum, atualmente, para W Tower legado)
  são preservados via merge, nunca substituídos por um dict novo.

Verificação de que o calculator ao vivo NÃO precisa de alteração: já
implementa `Repasse bruto - Fundo de Recomposição = Repasse líquido`
exatamente (cumulativo.py: extras["saldo_a_pagar"] = round(aluguel -
fundo_recomposicao, 2)) — confirmado por leitura direta do código antes de
desenhar esta migração. Nenhum arquivo em app/calculators é tocado aqui.

Depois de corrigir `lancamentos`, reconstrói `historico_anual` — SÓ de
w_tower_caxias — a partir de TODOS os lançamentos da unidade (2021 em
diante, incluindo >= 2026-06 quando existir), com uma regra de agregação
DIFERENTE da genérica usada por 0006/0011/0012: o valor anual de "Repasse"
soma, mês a mês, `extras.saldo_a_pagar` quando presente (repasse líquido
real, já descontado o Fundo) e `aluguel_calculado` nos demais meses (onde
já é o valor líquido, por não ter Fundo). Usar `aluguel_calculado` puro
(como as demais migrações fazem) ignoraria o Fundo de Recomposição nos 10
meses em que ele existe — a operadora pediu explicitamente que o Histórico
Anual reflita o valor líquido efetivamente devido, não o bruto. Ajuste
propositalmente LOCAL a esta migração (não em app/reporter.py nem
app/relatorio.py): ambos já leem `historico_anual.dados_json
["aluguel_calculado"]` genericamente sob o rótulo "Repasse"/"Aluguel
Pago" — gravar o valor líquido nessa MESMA chave, só para w_tower_caxias,
é suficiente para corrigir a visão anual (UI e DOCX) sem tocar nenhum
código compartilhado com outras unidades.

Esta reconstrução SUPERA (supersedes) a correção manual feita pela
migration 0003 — que já havia corrigido `historico_anual.aluguel_calculado`
por ano, mas usando somas BRUTAS vindas de outra apuração (mapeamento de
coluna corrigido, sem envolver Fundo de Recomposição) e, para 2022/2023,
com valores incompatíveis com a regra agora confirmada pela operadora
("prejuízo acumulado permanece negativo até dezembro/2023" implica repasse
zero nesses dois anos — e é exatamente o que a planilha mostra na coluna
"Aluguel a Pagar" desses meses: 0 em todos eles). A migration 0003
permanece no histórico como está (nunca se reescreve uma migração já
aplicada); esta apenas grava um novo `dados_json` por cima, com os valores
agora corretos e completos.

Idempotente: cada execução recalcula tudo a partir do JSON + `lancamentos`
já corrigidos e só grava o que realmente difere (dentro da tolerância) —
uma segunda execução encontra 0 lançamentos a atualizar e recalcula
`historico_anual` para o mesmo resultado.

Não toca `parametros_vigentes`, `saldos_acumulados`, nem nenhuma outra
unidade. Não altera app/calculators/cumulativo.py nem app/reporter.py.
"""
import json
import os
from collections import defaultdict

CADEIA_SALDO_DESDE = "2026-06"
UNIDADE_ID = "w_tower_caxias"
MES_INICIO_ESCOPO = "2022-01"
MES_FIM_ESCOPO = "2026-05"
MES_VIRADA_ESPERADO = "2024-01"
FUNDO_MESES_ESPERADOS = {
    "2024-06", "2024-07", "2024-08", "2024-09", "2024-10", "2024-11", "2024-12",
    "2025-01", "2025-02", "2025-03",
}
TOLERANCIA = 0.005  # meio centavo

DADOS_PATH = os.path.join(os.path.dirname(__file__), "data", "historico_wtower.json")


def _carregar_e_validar_fonte():
    if not os.path.exists(DADOS_PATH):
        raise RuntimeError(
            f"Arquivo de dados não encontrado: {DADOS_PATH}. "
            "Gere-o com scripts/extrair_wtower.py antes de aplicar esta migração."
        )
    with open(DADOS_PATH, encoding="utf-8") as f:
        dados = json.load(f)
    registros = dados.get(UNIDADE_ID, [])
    por_mes = {r["mes_referencia"]: r for r in registros}

    erros = []
    if not registros:
        erros.append("historico_wtower.json não tem nenhum registro para w_tower_caxias.")
        return por_mes, erros

    competencias = sorted(por_mes)
    if competencias[0] != MES_INICIO_ESCOPO or competencias[-1] != MES_FIM_ESCOPO:
        erros.append(
            f"intervalo do JSON é {competencias[0]}..{competencias[-1]}, "
            f"esperado {MES_INICIO_ESCOPO}..{MES_FIM_ESCOPO}"
        )

    mes_virada = next(
        (m for m in competencias
         if por_mes[m]["prejuizo_acumulado_saida"] == 0.0
         and por_mes[m]["prejuizo_acumulado_entrada"] < 0.0),
        None,
    )
    if mes_virada != MES_VIRADA_ESPERADO:
        erros.append(f"mês de virada no JSON é {mes_virada!r}, esperado {MES_VIRADA_ESPERADO!r}")

    fundo_no_json = {m for m, r in por_mes.items() if "fundo_recomposicao" in r}
    if fundo_no_json != FUNDO_MESES_ESPERADOS:
        erros.append(
            f"meses com fundo_recomposicao no JSON: {sorted(fundo_no_json)}, "
            f"esperado exatamente: {sorted(FUNDO_MESES_ESPERADOS)}"
        )

    return por_mes, erros


def _corrigir_lancamentos(conn, por_mes: dict) -> int:
    linhas = conn.execute(
        "SELECT id, mes_referencia, resultado_json FROM lancamentos "
        "WHERE unidade_id=? AND mes_referencia >= ? AND mes_referencia <= ? "
        "ORDER BY mes_referencia",
        (UNIDADE_ID, MES_INICIO_ESCOPO, MES_FIM_ESCOPO),
    ).fetchall()

    if not linhas:
        print(f"  {UNIDADE_ID}: nenhum lançamento em {MES_INICIO_ESCOPO}..{MES_FIM_ESCOPO} encontrado — nada a fazer.")
        return 0

    erros = []
    if len(linhas) != len(por_mes):
        erros.append(f"{len(linhas)} lançamento(s) em {MES_INICIO_ESCOPO}..{MES_FIM_ESCOPO}, "
                      f"mas o JSON tem {len(por_mes)} competência(s) — divergência de cobertura.")

    for row in linhas:
        mes = row["mes_referencia"]
        if mes >= CADEIA_SALDO_DESDE:
            # Defensivo — o filtro SQL já garante isso, mas nunca confia
            # cegamente numa única camada de proteção contra tocar a cadeia real.
            erros.append(f"lançamento {mes} >= {CADEIA_SALDO_DESDE} apareceu na consulta filtrada — abortando.")
            continue
        if mes not in por_mes:
            erros.append(f"lançamento {mes} existe em `lancamentos` mas não tem registro correspondente no JSON.")
            continue
        atual = json.loads(row["resultado_json"])
        fonte = por_mes[mes]
        resultado_atual = atual.get("resultado")
        if resultado_atual is None or abs(resultado_atual - fonte["resultado"]) > TOLERANCIA:
            erros.append(
                f"{mes}: resultado já gravado ({resultado_atual!r}) não bate com o resultado do "
                f"JSON ({fonte['resultado']!r}) — pode ser a competência errada, abortando."
            )

    if erros:
        print(f"  {UNIDADE_ID}: {len(erros)} validação(ões) falharam, NADA foi gravado:")
        for e in erros:
            print(f"    - {e}")
        return 0

    atualizados, ja_corretos = 0, 0
    for row in linhas:
        mes = row["mes_referencia"]
        fonte = por_mes[mes]
        atual = json.loads(row["resultado_json"])

        extras_atual = dict(atual.get("extras") or {})
        extras_novo = dict(extras_atual)
        tem_fundo = mes in FUNDO_MESES_ESPERADOS
        if tem_fundo:
            extras_novo["fundo_recomposicao"] = fonte["fundo_recomposicao"]
            extras_novo["saldo_a_pagar"] = fonte["saldo_a_pagar"]
        else:
            extras_novo.pop("fundo_recomposicao", None)
            extras_novo.pop("saldo_a_pagar", None)

        entrada_atual = atual.get("prejuizo_acumulado_entrada")
        saida_atual = atual.get("prejuizo_acumulado_saida")
        aluguel_atual = atual.get("aluguel_calculado")

        ja_bate = (
            entrada_atual is not None and abs(entrada_atual - fonte["prejuizo_acumulado_entrada"]) < TOLERANCIA
            and saida_atual is not None and abs(saida_atual - fonte["prejuizo_acumulado_saida"]) < TOLERANCIA
            and aluguel_atual is not None and abs(aluguel_atual - fonte["aluguel_calculado"]) < TOLERANCIA
            and extras_atual == extras_novo
        )
        if ja_bate:
            ja_corretos += 1
            continue

        novo = dict(atual)
        novo["prejuizo_acumulado_entrada"] = fonte["prejuizo_acumulado_entrada"]
        novo["prejuizo_acumulado_saida"] = fonte["prejuizo_acumulado_saida"]
        novo["aluguel_calculado"] = fonte["aluguel_calculado"]
        novo["extras"] = extras_novo
        conn.execute(
            "UPDATE lancamentos SET resultado_json=? WHERE id=?",
            (json.dumps(novo, ensure_ascii=False), row["id"]),
        )
        atualizados += 1

    print(f"  {UNIDADE_ID}: {atualizados} lançamento(s) corrigido(s), {ja_corretos} já correto(s), "
          f"de {len(linhas)} no intervalo {MES_INICIO_ESCOPO}..{MES_FIM_ESCOPO}.")
    return atualizados


def _reconstruir_historico_anual_wtower(conn) -> None:
    """Agregação por ano do Histórico Anual de w_tower_caxias — variante da
    regra genérica de 0006/0011/0012: soma o repasse LÍQUIDO
    (extras.saldo_a_pagar quando presente, aluguel_calculado nos demais
    meses) na chave "aluguel_calculado" do agregado anual, para que a
    coluna "Repasse" (app.reporter._HISTORICO_ANUAL_COLUNAS) e "Aluguel
    Pago" (app.relatorio._montar_linhas_historico) já mostrem o valor
    líquido — ambos leem essa mesma chave, sem nenhuma outra mudança."""
    rows = conn.execute(
        "SELECT mes_referencia, resultado_json FROM lancamentos "
        "WHERE unidade_id=? ORDER BY mes_referencia",
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
        repasse_liquido = extras.get("saldo_a_pagar")
        if repasse_liquido is None:
            repasse_liquido = dados.get("aluguel_calculado") or 0.0

        anos[ano]["faturamento"] += dados.get("faturamento") or 0.0
        anos[ano]["resultado"] += dados.get("resultado") or 0.0
        anos[ano]["aluguel_calculado"] += repasse_liquido + repasse_outros
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

    print(f"  historico_anual recalculado para {UNIDADE_ID} (repasse líquido): {len(anos)} ano(s).")


def apply(conn):
    por_mes, erros = _carregar_e_validar_fonte()
    if erros:
        print(f"  {UNIDADE_ID}: {len(erros)} validação(ões) da fonte falharam, NADA foi gravado:")
        for e in erros:
            print(f"    - {e}")
        return

    atualizados = _corrigir_lancamentos(conn, por_mes)
    _reconstruir_historico_anual_wtower(conn)
