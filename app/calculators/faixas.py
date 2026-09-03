"""
Calculadora COM_FAIXAS — Fiergs, Monza e similares.

Fluxo Fiergs:
  subtotal = fat - fat*aliq - base_taxa_cob*taxa_cob
  resultado = subtotal - PE - custos_variaveis
  aluguel   = faixas sobre resultado

Fluxo Monza (sem aliq, sem taxa_cob, sem PE, sem custos):
  resultado = faturamento
  aluguel   = faixas sobre resultado
"""
from app.models import ResultadoUnidade
from app.rubricas import custos_com_overrides, ids_normalizados


def calcular_com_faixas(cfg: dict, mes: str, faturamento: float,
                         custos_extras: dict = None,
                         pe_override: float = None,
                         **kwargs) -> ResultadoUnidade:
    aliq = cfg.get("aliquota_imposto", 0.0)
    taxa_cob_pct = cfg.get("taxa_cobranca", 0.0)
    pe = pe_override if pe_override is not None else cfg.get("ponto_equilibrio", 0.0)
    faixas = cfg["faixas"]

    # Receita de Selos (Fiergs): soma-se ao faturamento antes do restante do
    # cálculo. Mantida separada em `extras` para a memória de cálculo exibir
    # a composição explícita (Faturamento + Receita de Selos = Receita Bruta),
    # em vez de somar silenciosamente.
    receita_selos = float((custos_extras or {}).get("receita_selos", 0.0))
    receita_bruta = round(faturamento + receita_selos, 2)

    # Base de cálculo da taxa de cobrança: pode ser um campo separado ou a receita bruta
    base_taxa_cob = float((custos_extras or {}).get("base_calculo_taxa_cobranca", receita_bruta))
    taxa_cob_valor = round(base_taxa_cob * taxa_cob_pct, 2)

    subtotal = round(receita_bruta * (1 - aliq) - taxa_cob_valor, 2)

    # Custos mensais fixos (condomínio, IPTU, energia — ex: Ekos, OKA) e
    # variáveis (sistema_perto etc.) — normalizados via app.rubricas, aceita
    # tanto dict legado quanto lista nova sem este módulo saber a diferença.
    custos = dict(custos_com_overrides(cfg.get("custos_mensais"), custos_extras))
    custos.update(custos_com_overrides(cfg.get("custos_variaveis"), custos_extras))
    # Custos extras dinâmicos (eventos etc.) — nunca estiveram em cfg
    _excluir = {"base_calculo_taxa_cobranca", "ponto_equilibrio_override", "receita_selos"}
    _ids_rubricas = ids_normalizados(cfg.get("custos_mensais"), cfg.get("custos_variaveis"))
    for k, v in (custos_extras or {}).items():
        if k not in custos and k not in _ids_rubricas and k not in _excluir and v:
            custos[k] = float(v)
    total_custos = sum(custos.values())

    resultado = round(subtotal - pe - total_custos, 2)

    # Aplicar faixas sobre resultado
    aluguel = 0.0
    saldo = resultado
    faixas_detalhe = []
    for i, faixa in enumerate(faixas):
        if saldo <= 0:
            faixas_detalhe.append({"percentual": faixa["percentual"], "base": 0.0, "aluguel": 0.0})
            continue
        limite = faixa.get("ate")
        pct = faixa["percentual"]
        if limite is None:
            parcela = saldo
            aluguel += round(parcela * pct, 2)
            saldo = 0
        else:
            parcela = min(saldo, limite)
            aluguel += round(parcela * pct, 2)
            saldo -= parcela
        faixas_detalhe.append({"percentual": pct, "base": parcela, "aluguel": round(parcela * pct, 2)})

    extras = {
        "taxa_cobranca": taxa_cob_pct,
        "base_taxa_cobranca": base_taxa_cob,
        "taxa_cobranca_valor": taxa_cob_valor,
        "faixas_detalhe": faixas_detalhe,
    }
    if receita_selos:
        extras["receita_selos"] = receita_selos

    return ResultadoUnidade(
        unidade_id=cfg["id"],
        mes_referencia=mes,
        faturamento=receita_bruta,
        aliquota_imposto=aliq,
        subtotal=subtotal,
        ponto_equilibrio=pe,
        custos=custos,
        resultado=resultado,
        aluguel_calculado=round(aluguel, 2),
        extras=extras,
    )
