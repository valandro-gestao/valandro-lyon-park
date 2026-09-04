"""
Calculadora COM_ALIQUOTA_CUMUL.

Suporta:
  - alíquota de imposto
  - ponto de equilíbrio (editável por mês via pe_override)
  - custos mensais fixos (condomínio, IPTU etc.)
  - prejuízo acumulado entre meses
  - faixas_aluguel (se configurado no YAML)
  - investimentos (dedução do aluguel → saldo_a_pagar)
  - adicional_fixo (ex: parcelamento de equipamentos)

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
                  "ponto_equilibrio_override"}
    _ids_rubricas = ids_normalizados(cfg.get("custos_mensais"))
    for k, v in (custos_extras or {}).items():
        if k not in custos and k not in _ids_rubricas and k not in _nao_custo and v:
            custos[k] = float(v)
    total_custos = sum(custos.values())

    resultado_bruto = subtotal - pe - total_custos
    resultado_com_prejuizo = resultado_bruto + prejuizo_entrada  # prejuizo é negativo

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
        prejuizo_saida = round(resultado_com_prejuizo, 2)

    extras: dict = {}
    if adicional:
        extras["adicional_fixo"] = adicional
        aluguel = round(aluguel + adicional, 2)
    if fat_carregadores:
        extras["fat_carregadores"] = fat_carregadores

    # Deduções do aluguel → Saldo a Pagar (investimentos ou fundo_recomposicao)
    for campo in ("investimentos", "fundo_recomposicao"):
        val = float((custos_extras or {}).get(campo, 0.0))
        if val == 0.0:
            val = float((cfg.get("custos_variaveis") or {}).get(campo, 0.0))
        if val:
            extras[campo] = val
            extras["saldo_a_pagar"] = round(aluguel - val, 2)
            break

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
