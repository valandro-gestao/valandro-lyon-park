"""
Calculadora COM_ALIQUOTA_CUMUL_DU — caso-piloto Nilo Square (homologação
set/2026). Isolada de `app.calculators.cumulativo`: nenhuma das 9 unidades
que já usam COM_ALIQUOTA_CUMUL (Viva Trindade, W Tower, EKOS/OKA etc.) é
tocada por este módulo — só reaproveita, por import, a resolução da cadeia
de prejuízo acumulado (`get_saldo_entrada`) e a aplicação de faixas
(`_aplicar_faixas`), que já eram funções soltas/puras em cumulativo.py.

Convenção de sinal das quatro tabelas dinâmicas de rubricas (Despesas da
Operação, Despesas após Resultado, Despesas de Ressarcimento DU, Despesas
de Rateio DU) — confirmada pela operadora, mesma da planilha legado:
  - despesa normal = valor POSITIVO;
  - estorno/reembolso/ressarcimento = valor NEGATIVO;
  - zero permitido.
O calculator SUBTRAI o total de cada grupo — um reembolso negativo reduz
algebricamente esse total (nunca vira uma segunda dedução/receita).

Fórmula (aprovada, ver relatório da rodada de homologação):
  receita_liquida         = faturamento - impostos
  ressarcimento_liquido_du = receita_ressarcimento_du - Σ despesas_ressarcimento_du
  subtotal_receita         = receita_liquida + ressarcimento_liquido_du
  resultado                = subtotal_receita - Σ despesas_rateio_du
                              - Σ despesas_operacao - ponto_equilibrio
  resultado_disponivel     = resultado - Σ despesas_pos_resultado + prejuizo_acumulado_entrada
  repasse                  = faixas(resultado_disponivel) ou resultado_disponivel × percentual_aluguel
  prejuizo_acumulado_saida = resultado_disponivel se <= 0, senão 0
  du_por_vaga (informativo, fora da cadeia de repasse)
                            = Σ despesas_rateio_du / numero_vagas

Estrutura (nomes das rubricas) é definida na Administração; os VALORES são
sempre mensais, nunca geram vigência — ver app.ui.fechamento
(`_inputs_rubricas_du`). Aqui o calculator só recebe, via `custos_extras`,
um dict ANINHADO por grupo (nunca uma chave plana compartilhada entre os
quatro grupos — evita colisão de id entre tabelas independentes):
  custos_extras = {
      "receita_ressarcimento_du": 234896.54,
      "despesas_ressarcimento_du": {"proprietarios": 82882.08, ...},
      "despesas_rateio_du": {"energia": -1481.76, ...},
      "despesas_operacao": {...},
      "despesas_pos_resultado": {...},
  }
"""
from app.models import ResultadoUnidade, get_saldo_entrada
from app.rubricas import normalizar_rubricas


def _itens_com_valores(valor_cfg, valores_mensais: dict | None) -> list[dict]:
    """Junta a ESTRUTURA (id/nome, definida na Administração) com os
    VALORES mensais (id -> valor, vindos do Fechamento via custos_extras)
    — mesma resolução de app.rubricas.custos_com_overrides, mas devolvendo
    a lista itemizada (id+nome+valor) em vez de um dict nome->valor: aqui
    precisamos do id estável para reabrir a competência (ver
    app.ui.fechamento._valor_du_ja_lancado) e do nome para PDF/tela, sem
    depender de o nome nunca mudar."""
    valores_mensais = valores_mensais or {}
    return [
        {"id": item.id, "nome": item.nome, "valor": float(valores_mensais.get(item.id, 0.0))}
        for item in normalizar_rubricas(valor_cfg)
    ]


def calcular_com_aliquota_cumul_du(cfg: dict, mes: str, faturamento: float,
                                    saldo_override: float = None,
                                    custos_extras: dict = None,
                                    pe_override: float = None,
                                    **kwargs) -> ResultadoUnidade:
    from app.calculators.cumulativo import _aplicar_faixas

    aliq = cfg.get("aliquota_imposto", 0.0)
    pe = pe_override if pe_override is not None else cfg.get("ponto_equilibrio", 0.0)
    ce = custos_extras or {}

    impostos = round(faturamento * aliq, 2)
    receita_liquida = round(faturamento - impostos, 2)

    receita_du = float(ce.get("receita_ressarcimento_du", 0.0))
    despesas_du = _itens_com_valores(cfg.get("despesas_ressarcimento_du"), ce.get("despesas_ressarcimento_du"))
    total_despesas_du = round(sum(i["valor"] for i in despesas_du), 2)
    ressarcimento_liquido_du = round(receita_du - total_despesas_du, 2)

    subtotal_receita = round(receita_liquida + ressarcimento_liquido_du, 2)

    despesas_rateio = _itens_com_valores(cfg.get("despesas_rateio_du"), ce.get("despesas_rateio_du"))
    total_rateio_du = round(sum(i["valor"] for i in despesas_rateio), 2)

    despesas_operacao = _itens_com_valores(cfg.get("despesas_operacao"), ce.get("despesas_operacao"))
    total_despesas_operacao = round(sum(i["valor"] for i in despesas_operacao), 2)

    resultado = round(subtotal_receita - total_rateio_du - total_despesas_operacao - pe, 2)

    despesas_pos = _itens_com_valores(cfg.get("despesas_pos_resultado"), ce.get("despesas_pos_resultado"))
    total_despesas_pos = round(sum(i["valor"] for i in despesas_pos), 2)

    if saldo_override is not None:
        prejuizo_entrada = saldo_override
    else:
        prejuizo_entrada = get_saldo_entrada(cfg["id"], mes)

    resultado_disponivel = round(resultado - total_despesas_pos + prejuizo_entrada, 2)

    faixas_aluguel = cfg.get("faixas_aluguel")
    pct = cfg.get("percentual_aluguel", 0.0)
    if resultado_disponivel > 0:
        if faixas_aluguel:
            aluguel = _aplicar_faixas(resultado_disponivel, faixas_aluguel)
        else:
            aluguel = round(resultado_disponivel * pct, 2)
        prejuizo_saida = 0.0
    else:
        aluguel = 0.0
        prejuizo_saida = round(resultado_disponivel, 2)

    numero_vagas = cfg.get("numero_vagas") or 0
    du_por_vaga = round(total_rateio_du / numero_vagas, 2) if numero_vagas else None

    extras = {
        "receita_ressarcimento_du": receita_du,
        "despesas_ressarcimento_du": despesas_du,
        "total_despesas_ressarcimento_du": total_despesas_du,
        "ressarcimento_liquido_du": ressarcimento_liquido_du,
        "despesas_rateio_du": despesas_rateio,
        "total_despesas_rateio_du": total_rateio_du,
        "numero_vagas": numero_vagas or None,
        "du_por_vaga": du_por_vaga,
        "despesas_operacao": despesas_operacao,
        "total_despesas_operacao": total_despesas_operacao,
        "despesas_pos_resultado": despesas_pos,
        "total_despesas_pos_resultado": total_despesas_pos,
    }

    return ResultadoUnidade(
        unidade_id=cfg["id"],
        mes_referencia=mes,
        faturamento=faturamento,
        aliquota_imposto=aliq,
        subtotal=subtotal_receita,
        ponto_equilibrio=pe,
        custos={},
        resultado=resultado,
        prejuizo_acumulado_entrada=prejuizo_entrada,
        prejuizo_acumulado_saida=prejuizo_saida,
        aluguel_calculado=aluguel,
        extras=extras,
    )
