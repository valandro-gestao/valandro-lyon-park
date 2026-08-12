"""
Calculadora RESULTADO_SPLIT — Medcenter e Viva Open Mall.

Fórmula:
  receita_liquida = faturamento * (1 - aliq)
  despesas = despesas_fixas + custos_mensais + custos_variaveis
  resultado = receita_liquida - despesas
  resultado_operador    = resultado * percentual_operador     (ex: 15%)
  resultado_contratante = resultado * percentual_contratante  (ex: 85%)
  saldo_a_pagar = resultado_contratante - parcela_fixa
"""
from app.models import ResultadoUnidade


def calcular_resultado_split(cfg: dict, mes: str, faturamento: float,
                              custos_extras: dict = None,
                              **kwargs) -> ResultadoUnidade:
    aliq = cfg.get("aliquota_imposto", 0.0)
    despesas_fixas = cfg.get("despesas_fixas", 0.0)
    pct_op = cfg.get("percentual_operador", 0.15)
    pct_cont = cfg.get("percentual_contratante", 0.85)
    parcela_fixa = cfg.get("parcela_fixa", 0.0)

    receita_liquida = round(faturamento * (1 - aliq), 2)

    # Custos mensais variáveis (condomínio, IPTU, energia, água, internet, etc.)
    custos: dict = {}
    for k, v in (cfg.get("custos_mensais") or {}).items():
        custos[k] = float(custos_extras.get(k, v) if custos_extras else v)
    for k, v in (cfg.get("custos_variaveis") or {}).items():
        custos[k] = float(custos_extras.get(k, v) if custos_extras else v)
    for k, v in (custos_extras or {}).items():
        if k not in custos and v:
            custos[k] = float(v)
    total_custos = sum(custos.values())

    resultado = round(receita_liquida - despesas_fixas - total_custos, 2)
    resultado_operador = round(resultado * pct_op, 2)
    resultado_contratante = round(resultado * pct_cont, 2)
    saldo_a_pagar = round(resultado_contratante - parcela_fixa, 2)

    extras = {
        "receita_liquida": receita_liquida,
        "despesas_fixas": despesas_fixas,
        "resultado_operador": resultado_operador,
        "resultado_contratante": resultado_contratante,
        "parcela_fixa": parcela_fixa,
        "saldo_a_pagar": saldo_a_pagar,
        "percentual_operador": pct_op,
        "percentual_contratante": pct_cont,
    }

    return ResultadoUnidade(
        unidade_id=cfg["id"],
        mes_referencia=mes,
        faturamento=faturamento,
        aliquota_imposto=aliq,
        subtotal=receita_liquida,
        custos=custos,
        resultado=resultado,
        aluguel_calculado=saldo_a_pagar,
        extras=extras,
    )
