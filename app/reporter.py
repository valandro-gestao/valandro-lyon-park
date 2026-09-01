"""
Motor de montagem do ReportData.
"""
from __future__ import annotations
import json
from datetime import date, datetime
from app.report_data import (
    ReportData, UnidadeInfo, Cards, ComparativoMes,
    LinhaPrestacao, Prestacao, Historico, LinhaHistoricoAnual,
    BlocoReceita, BlocoEventos, EventoCompetencia, ResumoEvento,
)
from app.models import ResultadoUnidade, get_lancamentos_mes, get_historico_anual, get_db
from app.calculators.patio import ResultadoPatio
from app.engine import get_unit
from app.parsers import eventos as eventos_parser

MESES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]
MESES_CURTO = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _label_mes(mes_ref: str) -> str:
    ano, m = mes_ref.split("-")
    return f"{MESES_PT[int(m)-1]} / {ano}"


def _label_mes_curto(mes_ref: str) -> str:
    ano, m = mes_ref.split("-")
    return f"{MESES_CURTO[int(m)-1]}/{ano[2:]}"


def _pct_var(atual: float, anterior: float) -> float | None:
    if anterior is None or anterior == 0:
        return None
    return round((atual - anterior) / abs(anterior) * 100, 1)


def _get_lancamentos_periodo(unidade_id: str, mes_ref: str, meses: int = 24) -> list[dict]:
    """Busca até `meses` competências terminando em `mes_ref` (inclusive).
    Padrão de 24: os 12 meses exibidos no comparativo mais os 12 meses
    correspondentes um ano antes de cada um — necessários para a
    comparação YoY em _comparativo_12m, sem depender de uma segunda
    consulta por linha exibida."""
    ano, mes = int(mes_ref[:4]), int(mes_ref[5:7])
    candidatos = []
    for i in range(meses):
        m = mes - i
        a = ano
        while m <= 0:
            m += 12
            a -= 1
        candidatos.append(f"{a}-{m:02d}")

    with get_db() as conn:
        placeholders = ",".join("?" * len(candidatos))
        rows = conn.execute(f"""
            SELECT mes_referencia, resultado_json
            FROM lancamentos
            WHERE unidade_id=? AND mes_referencia IN ({placeholders})
            ORDER BY mes_referencia DESC
        """, [unidade_id] + candidatos).fetchall()

    return [{"mes": r["mes_referencia"], **json.loads(r["resultado_json"])} for r in rows]


def _com_mes_atual(lancamentos: list[dict], resultado, mes_ref: str) -> list[dict]:
    """Garante que a competência sendo processada apareça no comparativo
    mesmo quando ainda não foi salva em `lancamentos`.

    Isso acontece sempre que o PDF é gerado antes da aprovação ("Gerar PDF"
    não chama salvar_lancamento — só "Aprovar" chama, e o faz antes de gerar
    o relatório). Nesse caso, `_get_lancamentos_periodo` busca as
    competências corretas, mas o próprio mes_ref ainda não existe no banco.
    Não é um problema na consulta: é a competência atual que ainda não foi
    persistida.

    Se mes_ref já estiver presente (aprovação, ou reabertura já recalculada
    e salva), não faz nada — o valor do banco nunca é substituído pelo
    rascunho em memória. Não trunca a lista — quem decide quantas linhas
    exibir é _comparativo_12m, que também precisa do restante (meses do
    ano anterior) para a comparação YoY.
    """
    if any(l["mes"] == mes_ref for l in lancamentos):
        return lancamentos
    atual = {"mes": mes_ref, **resultado.__dict__}
    return sorted(lancamentos + [atual], key=lambda l: l["mes"], reverse=True)


def _comparativo_12m(lancamentos: list[dict]) -> list[ComparativoMes]:
    """Monta as até 12 linhas exibidas no comparativo mensal do PDF,
    comparando cada competência com o MESMO MÊS DO ANO ANTERIOR (YoY) —
    não com o mês imediatamente anterior.

    `lancamentos` deve conter, além das competências exibidas, as
    competências correspondentes um ano antes de cada uma (fornecidas por
    _get_lancamentos_periodo com meses=24) — usadas só como referência de
    comparação, nunca como linha própria do comparativo exibido.

    Quando a competência do ano anterior não existir, a variação fica
    `None` — nunca inventa comparação com outro mês.
    """
    por_mes = {l["mes"]: l for l in lancamentos}
    exibidas = sorted(lancamentos, key=lambda l: l["mes"], reverse=True)[:12]

    result = []
    for l in exibidas:
        fat = l.get("faturamento", 0.0)
        res = l.get("resultado", 0.0)
        repasse = l.get("aluguel_calculado", 0.0)
        extras = l.get("extras") or {}
        if isinstance(extras, dict):
            repasse += extras.get("repasse_outros", 0.0)

        ano_str, mes_str = l["mes"].split("-")
        mes_ano_anterior = f"{int(ano_str) - 1}-{mes_str}"
        anterior = por_mes.get(mes_ano_anterior)
        if anterior is not None:
            var_fat = _pct_var(fat, anterior.get("faturamento", 0.0))
            var_res = _pct_var(res, anterior.get("resultado", 0.0))
        else:
            var_fat = None
            var_res = None

        result.append(ComparativoMes(
            competencia=l["mes"],
            competencia_label=_label_mes_curto(l["mes"]),
            faturamento=fat,
            variacao_faturamento=var_fat,
            resultado=res,
            variacao_resultado=var_res,
            repasse=repasse,
        ))
    return result


# Colunas fixas do Histórico Anual, na ordem em que aparecem — layout
# "Ano | Faturamento | Resultado | Repasse" (anos em linha, para não
# crescer horizontalmente a cada ano novo). Sempre os mesmos três
# indicadores, nos mesmos conceitos dos cards principais — não varia por
# tipo de calculadora e não é substituído por outro indicador quando
# ausente (ver _historico_anual).
_HISTORICO_ANUAL_COLUNAS = [
    ("faturamento",       "Faturamento"),
    ("resultado",         "Resultado"),
    ("aluguel_calculado", "Repasse"),
]


def _formatar_ano_label(ano: int, quantidade_meses: int | None) -> str:
    """"2025" quando o ano tem as 12 competências; "2024 (10 meses)" /
    "2026 (1 mês)" quando é parcial. `quantidade_meses` vem pronto de
    `historico_anual.dados_json` (gravado pela migration 0006) — não é
    recalculado aqui a partir de `lancamentos`.

    `quantidade_meses is None` significa um registro legado que a 0006 não
    reconstruiu (nenhum lançamento correspondente em `lancamentos` — ver
    seu docstring: nunca apaga esses registros). Nesse caso NUNCA se supõe
    12 meses — não há evidência disso. O rótulo fica "{ano} (—)": neutro,
    não declara uma contagem que não temos como confirmar."""
    if quantidade_meses is None:
        return f"{ano} (—)"
    if quantidade_meses >= 12:
        return str(ano)
    unidade = "mês" if quantidade_meses == 1 else "meses"
    return f"{ano} ({quantidade_meses} {unidade})"


def _mes_atual_persistido(unidade_id: str, mes_ref: str) -> bool:
    """True se (unidade_id, mes_ref) já existir em `lancamentos`.

    `historico_anual` só é populado agregando `lancamentos` (migration
    0006) — nunca por outro caminho — então "mes_ref já está em
    lancamentos" e "mes_ref já está refletido no agregado anual
    persistido" são a mesma pergunta. Não há necessidade (nem estrutura,
    sem reconstruir o ano inteiro) para verificar isso de outra forma; não
    usa `status` de workflow, só a própria competência."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM lancamentos WHERE unidade_id=? AND mes_referencia=?",
            (unidade_id, mes_ref),
        ).fetchone()
    return row is not None


def _historico_anual(unidade_id: str, mes_ref: str, resultado) -> Historico:
    """Visão gerencial sintética — não a memória completa da prestação de
    contas. Colunas são sempre as mesmas três (Faturamento, Resultado,
    Repasse); quando a base histórica da unidade não tiver Resultado ou
    Repasse para um ano, o valor fica None e o template exibe '—' — nunca
    preenche com outro indicador só para não deixar a célula vazia.

    `historico_anual` é um cache/agregado derivado de `lancamentos` (fonte
    de verdade mensal — ver migration 0006); esta função lê o cache e, só
    quando a competência sendo processada (`mes_ref`) ainda não estiver
    persistida em `lancamentos`, soma o `resultado` em memória ao ano
    correspondente — mesmo princípio que `_com_mes_atual` já aplica ao
    comparativo mensal, para o PDF gerado antes da aprovação não "esquecer"
    a competência atual. Nunca grava nada de volta em `historico_anual`;
    o ajuste vive só no ReportData desta chamada."""
    raw = get_historico_anual(unidade_id)
    por_ano = {e["ano"]: dict(e) for e in raw}

    ano_atual = int(mes_ref[:4])
    if not _mes_atual_persistido(unidade_id, mes_ref):
        agregado = por_ano.get(ano_atual)
        # Ano sem nenhum registro persistido ainda (unidade nova) — parte de
        # zero. Ano com registro legado nunca reconstruído pela 0006
        # (quantidade_meses ausente, ex.: unidades sem lançamentos, como
        # ekos/oka) — não mistura o valor corrente com um agregado que não
        # temos como confirmar; deixa esse ano como está, intocado.
        if agregado is None:
            por_ano[ano_atual] = {
                "ano": ano_atual,
                "faturamento": resultado.faturamento or 0.0,
                "resultado": resultado.resultado or 0.0,
                "aluguel_calculado": (resultado.aluguel_calculado or 0.0)
                    + (resultado.extras or {}).get("repasse_outros", 0.0),
                "quantidade_meses": 1,
            }
        elif agregado.get("quantidade_meses") is not None:
            agregado["faturamento"] = (agregado.get("faturamento") or 0.0) + (resultado.faturamento or 0.0)
            agregado["resultado"] = (agregado.get("resultado") or 0.0) + (resultado.resultado or 0.0)
            agregado["aluguel_calculado"] = (agregado.get("aluguel_calculado") or 0.0) + (
                (resultado.aluguel_calculado or 0.0) + (resultado.extras or {}).get("repasse_outros", 0.0)
            )
            agregado["quantidade_meses"] = agregado["quantidade_meses"] + 1

    if not por_ano:
        return Historico(colunas=[], linhas=[])

    linhas = [
        LinhaHistoricoAnual(
            ano=ano,
            ano_label=_formatar_ano_label(ano, e.get("quantidade_meses")),
            valores={label: e.get(campo) for campo, label in _HISTORICO_ANUAL_COLUNAS},
        )
        for ano, e in sorted(por_ano.items())
    ]

    return Historico(
        colunas=[label for _, label in _HISTORICO_ANUAL_COLUNAS],
        linhas=linhas,
    )


_CUSTO_LABELS: dict[str, str] = {
    "custos_eventos":   "Colaboradores Eventos",
    "condominio":       "Condomínio",
    "iptu":             "IPTU",
    "monitoramento":    "Monitoramento",
    "energia_eletrica": "Energia Elétrica",
    "agua":             "Água",
    "manutencao_equipamentos": "Manutenção de Equipamentos",
    "internet":         "Internet",
    "sistema_perto":    "Sistema Perto",
    "sistema_automacao":"Sistema Automação",
    "aucon":            "Aucon / Equipamentos",
    "instalacoes":      "Manutenção Instalações",
    "investimentos_equipamentos": "Investimentos / Equipamentos",
    "troca_de_lona":    "Troca de Lona",
    "seguranca":        "Segurança",
    "sistemas_voip":    "Sistemas VOIP",
    "perto":            "Perto",
}


def _custo_label(k: str) -> str:
    return _CUSTO_LABELS.get(k, k.replace("_", " ").title())


def _build_bloco_eventos(mes_ref: str, eventos_data: dict) -> BlocoEventos | None:
    if not eventos_data:
        return None
    ev_mes = eventos_parser.get_eventos_competencia(eventos_data, mes_ref)
    resumo_anual = eventos_parser.get_resumo_anual(eventos_data)
    if not ev_mes and not resumo_anual:
        return None

    eventos_obj = [
        EventoCompetencia(
            data=e["data"], evento=e["evento"], horario=e["horario"],
            qtd_extras=e["qtd_extras"], valor_unitario=e["valor_unitario"],
            valor_total=e["valor_total"],
        )
        for e in ev_mes
    ]
    resumo_obj = [
        ResumoEvento(mes=r["mes_label"], qtd_extras=r["qtd_extras"], valor_total=r["valor_total"])
        for r in resumo_anual
    ]
    return BlocoEventos(eventos_competencia=eventos_obj, resumo=resumo_obj)


# ─── prestações ──────────────────────────────────────────────────────────────

def _prestacao_padrao(r: ResultadoUnidade, cfg: dict) -> Prestacao:
    linhas = []
    linhas_cfg = cfg.get("relatorio", {}).get("linhas", [])
    aliq = r.aliquota_imposto
    extras = r.extras or {}

    if "faturamento" in linhas_cfg:
        if extras.get("fat_carregadores"):
            # In 1183: mostra separado e o total
            linhas.append(LinhaPrestacao("Faturamento Estacionamento",
                                         r.faturamento - extras["fat_carregadores"], "subtotal"))
            linhas.append(LinhaPrestacao("(+) Faturamento Carregadores",
                                         extras["fat_carregadores"], "normal"))
            linhas.append(LinhaPrestacao("Total Faturamento", r.faturamento, "subtotal"))
        else:
            linhas.append(LinhaPrestacao("Receita Bruta", r.faturamento, "subtotal"))

    if "aliquota" in linhas_cfg and aliq:
        imposto_valor = round(r.faturamento - r.subtotal, 2)
        linhas.append(LinhaPrestacao(f"(-) Impostos ({aliq*100:.2f}%)", -imposto_valor, "deducao"))
        linhas.append(LinhaPrestacao("Receita Líquida", r.subtotal, "subtotal"))

    if "pe" in linhas_cfg and r.ponto_equilibrio:
        linhas.append(LinhaPrestacao("(-) Ponto de Equilíbrio", -r.ponto_equilibrio, "deducao"))

    for k, v in (r.custos or {}).items():
        if v:
            linhas.append(LinhaPrestacao(f"(-) {_custo_label(k)}", -v, "deducao"))

    if "resultado" in linhas_cfg:
        linhas.append(LinhaPrestacao("Resultado", r.resultado, "destaque"))

    if "prejuizo" in linhas_cfg:
        # Sempre mostra quando configurado — mesmo que zero
        linhas.append(LinhaPrestacao("(+/-) Prejuízo Acumulado",
                                      r.prejuizo_acumulado_entrada, "deducao"))

    repasse = r.aluguel_calculado
    if extras.get("repasse_outros"):
        repasse += extras["repasse_outros"]
    if extras.get("adicional_fixo"):
        linhas.append(LinhaPrestacao("(+) Parcelamento 48 meses", extras["adicional_fixo"], "normal"))
    # Aluguel ou taxa de administração (Vasco — resultado negativo)
    taxa_admin = extras.get("taxa_admin")
    if taxa_admin and r.aluguel_calculado == 0:
        linhas.append(LinhaPrestacao("Taxa de Administração (Resultado Negativo)",
                                      taxa_admin, "total"))
    else:
        linhas.append(LinhaPrestacao("Repasse", repasse, "total"))
        # Dedução pós-repasse: investimentos (FK) ou fundo_recomposicao (W Tower)
        for campo, label in (("investimentos", "(-) Investimentos"),
                              ("fundo_recomposicao", "(-) Fundo de Recomposição")):
            if extras.get(campo):
                linhas.append(LinhaPrestacao(label, -extras[campo], "deducao"))
                linhas.append(LinhaPrestacao("Saldo a Pagar", extras["saldo_a_pagar"], "total"))
                break

    return Prestacao(linhas=linhas)


def _prestacao_faixas(r: ResultadoUnidade, cfg: dict) -> Prestacao:
    linhas = []
    aliq = r.aliquota_imposto
    extras = r.extras or {}
    taxa_cob_pct = extras.get("taxa_cobranca", 0.0)
    taxa_cob_valor = extras.get("taxa_cobranca_valor", 0.0)
    base_taxa_cob = extras.get("base_taxa_cobranca", r.faturamento)
    receita_selos = extras.get("receita_selos", 0.0)

    if receita_selos:
        # Fiergs: composição explícita — nunca soma silenciosamente.
        linhas.append(LinhaPrestacao("Faturamento", r.faturamento - receita_selos, "subtotal"))
        linhas.append(LinhaPrestacao("(+) Receita de Selos", receita_selos, "normal"))
        linhas.append(LinhaPrestacao("Receita Bruta", r.faturamento, "subtotal"))
    else:
        linhas.append(LinhaPrestacao("Receita Bruta", r.faturamento, "subtotal"))
    if aliq:
        imposto_valor = round(r.faturamento * aliq, 2)
        linhas.append(LinhaPrestacao(f"(-) Impostos ({aliq*100:.2f}%)", -imposto_valor, "deducao"))
    if taxa_cob_pct and taxa_cob_valor:
        bc_fmt = f"R$ {base_taxa_cob:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        linhas.append(LinhaPrestacao(
            f"(-) Taxa de Cobrança {taxa_cob_pct*100:.1f}% (BC = {bc_fmt})",
            -taxa_cob_valor, "deducao"))
    linhas.append(LinhaPrestacao("Subtotal", r.subtotal, "subtotal"))
    if r.ponto_equilibrio:
        linhas.append(LinhaPrestacao("(-) Ponto de Equilíbrio", -r.ponto_equilibrio, "deducao"))
    for k, v in (r.custos or {}).items():
        if v:
            linhas.append(LinhaPrestacao(f"(-) {_custo_label(k)}", -v, "deducao"))
    linhas.append(LinhaPrestacao("Resultado", r.resultado, "destaque"))

    # Faixas de aluguel detalhadas
    faixas_cfg = cfg.get("faixas", [])
    faixas_det = extras.get("faixas_detalhe", [])
    for i, f in enumerate(faixas_cfg):
        det = faixas_det[i] if i < len(faixas_det) else {}
        pct = f["percentual"]
        ate = f.get("ate")
        if ate:
            label = f"Aluguel {int(pct*100)}% (até R$ {ate:,.0f})"
        else:
            label = f"Aluguel {int(pct*100)}% (excedente)"
        val = det.get("aluguel", 0.0)
        if val:
            linhas.append(LinhaPrestacao(label, val, "normal"))

    linhas.append(LinhaPrestacao("Total Aluguel", r.aluguel_calculado, "total"))
    return Prestacao(linhas=linhas)


def _prestacao_split(r: ResultadoUnidade, cfg: dict) -> Prestacao:
    """DRE para COM_ALIQUOTA_SPLIT (Axis)."""
    linhas = []
    aliq = r.aliquota_imposto
    extras = r.extras or {}
    splits = extras.get("splits", [])

    linhas.append(LinhaPrestacao("Receita Bruta", r.faturamento, "subtotal"))
    if aliq:
        imposto_valor = round(r.faturamento - r.subtotal, 2)
        linhas.append(LinhaPrestacao(f"(-) Impostos ({aliq*100:.2f}%)", -imposto_valor, "deducao"))
        linhas.append(LinhaPrestacao("Receita Líquida", r.subtotal, "subtotal"))
    if r.ponto_equilibrio:
        linhas.append(LinhaPrestacao("(-) Ponto de Equilíbrio", -r.ponto_equilibrio, "deducao"))
    linhas.append(LinhaPrestacao("Resultado", r.resultado, "destaque"))

    for s in splits:
        pct_split = s["percentual_split"]
        pct_al = s["percentual_aluguel"]
        linhas.append(LinhaPrestacao(
            f"Aluguel {s['nome']} ({pct_split*100:.4f}% × {int(pct_al*100)}%)",
            s["aluguel"], "normal"))

    linhas.append(LinhaPrestacao("Total Aluguel", r.aluguel_calculado, "total"))
    return Prestacao(linhas=linhas)


def _prestacao_resultado_split(r: ResultadoUnidade, cfg: dict) -> Prestacao:
    """DRE para RESULTADO_SPLIT — Medcenter e Viva Open Mall."""
    linhas = []
    aliq = r.aliquota_imposto
    extras = r.extras or {}
    pct_op  = extras.get("percentual_operador", cfg.get("percentual_operador", 0.15))
    pct_cnt = extras.get("percentual_contratante", cfg.get("percentual_contratante", 0.85))
    despesas_fixas = extras.get("despesas_fixas", cfg.get("despesas_fixas", 0.0))

    linhas.append(LinhaPrestacao("Receita Bruta", r.faturamento, "subtotal"))
    if aliq:
        imposto_valor = round(r.faturamento * aliq, 2)
        linhas.append(LinhaPrestacao(f"(-) Impostos ({aliq*100:.2f}%)", -imposto_valor, "deducao"))
    linhas.append(LinhaPrestacao("Receita Líquida", r.subtotal, "subtotal"))
    if despesas_fixas:
        linhas.append(LinhaPrestacao("(-) Despesas Fixas", -despesas_fixas, "deducao"))
    for k, v in (r.custos or {}).items():
        if v:
            linhas.append(LinhaPrestacao(f"(-) {_custo_label(k)}", -v, "deducao"))
    linhas.append(LinhaPrestacao("Resultado Operacional", r.resultado, "destaque"))
    linhas.append(LinhaPrestacao(
        f"Resultado Operador ({int(pct_op*100)}%)", extras.get("resultado_operador", 0.0), "normal"))
    linhas.append(LinhaPrestacao(
        f"Resultado Contratante ({int(pct_cnt*100)}%)", extras.get("resultado_contratante", 0.0), "subtotal"))
    if extras.get("parcela_fixa"):
        linhas.append(LinhaPrestacao("(-) Parcela Fixa Mensal",
                                      -extras["parcela_fixa"], "deducao"))
    linhas.append(LinhaPrestacao("Saldo a Pagar", extras.get("saldo_a_pagar", 0.0), "total"))
    return Prestacao(linhas=linhas)


def _prestacao_repasse_duplo(r: ResultadoUnidade, cfg: dict) -> Prestacao:
    """DRE para COM_ALIQUOTA_REPASSE_DUPLO — Terreno OKA."""
    linhas = []
    aliq = r.aliquota_imposto
    extras = r.extras or {}
    taxa_cob_pct   = extras.get("taxa_cobranca", 0.0)
    taxa_cob_valor = extras.get("taxa_cobranca_valor", 0.0)
    base_taxa_cob  = extras.get("base_taxa_cobranca", r.faturamento)

    linhas.append(LinhaPrestacao("Receita Bruta", r.faturamento, "subtotal"))
    if aliq:
        imposto_valor = round(r.faturamento * aliq, 2)
        linhas.append(LinhaPrestacao(f"(-) Impostos ({aliq*100:.2f}%)", -imposto_valor, "deducao"))
    if taxa_cob_pct and taxa_cob_valor:
        bc_fmt = f"R$ {base_taxa_cob:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        linhas.append(LinhaPrestacao(
            f"(-) Taxa de Cobrança {taxa_cob_pct*100:.1f}% (BC = {bc_fmt})",
            -taxa_cob_valor, "deducao"))
    linhas.append(LinhaPrestacao("Subtotal", r.subtotal, "subtotal"))
    if r.ponto_equilibrio:
        linhas.append(LinhaPrestacao("(-) Ponto de Equilíbrio", -r.ponto_equilibrio, "deducao"))
    for k, v in (r.custos or {}).items():
        if v:
            linhas.append(LinhaPrestacao(f"(-) {_custo_label(k)}", -v, "deducao"))
    linhas.append(LinhaPrestacao("Resultado", r.resultado, "destaque"))

    for rep in extras.get("repasses", []):
        pct = rep.get("percentual", 0.0)
        minimo = rep.get("aluguel_minimo", 0.0)
        nome = rep.get("nome", "")
        pct_str = f"{pct*100:.4g}%"
        if minimo:
            label = f"Aluguel {nome} ({pct_str} | mín. R$ {minimo:,.2f})"
        else:
            label = f"Aluguel {nome} ({pct_str})"
        linhas.append(LinhaPrestacao(label, rep["aluguel"], "normal"))

    linhas.append(LinhaPrestacao("Total Repasse", r.aluguel_calculado, "total"))
    return Prestacao(linhas=linhas)


def _prestacao_manutencao(r: ResultadoUnidade, cfg: dict) -> Prestacao:
    iss_pct = cfg.get("retencao_iss", 0.05)
    extras = r.extras or {}
    retencao = extras.get("retencao_iss", round(r.faturamento * iss_pct, 2))
    saldo = extras.get("saldo_acumulado", r.prejuizo_acumulado_saida)

    linhas = [
        LinhaPrestacao("Receita Total de Manutenções", r.faturamento, "subtotal"),
        LinhaPrestacao(f"(-) Retenção ISS ({iss_pct*100:.0f}%)", -retencao, "deducao"),
        LinhaPrestacao("Total Líquido", r.subtotal, "subtotal"),
    ]
    for k, v in (r.custos or {}).items():
        if v:
            linhas.append(LinhaPrestacao(f"(-) {_custo_label(k)}", -v, "deducao"))
    linhas.append(LinhaPrestacao("Resultado", r.resultado, "destaque"))
    linhas.append(LinhaPrestacao("Saldo Acumulado", saldo, "total"))
    return Prestacao(linhas=linhas)


# ─── build_report_data ────────────────────────────────────────────────────────

def build_report_data(resultado, mes_ref: str,
                       patio_split_id: str = None,
                       patio_resultado: "ResultadoPatio | None" = None) -> ReportData:
    hoje = date.today().strftime("%d/%m/%Y")

    if patio_split_id is not None and patio_resultado is not None:
        return _build_patio(patio_resultado, patio_split_id, mes_ref, hoje)

    cfg = get_unit(resultado.unidade_id)
    tipo_rel = cfg.get("tipo_relatorio", "padrao")
    tipo_cal = cfg.get("tipo_calculo", "")

    repasse = resultado.aluguel_calculado + (resultado.extras or {}).get("repasse_outros", 0.0)

    unidade = UnidadeInfo(
        nome=cfg["nome"],
        contratante=cfg["contratante"],
        competencia=mes_ref,
        competencia_label=_label_mes(mes_ref),
        data_emissao=hoje,
        tipo_relatorio=tipo_rel,
    )

    cards = Cards(
        faturamento=resultado.faturamento,
        resultado=resultado.resultado,
        repasse=repasse,
    )

    lancamentos = _get_lancamentos_periodo(resultado.unidade_id, mes_ref)
    lancamentos = _com_mes_atual(lancamentos, resultado, mes_ref)
    comparativo = _comparativo_12m(lancamentos)
    n_meses = len(comparativo)

    import sys
    print(f"[reporter] {resultado.unidade_id}/{mes_ref}: {n_meses} mês(es) no comparativo",
          file=sys.stderr)

    if tipo_cal == "COM_FAIXAS":
        prestacao = _prestacao_faixas(resultado, cfg)
    elif tipo_cal == "COM_ALIQUOTA_SPLIT":
        prestacao = _prestacao_split(resultado, cfg)
    elif tipo_cal == "RESULTADO_SPLIT":
        prestacao = _prestacao_resultado_split(resultado, cfg)
    elif tipo_cal == "COM_ALIQUOTA_REPASSE_DUPLO":
        prestacao = _prestacao_repasse_duplo(resultado, cfg)
    elif tipo_cal == "PATIO_MANUTENCAO":
        prestacao = _prestacao_manutencao(resultado, cfg)
    else:
        prestacao = _prestacao_padrao(resultado, cfg)

    historico = _historico_anual(resultado.unidade_id, mes_ref, resultado)

    # Eventos — carregado da planilha por unidade (uid-específico)
    bloco_eventos = None
    if tipo_rel == "com_eventos":
        ev_data = eventos_parser.load_uid(mes_ref, resultado.unidade_id)
        if ev_data is None:
            # fallback para formato legado
            ev_data = eventos_parser.load(mes_ref)
        bloco_eventos = _build_bloco_eventos(mes_ref, ev_data)

    return ReportData(
        unidade=unidade,
        cards=cards,
        comparativo_12m=comparativo,
        prestacao=prestacao,
        historico=historico,
        bloco_eventos=bloco_eventos,
        comparativo_meses_disponiveis=n_meses,
    )


def _build_patio(r: ResultadoPatio, split_id: str, mes_ref: str, hoje: str) -> ReportData:
    split_r = r.real if split_id == "real" else r.maiojama
    split_nome = "REAL (53,52%)" if split_id == "real" else "MAIOJAMA (46,48%)"
    uid_hist = f"patio_{split_id}"

    repasse_outros = split_r.extras.get("repasse_outros", 0.0)
    repasse_total = split_r.aluguel_calculado + repasse_outros

    unidade = UnidadeInfo(
        nome=f"Pátio — {split_nome}",
        contratante="Trend Pátio 24",
        competencia=mes_ref,
        competencia_label=_label_mes(mes_ref),
        data_emissao=hoje,
        tipo_relatorio="com_receitas_extras",
    )

    cards = Cards(
        faturamento=split_r.faturamento,
        resultado=split_r.resultado,
        repasse=repasse_total,
    )

    lancamentos = _get_lancamentos_periodo(split_r.unidade_id, mes_ref)
    lancamentos = _com_mes_atual(lancamentos, split_r, mes_ref)
    comparativo = _comparativo_12m(lancamentos)
    n_meses_split = len(comparativo)

    linhas = [LinhaPrestacao("Receita Bruta", split_r.faturamento, "subtotal")]
    if split_r.aliquota_imposto:
        imposto_patio = round(split_r.faturamento - split_r.subtotal, 2)
        linhas.append(LinhaPrestacao(
            f"(-) Impostos ({split_r.aliquota_imposto*100:.2f}%)",
            -imposto_patio, "deducao"))
        linhas.append(LinhaPrestacao("Receita Líquida", split_r.subtotal, "subtotal"))
    if split_r.ponto_equilibrio:
        linhas.append(LinhaPrestacao("(-) Ponto de Equilíbrio", -split_r.ponto_equilibrio, "deducao"))
    for k, v in (split_r.custos or {}).items():
        if v:
            linhas.append(LinhaPrestacao(f"(-) {k.replace('_',' ').title()}", -v, "deducao"))
    linhas.append(LinhaPrestacao("Resultado", split_r.resultado, "destaque"))
    pct_aluguel = cfg_split.get("percentual_aluguel", 0.95) if (cfg_split := next(
        (s for s in get_unit("patio").get("splits", []) if s["id"] == split_id), None
    )) else 0.95
    linhas.append(LinhaPrestacao(f"Aluguel {int(pct_aluguel*100)}%", split_r.aluguel_calculado, "normal"))
    if repasse_outros:
        linhas.append(LinhaPrestacao("(+) Repasse Outros Serviços 50%", repasse_outros, "normal"))
    linhas.append(LinhaPrestacao("Total Repasse", repasse_total, "total"))

    prestacao = Prestacao(linhas=linhas)
    historico = _historico_anual(uid_hist, mes_ref, split_r)

    blocos = []
    os_data = r.outros_servicos
    if os_data and os_data.get("receitas_midia", 0):
        rep_key = "repasse_real" if split_id == "real" else "repasse_maiojama"
        nome_curto = "REAL" if split_id == "real" else "MAIOJAMA"
        pct_rateio_str = "53,52%" if split_id == "real" else "46,48%"
        bloco_os = BlocoReceita(
            titulo="Outros Serviços — Mídias",
            linhas=[
                LinhaPrestacao("Receita de Mídias", os_data["receitas_midia"], "subtotal"),
                LinhaPrestacao("(-) Impostos (14,25%)",
                               -round(os_data["receitas_midia"] - os_data["subtotal"], 2), "deducao"),
                LinhaPrestacao("Subtotal", os_data["subtotal"], "subtotal"),
                LinhaPrestacao("(-) Despesas", -sum(os_data.get("despesas", {}).values()), "deducao"),
                LinhaPrestacao("Resultado", os_data["resultado"], "destaque"),
            ],
            repasse_label=f"Repasse 50% ({split_nome})",
        )
        # Mesma fórmula de sempre (patio.py: repasse_total = resultado × 50%;
        # valor do contratante = repasse_total × percentual de rateio) — as
        # duas incidências continuam em etapas explícitas, mas a última linha
        # já traz o rótulo do rateio e o valor final juntos.
        bloco_os.linhas.append(LinhaPrestacao("Repasse 50%", os_data["repasse_total"], "normal"))
        bloco_os.linhas.append(LinhaPrestacao(f"Rateio {nome_curto} ({pct_rateio_str})", os_data[rep_key], "total"))
        blocos.append(bloco_os)

    car = r.carregadores
    if car and car.get("receita", 0):
        rep_key = "repasse_real" if split_id == "real" else "repasse_maiojama"
        bloco_car = BlocoReceita(
            titulo="Carregadores Elétricos",
            linhas=[
                LinhaPrestacao("Receita Carregadores", car["receita"], "subtotal"),
                LinhaPrestacao("(-) Taxa WEG (10%)", -car["taxa_weg"], "deducao"),
                LinhaPrestacao("(-) Custo Energia", -car["custo_energia"], "deducao"),
                LinhaPrestacao("Resultado", car["resultado"], "destaque"),
                LinhaPrestacao("Saldo Acumulado", car["saldo"], "normal"),
                LinhaPrestacao("Repasse 60%", car[rep_key], "total"),
            ],
        )
        blocos.append(bloco_car)

    return ReportData(
        unidade=unidade,
        cards=cards,
        comparativo_12m=comparativo,
        prestacao=prestacao,
        historico=historico,
        blocos_receitas=blocos,
        comparativo_meses_disponiveis=n_meses_split,
    )
