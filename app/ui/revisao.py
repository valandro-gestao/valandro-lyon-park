"""Tela de revisão e aprovação dos cálculos."""
import streamlit as st
from app.calculators.patio import ResultadoPatio
from app.models import ResultadoUnidade, salvar_lancamento, init_db
from app.engine import get_unit


def fmt(v: float) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {s}" if v < 0 else f"R$ {s}"


def tela_revisao(mes_referencia: str):
    st.header("Revisão dos Cálculos")

    resultados = st.session_state.get("resultados", {})
    if not resultados:
        st.info("Nenhum cálculo disponível. Acesse **Entrada** e calcule primeiro.")
        return

    for uid, resultado in resultados.items():
        if isinstance(resultado, ResultadoPatio):
            _exibir_patio(resultado, mes_referencia)
        else:
            _exibir_unidade(uid, resultado, mes_referencia)

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Aprovar todos e salvar", type="primary", use_container_width=True):
            _aprovar_todos(resultados, mes_referencia)
    with col2:
        if st.button("Gerar Relatórios PDF", use_container_width=True):
            st.session_state.ir_para = "relatorios"
            st.rerun()


def _exibir_unidade(uid: str, r: ResultadoUnidade, mes: str):
    cfg = get_unit(uid)
    with st.expander(f"**{cfg['nome']}** — Aluguel: {fmt(r.aluguel_calculado)}", expanded=True):
        linhas = cfg.get("relatorio", {}).get("linhas", [])
        dados = _montar_dados(r, linhas)
        for label, valor in dados:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(label)
            with col2:
                st.write(fmt(valor) if isinstance(valor, float) else valor)


def _exibir_patio(r: ResultadoPatio, mes: str):
    with st.expander("**Pátio — Trend Pátio 24**", expanded=True):
        for split_nome, split_r in [("REAL (53,52%)", r.real), ("MAIOJAMA (46,48%)", r.maiojama)]:
            st.markdown(f"**{split_nome}** — Aluguel base: {fmt(split_r.aluguel_calculado)}")
            total = split_r.aluguel_calculado + split_r.extras.get("repasse_outros", 0.0)
            cols = st.columns(4)
            cols[0].metric("Faturamento", fmt(split_r.faturamento))
            cols[1].metric("Subtotal (após alíq.)", fmt(split_r.subtotal))
            cols[2].metric("Resultado", fmt(split_r.resultado))
            cols[3].metric("Total Repasse", fmt(total))

        if r.outros_servicos:
            st.markdown("**Outros Serviços (Mídias)**")
            os = r.outros_servicos
            c1, c2, c3 = st.columns(3)
            c1.metric("Receita Mídias", fmt(os["receitas_midia"]))
            c2.metric("Resultado", fmt(os["resultado"]))
            c3.metric("Repasse Total (50%)", fmt(os["repasse_total"]))

        if r.carregadores:
            st.markdown("**Carregadores Elétricos**")
            car = r.carregadores
            c1, c2, c3 = st.columns(3)
            c1.metric("Receita", fmt(car["receita"]))
            c2.metric("Saldo acumulado", fmt(car["saldo"]))
            c3.metric("Repasse (60%)", fmt(car["repasse_total"]))

        if r.manutencao:
            st.markdown("**Manutenções**")
            man = r.manutencao
            c1, c2, c3 = st.columns(3)
            c1.metric("Receita líquida", fmt(man["total_liquido"]))
            c2.metric("Resultado", fmt(man["resultado"]))
            c3.metric("Saldo acumulado", fmt(man["saldo_acumulado"]))


def _montar_dados(r: ResultadoUnidade, linhas: list) -> list:
    mapa = {
        "faturamento": ("Total Faturamento", r.faturamento),
        "aliquota": ("Alíquota Imposto", f"{r.aliquota_imposto*100:.2f}%"),
        "subtotal": ("Subtotal", r.subtotal),
        "pe": ("Ponto de Equilíbrio", r.ponto_equilibrio),
        "resultado": ("Resultado", r.resultado),
        "prejuizo": ("Prejuízo Acumulado", r.prejuizo_acumulado_entrada),
        "aluguel": ("Aluguel a Pagar", r.aluguel_calculado),
        "taxa_admin": ("Taxa de Administração", r.extras.get("taxa_admin", 0.0)),
        "adicional": ("Adicional Fixo", r.extras.get("adicional_fixo", 0.0)),
    }
    for k, v in r.custos.items():
        mapa[k] = (k.replace("_", " ").title(), v)

    return [mapa[l] for l in linhas if l in mapa]


def _aprovar_todos(resultados: dict, mes: str):
    from app import run_manager as rm
    init_db()
    count = 0
    for uid, resultado in resultados.items():
        if isinstance(resultado, ResultadoPatio):
            for split_id, r in [("patio_real", resultado.real), ("patio_maiojama", resultado.maiojama)]:
                r.status = "aprovado"
                r.mes_referencia = mes
                salvar_lancamento(r)
                unit_run = rm.get_unit_run(mes, split_id)
                if unit_run["status"] == "gerado":
                    rm.mark_approved(mes, split_id)
            count += 2
        else:
            resultado.status = "aprovado"
            resultado.mes_referencia = mes
            salvar_lancamento(resultado)
            unit_run = rm.get_unit_run(mes, uid)
            if unit_run["status"] == "gerado":
                rm.mark_approved(mes, uid)
            count += 1
    st.success(f"{count} lançamento(s) aprovado(s) e salvos. Acesse **Relatórios** para gerar os PDFs.")
