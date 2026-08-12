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


def calcular_com_faixas(cfg: dict, mes: str, faturamento: float,
                         custos_extras: dict = None,
                         pe_override: float = None,
                         **kwargs) -> ResultadoUnidade:
    aliq = cfg.get("aliquota_imposto", 0.0)
    taxa_cob_pct = cfg.get("taxa_cobranca", 0.0)
    pe = pe_override if pe_override is not None else cfg.get("ponto_equilibrio", 0.0)
    faixas = cfg["faixas"]

    # Base de cálculo da taxa de cobrança: pode ser um campo separado ou o faturamento bruto
    base_taxa_cob = float((custos_extras or {}).get("base_calculo_taxa_cobranca", faturamento))
    taxa_cob_valor = round(base_taxa_cob * taxa_cob_pct, 2)

    subtotal = round(faturamento * (1 - aliq) - taxa_cob_valor, 2)

    # Custos mensais fixos (condomínio, IPTU, energia — ex: Ekos, OKA)
    custos = {}
    for k, v in (cfg.get("custos_mensais") or {}).items():
        custos[k] = float(custos_extras.get(k, v) if custos_extras else v)
    # Custos variáveis (sistema_perto etc.)
    for k, v in (cfg.get("custos_variaveis") or {}).items():
        custos[k] = float(custos_extras.get(k, v) if custos_extras else v)
    # Custos extras dinâmicos (eventos etc.)
    _excluir = {"base_calculo_taxa_cobranca", "ponto_equilibrio_override"}
    for k, v in (custos_extras or {}).items():
        if k not in custos and k not in _excluir and v:
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

    return ResultadoUnidade(
        unidade_id=cfg["id"],
        mes_referencia=mes,
        faturamento=faturamento,
        aliquota_imposto=aliq,
        subtotal=subtotal,
        ponto_equilibrio=pe,
        custos=custos,
        resultado=resultado,
        aluguel_calculado=round(aluguel, 2),
        extras=extras,
    )
