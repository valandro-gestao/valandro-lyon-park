"""
Calculadora COM_ALIQUOTA_REPASSE_DUPLO — Terreno OKA.

Fórmula:
  subtotal = faturamento * (1 - aliq) - taxa_cobranca
  resultado = subtotal - PE - custos
  Para cada item em `repasses`:
    valor = max(resultado * percentual, aluguel_minimo)
  total_repasse = soma de todos os repasses
"""
from app.models import ResultadoUnidade
from app.rubricas import custos_com_overrides, ids_normalizados


def calcular_com_aliquota_repasse_duplo(cfg: dict, mes: str, faturamento: float,
                                         pe_override: float = None,
                                         custos_extras: dict = None,
                                         **kwargs) -> ResultadoUnidade:
    pe = pe_override if pe_override is not None else cfg.get("ponto_equilibrio", 0.0)
    aliq = cfg.get("aliquota_imposto", 0.0)
    taxa_cob_pct = cfg.get("taxa_cobranca", 0.0)

    base_taxa_cob = float((custos_extras or {}).get("base_calculo_taxa_cobranca", faturamento))
    taxa_cob_valor = round(base_taxa_cob * taxa_cob_pct, 2)
    subtotal = round(faturamento * (1 - aliq) - taxa_cob_valor, 2)

    custos = dict(custos_com_overrides(cfg.get("custos_mensais"), custos_extras))
    custos.update(custos_com_overrides(cfg.get("custos_variaveis"), custos_extras))
    _excluir = {"base_calculo_taxa_cobranca", "ponto_equilibrio_override"}
    _ids_rubricas = ids_normalizados(cfg.get("custos_mensais"), cfg.get("custos_variaveis"))
    for k, v in (custos_extras or {}).items():
        if k not in custos and k not in _ids_rubricas and k not in _excluir and v:
            custos[k] = float(v)
    total_custos = sum(custos.values())

    resultado = round(subtotal - pe - total_custos, 2)

    repasses_cfg = cfg.get("repasses", [])
    repasses_calc = []
    total_aluguel = 0.0
    for rep in repasses_cfg:
        pct = rep.get("percentual", 0.0)
        minimo = rep.get("aluguel_minimo", 0.0)
        val = round(max(resultado * pct, minimo) if resultado > 0 else minimo, 2)
        total_aluguel += val
        repasses_calc.append({
            "id":    rep.get("id", ""),
            "nome":  rep.get("nome", ""),
            "percentual": pct,
            "aluguel_minimo": minimo,
            "aluguel": val,
        })

    extras = {
        "taxa_cobranca": taxa_cob_pct,
        "base_taxa_cobranca": base_taxa_cob,
        "taxa_cobranca_valor": taxa_cob_valor,
        "repasses": repasses_calc,
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
        aluguel_calculado=round(total_aluguel, 2),
        extras=extras,
    )
