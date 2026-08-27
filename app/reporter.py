"""
Motor de montagem do ReportData.
"""
from __future__ import annotations
import json
from datetime import date, datetime
from app.report_data import (
    ReportData, UnidadeInfo, Cards, ComparativoMes,
    LinhaPrestacao, Prestacao, Historico,
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


def _get_lancamentos_ultimos_12(unidade_id: str, mes_ref: str) -> list[dict]:
    ano, mes = int(mes_ref[:4]), int(mes_ref[5:7])
    meses = []
    for i in range(12):
        m = mes - i
        a = ano
        while m <= 0:
            m += 12
            a -= 1
        meses.append(f"{a}-{m:02d}")

    with get_db() as conn:
        placeholders = ",".join("?" * len(meses))
        rows = conn.execute(f"""
            SELECT mes_referencia, resultado_json
            FROM lancamentos
            WHERE unidade_id=? AND mes_referencia IN ({placeholders})
            ORDER BY mes_referencia DESC
        """, [unidade_id] + meses).fetchall()

    return [{"mes": r["mes_referencia"], **json.loads(r["resultado_json"])} for r in rows]


def _comparativo_12m(lancamentos: list[dict]) -> list[ComparativoMes]:
    result = []
    for i, l in enumerate(lancamentos):
        fat = l.get("faturamento", 0.0)
        res = l.get("resultado", 0.0)
        repasse = l.get("aluguel_calculado", 0.0)
        extras = l.get("extras") or {}
        if isinstance(extras, dict):
            repasse += extras.get("repasse_outros", 0.0)

        if i + 1 < len(lancamentos):
            prev = lancamentos[i + 1]
            var_fat = _pct_var(fat, prev.get("faturamento", 0.0))
            var_res = _pct_var(res, prev.get("resultado", 0.0))
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


def _historico_anual(unidade_id: str, linhas_cfg: list[str]) -> Historico:
    raw = get_historico_anual(unidade_id)
    if not raw:
        return Historico(anos=[], indicadores=[])

    anos = [e["ano"] for e in raw]
    label_map = {
        "faturamento":  "Faturamento",
        "subtotal":     "Receita Líquida",
        "resultado":    "Resultado",
        "aluguel":      "Repasse",
        "aluguel_calculado": "Repasse",
        "prejuizo":     "Prejuízo Acumulado",
        "ponto_equilibrio": "Ponto de Equilíbrio",
    }
    campo_map = {
        "faturamento": "faturamento",
        "subtotal":    "subtotal",
        "resultado":   "resultado",
        "aluguel":     "aluguel_calculado",
        "prejuizo":    "prejuizo_acumulado_entrada",
        "pe":          "ponto_equilibrio",
    }

    indicadores = []
    seen = set()
    for cfg_key in linhas_cfg:
        campo = campo_map.get(cfg_key, cfg_key)
        label = label_map.get(cfg_key, cfg_key.replace("_", " ").title())
        if label in seen:
            continue
        seen.add(label)
        valores = [e.get(campo) for e in raw]
        if any(v is not None and v != 0 for v in valores):
            indicadores.append({"label": label, "valores": valores})

    return Historico(anos=anos, indicadores=indicadores)


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
    linhas_cfg = cfg.get("relatorio", {}).get("linhas", [])

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

    lancamentos = _get_lancamentos_ultimos_12(resultado.unidade_id, mes_ref)
    comparativo = _comparativo_12m(lancamentos)
    n_meses = len(lancamentos)

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

    historico = _historico_anual(resultado.unidade_id, linhas_cfg)

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

    lancamentos = _get_lancamentos_ultimos_12(split_r.unidade_id, mes_ref)
    comparativo = _comparativo_12m(lancamentos)
    n_meses_split = len(lancamentos)

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
    historico = _historico_anual(uid_hist, ["faturamento", "subtotal", "resultado", "aluguel"])

    blocos = []
    os_data = r.outros_servicos
    if os_data and os_data.get("receitas_midia", 0):
        rep_key = "repasse_real" if split_id == "real" else "repasse_maiojama"
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
        bloco_os.linhas.append(LinhaPrestacao(
            f"Repasse 50% ({split_nome})", os_data[rep_key], "total"))
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
