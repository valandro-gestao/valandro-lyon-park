from app.models import ResultadoUnidade


def calcular_percentual_simples(cfg: dict, mes: str, faturamento: float,
                                 pe_override: float = None, **kwargs) -> ResultadoUnidade:
    pe = pe_override if pe_override is not None else cfg.get("ponto_equilibrio", 0.0)
    pct = cfg["percentual_aluguel"]
    taxa_admin = cfg.get("taxa_admin_fixa", 0.0) or 0.0
    resultado_bruto = faturamento - pe
    extras: dict = {}

    if resultado_bruto > 0:
        aluguel = round(resultado_bruto * pct, 2)
    else:
        aluguel = 0.0
        if taxa_admin:
            extras["taxa_admin"] = taxa_admin

    return ResultadoUnidade(
        unidade_id=cfg["id"],
        mes_referencia=mes,
        faturamento=faturamento,
        ponto_equilibrio=pe,
        resultado=round(resultado_bruto, 2),
        aluguel_calculado=aluguel,
        extras=extras if extras else None,
    )


def calcular_com_aliquota(cfg: dict, mes: str, faturamento: float,
                           pe_override: float = None,
                           custos_extras: dict = None,
                           **kwargs) -> ResultadoUnidade:
    pe = pe_override if pe_override is not None else cfg.get("ponto_equilibrio", 0.0)
    aliq = cfg.get("aliquota_imposto", 0.0)
    pct = cfg.get("percentual_aluguel", 0.0)

    # Faturamento pode incluir carregadores (In 1183: Total Faturamento =
    # Estacionamento + Carregadores, conforme Memória de Cálculo). Não afeta
    # unidades que não usam esse campo — fat_carregadores é 0.0 por padrão.
    fat_carregadores = float((custos_extras or {}).get("fat_carregadores", 0.0))
    faturamento_total = faturamento + fat_carregadores

    subtotal = round(faturamento_total * (1 - aliq), 2)
    resultado = round(max(subtotal - pe, 0.0), 2)
    aluguel = round(resultado * pct, 2)

    extras: dict = {}
    if fat_carregadores:
        extras["fat_carregadores"] = fat_carregadores

    # Investimentos (FK, In 1183 e similares): dedução do aluguel → saldo_a_pagar
    investimentos = float((custos_extras or {}).get("investimentos", 0.0))
    if investimentos == 0.0:
        investimentos = float((cfg.get("custos_variaveis") or {}).get("investimentos", 0.0))
    if investimentos:
        extras["investimentos"] = investimentos
        extras["saldo_a_pagar"] = round(aluguel - investimentos, 2)

    return ResultadoUnidade(
        unidade_id=cfg["id"],
        mes_referencia=mes,
        faturamento=faturamento_total,
        aliquota_imposto=aliq,
        subtotal=subtotal,
        ponto_equilibrio=pe,
        resultado=resultado,
        aluguel_calculado=aluguel,
        extras=extras if extras else None,
    )
