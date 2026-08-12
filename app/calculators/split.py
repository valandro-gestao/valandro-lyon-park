"""
Calculadora COM_ALIQUOTA_SPLIT — unidades com splits de resultado (ex: Axis).

Fluxo:
  subtotal = faturamento * (1 - aliquota)
  resultado = max(subtotal - PE, 0)
  Para cada split:
    base_split = resultado * percentual_split
    aluguel_split = base_split * percentual_aluguel_split
"""
from app.models import ResultadoUnidade


def calcular_com_aliquota_split(cfg: dict, mes: str, faturamento: float,
                                 pe_override: float = None, **kwargs) -> ResultadoUnidade:
    pe = pe_override if pe_override is not None else cfg.get("ponto_equilibrio", 0.0)
    aliq = cfg.get("aliquota_imposto", 0.0)
    splits_cfg = cfg.get("splits", [])

    subtotal = round(faturamento * (1 - aliq), 2)
    resultado = round(max(subtotal - pe, 0.0), 2)

    total_aluguel = 0.0
    extras: dict = {}
    for s in splits_cfg:
        split_id = s.get("id", s["nome"].lower().replace(" ", "_"))
        base = round(resultado * s["percentual_split"], 2)
        aluguel_s = round(base * s["percentual_aluguel"], 2)
        extras[f"base_{split_id}"] = base
        extras[f"aluguel_{split_id}"] = aluguel_s
        extras[f"nome_{split_id}"] = s["nome"]
        total_aluguel += aluguel_s

    total_aluguel = round(total_aluguel, 2)
    extras["splits"] = [
        {
            "id": s.get("id", s["nome"].lower().replace(" ", "_")),
            "nome": s["nome"],
            "percentual_split": s["percentual_split"],
            "percentual_aluguel": s["percentual_aluguel"],
            "base": extras[f"base_{s.get('id', s['nome'].lower().replace(' ', '_'))}"],
            "aluguel": extras[f"aluguel_{s.get('id', s['nome'].lower().replace(' ', '_'))}"],
        }
        for s in splits_cfg
    ]

    return ResultadoUnidade(
        unidade_id=cfg["id"],
        mes_referencia=mes,
        faturamento=faturamento,
        aliquota_imposto=aliq,
        subtotal=subtotal,
        ponto_equilibrio=pe,
        resultado=resultado,
        aluguel_calculado=total_aluguel,
        extras=extras,
    )
