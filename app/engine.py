import yaml, os, copy
from app.paths import UNITS_YAML
from app.models import (
    ResultadoUnidade, init_db, get_db, salvar_lancamento,
    get_parametros_vigentes, seed_parametros_from_yaml,
    validar_configuracao_unidade, unidade_possui_lancamento_no_mes,
)
from app.calculators.base import calcular_percentual_simples, calcular_com_aliquota
from app.calculators.cumulativo import calcular_com_aliquota_cumul
from app.calculators.faixas import calcular_com_faixas
from app.calculators.split import calcular_com_aliquota_split
from app.calculators.resultado_split import calcular_resultado_split
from app.calculators.repasse_duplo import calcular_com_aliquota_repasse_duplo
from app.calculators.patio import calcular_patio
from app.calculators.patio_manutencao import calcular_patio_manutencao

_units_cache = None
_yaml_blocos_cache = None


def _yaml_blocos() -> dict:
    """Blocos originais de data/units.yaml, indexados por id.

    v1.2.0: a tabela `unidades` (bootstrap em app.models.init_db, formalizado
    pela migration 0007) é a fonte de verdade para identidade/existência/
    status de cada unidade — não este arquivo. Ainda assim, os blocos
    aninhados que a tabela `unidades` deliberadamente não duplica (splits do
    Pátio, faixas, custos_mensais/variaveis — parâmetros operacionais, não
    estrutura) continuam vindo de cada bloco YAML como "shape legado", até a
    etapa seguinte trazer um editor próprio para eles. Uma unidade que só
    existir no banco (criada pela futura tela de Administração, sem bloco
    YAML correspondente) simplesmente não tem nenhum desses campos extras —
    load_units() trata isso normalmente.
    """
    global _yaml_blocos_cache
    if _yaml_blocos_cache is None:
        with open(UNITS_YAML, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _yaml_blocos_cache = {u["id"]: u for u in data["unidades"]}
    return _yaml_blocos_cache


def load_units(force: bool = False) -> dict:
    """Fonte de verdade: tabela `unidades` no banco (migration 0007).

    Cada unidade é montada a partir da linha do banco (identidade:
    nome, contratante, ativo, inicio, tipo_calculo, tipo_relatorio) com o
    bloco YAML correspondente (se existir) por baixo, fornecendo só os
    campos aninhados ainda não migrados para tabela própria — nunca o
    contrário: um valor estrutural do banco sempre prevalece sobre o YAML.
    """
    global _units_cache
    if _units_cache is None or force:
        init_db()
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM unidades").fetchall()

        yaml_blocos = _yaml_blocos()
        unidades = {}
        for row in rows:
            uid = row["id"]
            bloco = dict(yaml_blocos.get(uid, {}))
            bloco.update({
                "id": uid,
                "nome": row["nome"],
                "contratante": row["contratante"],
                "ativo": bool(row["ativo"]),
                "inicio": row["inicio"],
                "tipo_calculo": row["tipo_calculo"],
                "tipo_relatorio": row["tipo_relatorio"],
            })
            unidades[uid] = bloco
        _units_cache = unidades
    return _units_cache


def get_unit(unidade_id: str) -> dict:
    return load_units()[unidade_id]


def get_parametros_efetivos(unidade_id: str, mes_ref: str) -> dict:
    """
    A mesma resolução "efetiva" que o motor de cálculo usa (bloco legado do
    YAML como base + parâmetros já vigentes no banco por cima, DB sempre
    prevalecendo) — mas PURA: nunca chama seed_parametros_from_yaml, nunca
    escreve em parametros_vigentes, nunca chama init_db(). Não modifica o
    banco só porque alguém pediu para ler o estado de uma unidade.

    Existe para que a validação administrativa
    (app.models.validar_configuracao_unidade) enxergue exatamente o que o
    motor calcularia para aquela competência — antes, ela usava só
    get_parametros_vigentes (banco puro), o que fazia uma unidade cujo
    bloco YAML legado ainda carrega valores plenamente válidos aparecer
    como "incompleta" só por nunca ter sido "tocada" por
    get_unit_com_params (que faz esse seed automaticamente, mas como
    efeito colateral de calcular, não de só abrir uma tela).

    YAML aqui continua sendo só a ponte para os blocos ainda não migrados
    para tabela própria (faixas/splits/repasses/custos de unidades
    antigas) — nunca a fonte de verdade da identidade da unidade (isso é
    sempre a tabela `unidades`, já refletida em load_units()).
    """
    yaml_cfg = load_units()[unidade_id]
    db_params = get_parametros_vigentes(unidade_id, mes_ref)
    if not db_params:
        return yaml_cfg
    cfg = copy.deepcopy(yaml_cfg)
    _merge_dict(cfg, db_params)
    return cfg


def get_unit_com_params(unidade_id: str, mes_ref: str) -> dict:
    """
    Retorna cfg do YAML mesclado com parâmetros vigentes do DB.
    DB tem precedência sobre YAML para campos numéricos.
    Semeia o DB automaticamente na primeira chamada por unidade — esse
    lazy seed é feito aqui, e só aqui: get_parametros_efetivos (usada pela
    validação administrativa) resolve a mesma mescla sem esse efeito
    colateral.
    """
    init_db()
    yaml_cfg = load_units()[unidade_id]
    seed_parametros_from_yaml(unidade_id, yaml_cfg)
    return get_parametros_efetivos(unidade_id, mes_ref)


def _merge_dict(base: dict, overrides: dict):
    """Mescla overrides em base, recursivamente para dicts aninhados."""
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge_dict(base[k], v)
        else:
            base[k] = v


def get_unidades_ativas(mes_referencia: str = None) -> list[dict]:
    """Unidades que participam do fluxo operacional (Dashboard/Fechamento)
    NAQUELA competência.

    v1.2.0: uma unidade só é oferecida no Fechamento de uma competência
    quando (1) está operacionalmente ativa (`ativo=1`); (2) a competência
    é >= `inicio`; e (3) possui configuração efetiva válida naquela
    competência (app.models.validar_configuracao_unidade, que já resolve
    "nao_aplicavel" — ex. PATIO_OPERACAO — como sem bloqueio) OU (4) já
    existe lançamento gravado naquela competência, para nunca esconder do
    Fechamento uma competência que já teve cálculo/consulta real (ex.:
    unidade cuja configuração só passou a ser válida numa competência
    posterior, mas que já tinha um rascunho/aprovação num mês anterior).

    Deliberadamente NÃO depende de date.today() nem de "mês atual vs.
    passado/futuro": as 4 condições acima valem do mesmo jeito para
    qualquer competência, passada, presente ou futura — uma unidade cuja
    primeira configuração válida é só em 2026-10 não aparece em 2026-09
    mesmo que 2026-09 seja "hoje", e uma unidade com lançamento em
    2025-03 continua aparecendo lá mesmo que sua configuração atual não
    cubra mais aquele mês.

    Sem `mes_referencia`, retorna todas as `ativo=1` sem checar (2)/(3)/(4)
    — usado só por código que itera unidades ativas fora do contexto de
    uma competência específica (ex. scripts/relatorio_historico_mensal.py).

    Não afeta consulta de relatórios/histórico de uma unidade inativa —
    essa consulta usa `lancamentos`/`historico_anual` diretamente, não esta
    função. Esta função decide só quem entra no fluxo operacional CORRENTE
    para a competência informada.
    """
    units = load_units()
    if mes_referencia is None:
        return [u for u in units.values() if u.get("ativo", True)]

    result = []
    for u in units.values():
        if not u.get("ativo", True):
            continue
        if u.get("inicio", "") > mes_referencia + "-01":
            continue
        config_valida = validar_configuracao_unidade(u["id"], mes_referencia) == []
        tem_lancamento = unidade_possui_lancamento_no_mes(u["id"], mes_referencia)
        if config_valida or tem_lancamento:
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
        # v1.2.0: não pré-resolve mais o saldo aqui via get_saldo_acumulado
        # (valor único e corrente, sem competência) — passa saldo_override
        # como veio (None inclusive) e deixa o calculator resolver a
        # entrada pela cadeia real (app.models.get_saldo_entrada).
        res = calcular_com_aliquota_cumul(cfg, mes, faturamento,
                                           saldo_override=saldo_override,
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
        # v1.2.0: idem COM_ALIQUOTA_CUMUL — sem pré-resolução via
        # get_saldo_acumulado; o calculator resolve pela cadeia real.
        res = calcular_patio_manutencao(cfg, mes, faturamento,
                                         saldo_override=saldo_override,
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
