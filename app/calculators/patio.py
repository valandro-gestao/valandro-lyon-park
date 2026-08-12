from dataclasses import dataclass, field
from app.models import ResultadoUnidade


@dataclass
class ResultadoPatio:
    mes_referencia: str
    real: ResultadoUnidade
    maiojama: ResultadoUnidade
    outros_servicos: dict = field(default_factory=dict)
    carregadores: dict = field(default_factory=dict)
    manutencao: dict = field(default_factory=dict)


def calcular_patio(cfg: dict, mes: str,
                   fat_total: float,
                   receitas_midia: float = 0.0,
                   outros_custos_midia: dict = None,
                   receita_carregadores: float = 0.0,
                   custo_energia_carregadores: float = 0.0,
                   investimento_inicial_carregadores: float = 0.0,
                   saldo_carregadores: float = 0.0,
                   receita_manutencao: float = 0.0,
                   custos_manutencao: dict = None,
                   saldo_manutencao: float = 0.0,
                   custos_variaveis_real: dict = None,
                   custos_variaveis_maiojama: dict = None,
                   ) -> ResultadoPatio:

    aliq = cfg["aliquota_imposto"]
    splits_cfg = {s["id"]: s for s in cfg["splits"]}
    r_cfg = splits_cfg["real"]
    m_cfg = splits_cfg["maiojama"]

    def calcular_split(split_cfg: dict, fat: float, custos_var: dict = None) -> ResultadoUnidade:
        pe = split_cfg["ponto_equilibrio"]
        pct = split_cfg["percentual_aluguel"]
        subtotal = round(fat * (1 - aliq), 2)

        custos = {}
        for k, v in (split_cfg.get("custos_mensais") or {}).items():
            custos[k] = float(custos_var.get(k, v) if custos_var else v)
        total_custos = sum(custos.values())

        resultado = max(subtotal - pe - total_custos, 0.0)
        aluguel = round(resultado * pct, 2)
        return ResultadoUnidade(
            unidade_id=f"patio_{split_cfg['id']}",
            mes_referencia=mes,
            faturamento=fat,
            aliquota_imposto=aliq,
            subtotal=subtotal,
            ponto_equilibrio=pe,
            custos=custos,
            resultado=round(resultado, 2),
            aluguel_calculado=aluguel,
        )

    fat_real = round(fat_total * r_cfg["percentual_split"], 2)
    fat_maiojama = round(fat_total * m_cfg["percentual_split"], 2)

    res_real = calcular_split(r_cfg, fat_real, custos_variaveis_real)
    res_maiojama = calcular_split(m_cfg, fat_maiojama, custos_variaveis_maiojama)

    # Outros Serviços (mídias) — compartilhado
    os_cfg = cfg.get("outros_servicos", {})
    outros = {}
    if receitas_midia > 0:
        subtotal_os = round(receitas_midia * (1 - aliq), 2)
        despesas_os = sum((outros_custos_midia or {}).values())
        resultado_os = round(subtotal_os - despesas_os, 2)
        repasse_os = round(resultado_os * os_cfg.get("percentual_repasse", 0.5), 2)
        outros = {
            "receitas_midia": receitas_midia,
            "subtotal": subtotal_os,
            "despesas": outros_custos_midia or {},
            "resultado": resultado_os,
            "repasse_total": repasse_os,
            "repasse_real": round(repasse_os * os_cfg.get("split_real", 0.5352), 2),
            "repasse_maiojama": round(repasse_os * os_cfg.get("split_maiojama", 0.4648), 2),
        }
        res_real.extras["repasse_outros"] = outros["repasse_real"]
        res_maiojama.extras["repasse_outros"] = outros["repasse_maiojama"]

    # Carregadores elétricos
    car_cfg = cfg.get("carregadores", {})
    carregadores = {}
    if receita_carregadores > 0:
        taxa_weg = round(receita_carregadores * car_cfg.get("taxa_intermediacao_weg", 0.10), 2)
        resultado_car = round(receita_carregadores - taxa_weg - custo_energia_carregadores, 2)
        novo_saldo = round(saldo_carregadores + resultado_car - investimento_inicial_carregadores, 2)
        repasse = round(max(novo_saldo, 0) * car_cfg.get("percentual_repasse", 0.60), 2) if novo_saldo > 0 else 0.0
        carregadores = {
            "receita": receita_carregadores,
            "taxa_weg": taxa_weg,
            "custo_energia": custo_energia_carregadores,
            "investimento": investimento_inicial_carregadores,
            "resultado": resultado_car,
            "saldo": novo_saldo,
            "repasse_total": repasse,
            "repasse_real": round(repasse * car_cfg.get("split_real", 0.5352), 2),
            "repasse_maiojama": round(repasse * car_cfg.get("split_maiojama", 0.4648), 2),
        }

    # Manutenção
    man_cfg = cfg.get("manutencao", {})
    manutencao = {}
    if receita_manutencao > 0:
        retencao_iss = round(receita_manutencao * man_cfg.get("retencao_iss", 0.05), 2)
        total_liquido = round(receita_manutencao - retencao_iss, 2)
        total_despesas = sum((custos_manutencao or {}).values())
        resultado_man = round(total_liquido - total_despesas, 2)
        novo_saldo_man = round(saldo_manutencao + resultado_man, 2)
        manutencao = {
            "receita": receita_manutencao,
            "retencao_iss": retencao_iss,
            "total_liquido": total_liquido,
            "despesas": custos_manutencao or {},
            "total_despesas": total_despesas,
            "resultado": resultado_man,
            "saldo_acumulado": novo_saldo_man,
        }

    return ResultadoPatio(
        mes_referencia=mes,
        real=res_real,
        maiojama=res_maiojama,
        outros_servicos=outros,
        carregadores=carregadores,
        manutencao=manutencao,
    )
