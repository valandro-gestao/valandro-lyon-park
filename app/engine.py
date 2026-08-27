import yaml, os, copy
from app.models import (
    ResultadoUnidade, init_db, salvar_lancamento, get_saldo_acumulado,
    get_parametros_vigentes, seed_parametros_from_yaml,
)
from app.calculators.base import calcular_percentual_simples, calcular_com_aliquota
from app.calculators.cumulativo import calcular_com_aliquota_cumul
from app.calculators.faixas import calcular_com_faixas
from app.calculators.split import calcular_com_aliquota_split
from app.calculators.resultado_split import calcular_resultado_split
from app.calculators.repasse_duplo import calcular_com_aliquota_repasse_duplo
from app.calculators.patio import calcular_patio
from app.calculators.patio_manutencao import calcular_patio_manutencao

_UNITS_PATH = os.path.join(os.path.dirname(__file__), "../data/units.yaml")
_units_cache = None


def load_units(force: bool = False) -> dict:
    global _units_cache
    if _units_cache is None or force:
        with open(_UNITS_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _units_cache = {u["id"]: u for u in data["unidades"]}
    return _units_cache


def get_unit(unidade_id: str) -> dict:
    return load_units()[unidade_id]


def get_unit_com_params(unidade_id: str, mes_ref: str) -> dict:
    """
    Retorna cfg do YAML mesclado com parâmetros vigentes do DB.
    DB tem precedência sobre YAML para campos numéricos.
    Semeia o DB automaticamente na primeira chamada por unidade.
    """
    init_db()
    yaml_cfg = load_units()[unidade_id]
    seed_parametros_from_yaml(unidade_id, yaml_cfg)

    db_params = get_parametros_vigentes(unidade_id, mes_ref)
    if not db_params:
        return yaml_cfg

    cfg = copy.deepcopy(yaml_cfg)
    _merge_dict(cfg, db_params)
    return cfg


def _merge_dict(base: dict, overrides: dict):
    """Mescla overrides em base, recursivamente para dicts aninhados."""
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge_dict(base[k], v)
        else:
            base[k] = v


def get_unidades_ativas(mes_referencia: str = None) -> list[dict]:
    units = load_units()
    result = []
    for u in units.values():
        if not u.get("ativo", True):
            if mes_referencia and u.get("inicio", "") <= mes_referencia + "-01":
                pass
            else:
                continue
        result.append(u)
    return result


def calcular(unidade_id: str, mes: str, faturamento: float,
             saldo_override: float = None,
             custos_extras: dict = None,
             extras_patio: dict = None,
             pe_override: float = None) -> ResultadoUnidade:
    cfg = get_unit_com_params(unidade_id, mes)
    tipo = cfg["tipo_calculo"]

    # pe_override pode vir também via custos_extras (para uniformidade da chamada)
    if pe_override is None and custos_extras:
        pe_override = custos_extras.pop("ponto_equilibrio_override", None)

    if tipo == "PERCENTUAL_SIMPLES":
        res = calcular_percentual_simples(cfg, mes, faturamento, pe_override=pe_override)
    elif tipo == "COM_ALIQUOTA":
        res = calcular_com_aliquota(cfg, mes, faturamento,
                                    pe_override=pe_override,
                                    custos_extras=custos_extras)
    elif tipo == "COM_ALIQUOTA_SPLIT":
        res = calcular_com_aliquota_split(cfg, mes, faturamento, pe_override=pe_override)
    elif tipo == "COM_ALIQUOTA_CUMUL":
        saldo = saldo_override if saldo_override is not None else get_saldo_acumulado(unidade_id)
        res = calcular_com_aliquota_cumul(cfg, mes, faturamento,
                                           saldo_override=saldo,
                                           custos_extras=custos_extras,
                                           pe_override=pe_override)
    elif tipo == "COM_FAIXAS":
        res = calcular_com_faixas(cfg, mes, faturamento,
                                   custos_extras=custos_extras,
                                   pe_override=pe_override)
    elif tipo == "RESULTADO_SPLIT":
        res = calcular_resultado_split(cfg, mes, faturamento,
                                        custos_extras=custos_extras)
    elif tipo == "COM_ALIQUOTA_REPASSE_DUPLO":
        res = calcular_com_aliquota_repasse_duplo(cfg, mes, faturamento,
                                                   pe_override=pe_override,
                                                   custos_extras=custos_extras)
    elif tipo == "PATIO_OPERACAO":
        return calcular_patio(cfg, mes, faturamento, **(extras_patio or {}))
    elif tipo == "PATIO_MANUTENCAO":
        saldo = saldo_override if saldo_override is not None else get_saldo_acumulado(unidade_id)
        res = calcular_patio_manutencao(cfg, mes, faturamento,
                                         saldo_override=saldo,
                                         custos_extras=custos_extras)
    else:
        raise ValueError(f"Tipo de cálculo desconhecido: {tipo}")

    return res


def salvar(resultado: ResultadoUnidade):
    init_db()
    salvar_lancamento(resultado)


def seed_saldos_iniciais():
    """Insere saldos de prejuízo acumulado para início do sistema."""
    from app.models import get_db
    init_db()
    saldos = {
        # in_1183 removido (v1.1.1): a unidade não usa mais COM_ALIQUOTA_CUMUL
        # e não tem mecanismo de prejuízo acumulado — ver data/units.yaml.
        "mw_tristeza": -632029.12,
        "ilp": 0.0,
        "dom_pedro": -171239.32,
        "viva_trindade": -149050.05,
        "anitta_mall": 0.0,
    }
    with get_db() as conn:
        for uid, saldo in saldos.items():
            conn.execute("""
                INSERT INTO saldos_acumulados (unidade_id, prejuizo_acumulado)
                VALUES (?, ?)
                ON CONFLICT(unidade_id) DO UPDATE SET prejuizo_acumulado=excluded.prejuizo_acumulado
            """, (uid, saldo))
    print("Saldos iniciais inseridos.")
