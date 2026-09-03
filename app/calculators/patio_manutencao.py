from app.models import ResultadoUnidade, get_saldo_acumulado
from app.rubricas import custos_com_overrides


def calcular_patio_manutencao(cfg: dict, mes: str, faturamento: float,
                               saldo_override: float = None,
                               custos_extras: dict = None,
                               **kwargs) -> ResultadoUnidade:
    """
    Cálculo da unidade de Manutenções do Pátio.

    DRE:
      Receita Total de Manutenções
      (-) Retenção ISS (5%)
      Total Líquido
      (-) Custos (aucon, instalacoes etc.)
      Resultado
      Saldo Acumulado (carregado entre meses via DB)
    """
    iss_pct = cfg.get("retencao_iss", 0.05)
    retencao_iss = round(faturamento * iss_pct, 2)
    subtotal = round(faturamento - retencao_iss, 2)

    custos = dict(custos_com_overrides(cfg.get("custos_mensais"), custos_extras))
    total_custos = sum(custos.values())

    resultado = round(subtotal - total_custos, 2)

    # Saldo acumulado carregado do mês anterior (via DB ou override manual)
    if saldo_override is not None:
        saldo_anterior = saldo_override
    else:
        saldo_anterior = get_saldo_acumulado(cfg["id"])

    saldo_acumulado = round(saldo_anterior + resultado, 2)

    return ResultadoUnidade(
        unidade_id=cfg["id"],
        mes_referencia=mes,
        faturamento=faturamento,
        aliquota_imposto=iss_pct,
        subtotal=subtotal,
        ponto_equilibrio=0.0,
        custos=custos,
        resultado=resultado,
        # Reutiliza prejuizo_acumulado_saida para persistir o saldo entre meses
        prejuizo_acumulado_entrada=saldo_anterior,
        prejuizo_acumulado_saida=saldo_acumulado,
        aluguel_calculado=resultado,
        extras={"retencao_iss": retencao_iss, "saldo_acumulado": saldo_acumulado},
    )
