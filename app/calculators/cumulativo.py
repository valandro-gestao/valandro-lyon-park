"""
Calculadora COM_ALIQUOTA_CUMUL.

Suporta:
  - alíquota de imposto
  - ponto de equilíbrio (editável por mês via pe_override)
  - custos mensais fixos (condomínio, IPTU etc.)
  - prejuízo acumulado entre meses
  - faixas_aluguel (se configurado no YAML)
  - outras_despesas (dedução do RESULTADO — v1.2.0, junto de PE/custos_mensais,
    ANTES do resultado ser apurado; regra confirmada pela operadora para
    Viva Trindade, fechamento oficial de agosto/2026)
  - investimentos (dedução do RESULTADO já apurado, antes do prejuízo/repasse
    — v1.2.0, ver bloco abaixo; regra confirmada pela operadora para Viva
    Trindade)
  - fundo_recomposicao (dedução do ALUGUEL, depois do repasse — comportamento
    antigo, inalterado; usado só por W Tower, fora de escopo desta correção)
  - adicional_fixo (ex: parcelamento de equipamentos)

v1.2.0 — Investimentos (Viva Trindade): antes, `investimentos` era uma
dedução PÓS-repasse (aluguel calculado sobre o resultado cheio, depois
abatido por investimentos, virando "saldo_a_pagar") — igual ao que
`fundo_recomposicao` ainda faz. A operadora confirmou que isso está errado:
investimento precisa reduzir o resultado disponível ANTES de absorver ou
gerar prejuízo acumulado, e o repasse só pode incidir sobre o que sobrar
depois de prejuízo E investimento. Por isso `investimentos` agora entra na
composição de `resultado_com_prejuizo` (abaixo), e deixou de gerar
"saldo_a_pagar" — o valor de `aluguel_calculado` já sai líquido do
investimento. `fundo_recomposicao` (W Tower) NÃO foi alterado — continua na
regra antiga, pós-repasse — trata-se de um campo de W Tower, fora do
escopo desta correção (só Viva Trindade foi confirmada pela operadora).

v1.2.0 — Outras Despesas (Viva Trindade, confirmado após o fechamento
oficial de agosto/2026): categoria DIFERENTE de investimentos — a operadora
foi explícita que os dois conceitos coexistem, não se substituem.
`outras_despesas` entra ANTES de "Resultado" ser apurado, junto do Ponto de
Equilíbrio e dos custos mensais (condomínio, IPTU) — não depois, como
investimentos. Fórmula validada contra o fechamento oficial:
    resultado        = subtotal - PE - custos_mensais - outras_despesas
    disponivel        = resultado - investimentos + prejuizo_entrada
    disponivel <= 0   -> aluguel=0, prejuizo_saida=disponivel
    disponivel  > 0   -> aluguel=percentual/faixas(disponivel), prejuizo_saida=0
Campo reservado, resolvido via `custos_variaveis.outras_despesas`
(parametros_vigentes, versionado por competência — mesma infraestrutura já
usada por investimentos/fundo_recomposicao) — nunca aparece no editor
genérico de rubricas (custos_mensais).

Não suporta (removido, v1.2.0): taxa_admin_fixa como piso do repasse. Era
usada só por MW Tristeza (4350.0) e a operadora confirmou que era controle
da planilha antiga, sem correspondência na regra contratual real (repasse
= percentual_aluguel × resultado disponível após absorção do prejuízo
acumulado, sem piso). `taxa_admin_fixa` continua existindo para
PERCENTUAL_SIMPLES (Vasco) — semântica diferente (piso quando o resultado
NÃO supera o ponto de equilíbrio) — ver app.calculators.base.
"""
from app.models import ResultadoUnidade, get_saldo_entrada
from app.rubricas import custos_com_overrides, ids_normalizados


def calcular_com_aliquota_cumul(cfg: dict, mes: str, faturamento: float,
                                 saldo_override: float = None,
                                 custos_extras: dict = None,
                                 pe_override: float = None,
                                 **kwargs) -> ResultadoUnidade:
    pe = pe_override if pe_override is not None else cfg.get("ponto_equilibrio", 0.0)
    aliq = cfg.get("aliquota_imposto", 0.0)
    pct = cfg.get("percentual_aluguel", 0.0)
    adicional = cfg.get("adicional_fixo", 0.0) or 0.0

    # v1.2.0: entrada resolvida pela cadeia real de fechamentos (saída do
    # último aprovado anterior, com fallback à âncora explícita da
    # unidade) — nunca mais pelo valor único e corrente de
    # saldos_acumulados (app.models.get_saldo_acumulado), que não sabe a
    # qual competência pertence. saldo_override continua tendo prioridade
    # máxima, para testes e correções explícitas (ex.: futura correção de
    # IPCA de abril).
    if saldo_override is not None:
        prejuizo_entrada = saldo_override
    else:
        prejuizo_entrada = get_saldo_entrada(cfg["id"], mes)

    # Faturamento pode incluir carregadores (passado em custos_extras)
    fat_carregadores = float((custos_extras or {}).get("fat_carregadores", 0.0))
    faturamento_total = faturamento + fat_carregadores

    subtotal = round(faturamento_total * (1 - aliq), 2)

    # Custos mensais fixos (condomínio, IPTU, etc.) — normalizado via
    # app.rubricas, aceita dict legado ou lista nova indistintamente.
    custos = dict(custos_com_overrides(cfg.get("custos_mensais"), custos_extras))
    # Custos extras que não são campos fixos (eventos, etc.)
    _nao_custo = {"fat_carregadores", "investimentos", "fundo_recomposicao",
                  "outras_despesas", "ponto_equilibrio_override"}
    _ids_rubricas = ids_normalizados(cfg.get("custos_mensais"))
    for k, v in (custos_extras or {}).items():
        if k not in custos and k not in _ids_rubricas and k not in _nao_custo and v:
            custos[k] = float(v)
    total_custos = sum(custos.values())

    # v1.2.0: outras_despesas reduz o resultado JUNTO do PE/custos_mensais —
    # ANTES de "Resultado" ser apurado (ver docstring do módulo). Resolução
    # no mesmo padrão de investimentos/fundo_recomposicao: custos_extras
    # (entrada por cálculo) tem prioridade sobre o valor vigente em
    # cfg["custos_variaveis"] (parametros_vigentes, versionado por
    # competência).
    outras_despesas = float((custos_extras or {}).get("outras_despesas", 0.0))
    if outras_despesas == 0.0:
        outras_despesas = float((cfg.get("custos_variaveis") or {}).get("outras_despesas", 0.0))

    resultado_bruto = subtotal - pe - total_custos - outras_despesas

    # v1.2.0: investimentos reduz o resultado ANTES do prejuízo/repasse (ver
    # docstring do módulo — regra confirmada pela operadora para Viva
    # Trindade). Resolução idêntica à anterior: custos_extras (entrada por
    # cálculo) tem prioridade sobre o valor vigente em
    # cfg["custos_variaveis"] (parametros_vigentes, versionado por
    # competência via app.models.salvar_parametros).
    investimento = float((custos_extras or {}).get("investimentos", 0.0))
    if investimento == 0.0:
        investimento = float((cfg.get("custos_variaveis") or {}).get("investimentos", 0.0))

    disponivel = resultado_bruto - investimento
    resultado_com_prejuizo = disponivel + prejuizo_entrada  # prejuizo é negativo

    # Aluguel: por faixas ou percentual simples
    faixas_aluguel = cfg.get("faixas_aluguel")
    if resultado_com_prejuizo > 0:
        if faixas_aluguel:
            aluguel = _aplicar_faixas(resultado_com_prejuizo, faixas_aluguel)
        else:
            aluguel = round(resultado_com_prejuizo * pct, 2)
        prejuizo_saida = 0.0
    else:
        aluguel = 0.0
        # já reflete o investimento absorvido, quando o resultado não é
        # suficiente para cobri-lo (aumenta o prejuízo acumulado — regra
        # confirmada pela operadora).
        prejuizo_saida = round(resultado_com_prejuizo, 2)

    extras: dict = {}
    if outras_despesas:
        # Só informativo (mostrado no PDF antes de "Resultado", junto do
        # PE/custos — ver app.reporter._prestacao_padrao). O valor já foi
        # descontado de resultado_bruto, acima.
        extras["outras_despesas"] = outras_despesas
    if investimento:
        # Só informativo (mostrado no PDF antes do Prejuízo Acumulado — ver
        # app.reporter._prestacao_padrao). Não gera mais "saldo_a_pagar":
        # o repasse já sai líquido do investimento, calculado acima.
        extras["investimentos"] = investimento
    if adicional:
        extras["adicional_fixo"] = adicional
        aluguel = round(aluguel + adicional, 2)
    if fat_carregadores:
        extras["fat_carregadores"] = fat_carregadores

    # Dedução PÓS-repasse — comportamento antigo, inalterado. Só
    # fundo_recomposicao (W Tower) ainda usa este caminho; investimentos
    # (Viva Trindade) foi movido para antes do prejuízo/repasse, acima.
    fundo_recomposicao = float((custos_extras or {}).get("fundo_recomposicao", 0.0))
    if fundo_recomposicao == 0.0:
        fundo_recomposicao = float((cfg.get("custos_variaveis") or {}).get("fundo_recomposicao", 0.0))
    if fundo_recomposicao:
        extras["fundo_recomposicao"] = fundo_recomposicao
        extras["saldo_a_pagar"] = round(aluguel - fundo_recomposicao, 2)

    return ResultadoUnidade(
        unidade_id=cfg["id"],
        mes_referencia=mes,
        faturamento=faturamento_total,
        aliquota_imposto=aliq,
        subtotal=subtotal,
        ponto_equilibrio=pe,
        custos=custos,
        resultado=round(resultado_bruto, 2),
        prejuizo_acumulado_entrada=prejuizo_entrada,
        prejuizo_acumulado_saida=prejuizo_saida,
        aluguel_calculado=aluguel,
        extras=extras,
    )


def _aplicar_faixas(base: float, faixas: list) -> float:
    aluguel = 0.0
    saldo = base
    for faixa in faixas:
        if saldo <= 0:
            break
        limite = faixa.get("ate")
        pct = faixa["percentual"]
        if limite is None:
            aluguel += saldo * pct
        else:
            parcela = min(saldo, limite)
            aluguel += parcela * pct
            saldo -= parcela
    return round(aluguel, 2)
