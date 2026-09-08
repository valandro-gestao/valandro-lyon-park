"""
Backfill do histórico legado (< 2026-06) de Pátio Manutenções, a partir de
migrations/data/historico_patio_manutencao.json — gerado por
scripts/extrair_patio_manutencao.py a partir da planilha histórica original
("Lyon - Dados para Relatórios.xlsx", aba "Patio Manutenção"). Esta
migração NUNCA lê o Excel diretamente — só o JSON já extraído e validado
localmente (ver docstring do script de extração para a resolução temporal
completa: os rótulos de ano da aba estavam defasados em 1 ano; a correção
foi validada contra a âncora oficial de maio/2026, -42223.85, e contra a
continuidade interna do Saldo Acumulado mês a mês — 38 competências,
2023-04 a 2026-05, sem lacuna, sem duplicata).

Contexto: Pátio Manutenções nunca teve histórico legado no sistema — está
ausente tanto de migrations/data/historico_lancamentos.json (bootstrap
0002) quanto de historico_lancamentos_2026_05.json (backfill 0004), porque
scripts/extrair_historico_lancamentos.py nunca incluiu essa unidade em
nenhum dos seus mapeamentos (não foi bug nem exclusão deliberada — só
nunca entrou no escopo original). A operadora confirmou que o histórico
existe na planilha "Dados para Relatórios" e deve ser recuperado.

Comportamento:
  - Só processa competências < 2026-06 (a cadeia real do sistema começa em
    2026-06 — ver app.models.CADEIA_SALDO_DESDE — e junho/2026 já existe
    como lançamento real aprovado; esta migração nunca toca nele nem em
    qualquer competência posterior, mesmo que o JSON de origem viesse a
    conter alguma por engano — o filtro é aplicado aqui, defensivamente,
    além do próprio corte que a extração já respeitou).
  - NUNCA sobrescreve um lançamento existente. Para cada competência do
    JSON: se (patio_manutencao, mes_referencia) já existir em
    `lancamentos`, compara faturamento/resultado/saldo acumulado contra o
    valor já gravado e só REPORTA "já existe — igual" ou "já existe —
    DIVERGENTE" (com os dois valores, para decisão manual) — nunca grava
    por cima. Só insere quando a competência ainda não existe.
  - `aluguel_calculado` é gravado como 0.0 para todo mês backfilled — nunca
    inventa um valor de repasse: PATIO_MANUTENCAO não tem esse conceito
    (confirmado pela operadora; a tela e o PDF já escondem esse campo para
    esta unidade — ver correções anteriores em app.reporter/app.ui.
    fechamento). Isso difere deliberadamente do calculator ao vivo
    (app.calculators.patio_manutencao), que grava aluguel_calculado =
    resultado como valor técnico de preenchimento — aqui, para o
    histórico reconstruído a partir de uma fonte externa, 0.0 é o valor
    mais neutro e não presume nada sobre repasse.
  - `prejuizo_acumulado_entrada`/`prejuizo_acumulado_saida` são
    preenchidos de forma coerente com o Saldo Acumulado da planilha:
    saida = saldo_acumulado do mês (valor direto da planilha); entrada =
    saida - resultado do mês (mesma relação que
    app.calculators.patio_manutencao usa ao vivo: saldo_acumulado =
    saldo_anterior + resultado).
  - Depois de inserir os lançamentos, reconstrói `historico_anual` — SÓ de
    patio_manutencao — a partir de TODOS os lançamentos da unidade agora
    em `lancamentos` (backfill + o real de junho/2026 em diante, se já
    existir), com a MESMA regra de agregação já usada pelas migrations
    0006 e 0011 (soma por ano de faturamento/resultado/
    aluguel_calculado+repasse_outros, contagem de meses). Nenhuma outra
    unidade tem seu historico_anual tocado.

Idempotente: uma segunda execução encontra todas as competências já
inseridas (reporta "já existe — igual" para cada uma, já que os valores
batem com o que ela mesma gravou) e não insere nada novo; `historico_anual`
é recalculado com o mesmo resultado (upsert determinístico, mesmo padrão
das migrations 0006/0011).

Não toca `parametros_vigentes`, `saldos_acumulados`, nem nenhuma outra
unidade.
"""
import json
import os
from collections import defaultdict

CADEIA_SALDO_DESDE = "2026-06"
UNIDADE_ID = "patio_manutencao"
TOLERANCIA = 0.005  # meio centavo

DADOS_PATH = os.path.join(os.path.dirname(__file__), "data", "historico_patio_manutencao.json")


def _inserir_lancamentos(conn) -> None:
    if not os.path.exists(DADOS_PATH):
        raise RuntimeError(
            f"Arquivo de dados não encontrado: {DADOS_PATH}. "
            "Gere-o com scripts/extrair_patio_manutencao.py antes de aplicar esta migração."
        )
    with open(DADOS_PATH, encoding="utf-8") as f:
        dados = json.load(f)
    registros = dados.get(UNIDADE_ID, [])

    # Entrada de cada mês = saída (Saldo Acumulado da própria planilha,
    # fonte de verdade) MENOS o resultado do mês — recalculada por
    # registro, não encadeada a partir do mês anterior. Isso garante que a
    # identidade contábil de CADA lançamento (entrada + resultado = saída)
    # feche exatamente, sempre — a propriedade que mais importa para
    # auditoria de um lançamento isolado. O preço é que a saída de um mês
    # pode diferir em ±0,01 da entrada calculada do mês seguinte, porque
    # cada célula "Saldo Acumulado" da planilha já vem arredondada a 2
    # casas independentemente (Excel soma em precisão total internamente,
    # só exibe/arredonda por célula — ver scripts/extrair_patio_manutencao.py,
    # que precisou do mesmo cuidado para validar a continuidade). Essa
    # diferença de centavo entre meses é cosmética e sem efeito funcional:
    # nenhum destes lançamentos alimenta a cadeia real de cálculo
    # (app.models.get_saldo_entrada ignora tudo antes de
    # CADEIA_SALDO_DESDE = "2026-06").
    for r in registros:
        r["_entrada_calculada"] = round(r["saldo_acumulado"] - r["resultado"], 2)

    existentes = {
        row["mes_referencia"]
        for row in conn.execute(
            "SELECT mes_referencia FROM lancamentos WHERE unidade_id=?", (UNIDADE_ID,)
        ).fetchall()
    }

    inseridos, ja_iguais, divergentes = [], [], []

    for r in registros:
        mes = r["mes_referencia"]
        if mes >= CADEIA_SALDO_DESDE:
            # Defensivo — o JSON de origem já só contém < 2026-06, mas esta
            # migração nunca confia cegamente no arquivo para essa garantia.
            continue

        if mes in existentes:
            row = conn.execute(
                "SELECT resultado_json FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
                (UNIDADE_ID, mes),
            ).fetchone()
            atual = json.loads(row["resultado_json"])
            saida_atual = atual.get("prejuizo_acumulado_saida")
            diverge = (
                atual.get("faturamento") is None or abs(atual["faturamento"] - r["faturamento"]) > TOLERANCIA
                or atual.get("resultado") is None or abs(atual["resultado"] - r["resultado"]) > TOLERANCIA
                or saida_atual is None or abs(saida_atual - r["saldo_acumulado"]) > TOLERANCIA
            )
            if diverge:
                divergentes.append((mes, atual.get("faturamento"), r["faturamento"],
                                     atual.get("resultado"), r["resultado"],
                                     saida_atual, r["saldo_acumulado"]))
            else:
                ja_iguais.append(mes)
            continue

        saida = r["saldo_acumulado"]
        entrada = r["_entrada_calculada"]
        resultado_dict = {
            "unidade_id": UNIDADE_ID,
            "mes_referencia": mes,
            "faturamento": r["faturamento"],
            "aliquota_imposto": 0.05,
            "subtotal": r["total_liquido"],
            "ponto_equilibrio": 0.0,
            "custos": dict(r["custos"]),
            "resultado": r["resultado"],
            "prejuizo_acumulado_entrada": entrada,
            "prejuizo_acumulado_saida": saida,
            "aluguel_calculado": 0.0,
            "splits": {},
            "extras": {"retencao_iss": r["retencao_iss"], "saldo_acumulado": saida},
            "observacoes": ("Restaurado do histórico anterior ao Lyon Reports "
                             "(planilha \"Dados para Relatórios\", aba \"Patio Manutenção\")."),
            "status": "aprovado",
        }
        conn.execute(
            "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (UNIDADE_ID, mes, r["faturamento"], json.dumps(resultado_dict, ensure_ascii=False), "aprovado"),
        )
        inseridos.append(mes)

    print(f"  backfill_historico_patio_manutencao: {len(inseridos)} competência(s) inserida(s), "
          f"{len(ja_iguais)} já existente(s) e conferida(s) sem divergência, "
          f"{len(divergentes)} divergente(s).")
    if inseridos:
        print(f"    inseridas: {inseridos[0]} -> {inseridos[-1]} ({len(inseridos)})")
    if divergentes:
        print("  ATENÇÃO — competência(s) já existente(s) com valor DIVERGENTE do extraído "
              "(NÃO sobrescrito(s), decisão manual necessária):")
        for mes, fat_atual, fat_novo, res_atual, res_novo, saida_atual, saida_novo in divergentes:
            print(f"    {mes}: faturamento banco={fat_atual!r} planilha={fat_novo!r} | "
                  f"resultado banco={res_atual!r} planilha={res_novo!r} | "
                  f"saldo_acumulado banco={saida_atual!r} planilha={saida_novo!r}")


def _reconstruir_historico_anual_unidade(conn) -> None:
    """Mesma regra de agregação de migrations/0006 e 0011 — escopada só a
    patio_manutencao, nunca toca o historico_anual de outra unidade."""
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
    _inserir_lancamentos(conn)
    _reconstruir_historico_anual_unidade(conn)
