"""Tela de entrada de faturamento mensal."""
import tempfile, os
import streamlit as st
from app.engine import get_unidades_ativas, calcular, get_unit
from app.calculators.patio import ResultadoPatio
from app.models import get_saldo_acumulado
from app.parsers import eventos as eventos_parser
from app.parsers import faturamento as fat_parser


def fmt_br(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tela_entrada(mes_referencia: str):
    st.header("Entrada de Faturamento")
    st.caption(f"Mês de referência: **{mes_referencia}**")

    unidades = get_unidades_ativas(mes_referencia)

    if "faturamentos" not in st.session_state:
        st.session_state.faturamentos = {}
    if "extras_patio" not in st.session_state:
        st.session_state.extras_patio = {}
    if "resultados" not in st.session_state:
        st.session_state.resultados = {}
    if "eventos_parsed" not in st.session_state:
        st.session_state.eventos_parsed = None

    # ── Importação da planilha de faturamentos ───────────────────────────────
    _secao_importacao(mes_referencia, unidades)
    st.divider()

    # ── Upload de eventos (fora do form principal) ───────────────────────────
    unidades_eventos = [u for u in unidades if u.get("tipo_relatorio") == "com_eventos"]
    if unidades_eventos:
        _secao_eventos(mes_referencia)
        st.divider()

    with st.form("form_faturamento"):
        for u in unidades:
            uid = u["id"]
            if u["tipo_calculo"] == "PATIO_OPERACAO":
                _form_patio(u, uid)
            else:
                _form_simples(u, uid)

        submitted = st.form_submit_button("Calcular", type="primary", use_container_width=True)

    if submitted:
        _processar(unidades, mes_referencia)


def _secao_importacao(mes_ref: str, unidades: list):
    """Upload e preview da planilha de faturamentos da competência."""
    with st.expander("📥 Importar planilha de faturamentos", expanded=True):
        dados_disco = fat_parser.load(mes_ref)

        if dados_disco and st.session_state.get("fat_importado_confirmado"):
            n = len(dados_disco.get("uid_map", {}))
            total = sum(dados_disco["uid_map"].values())
            st.success(
                f"Planilha importada — **{n} unidades** mapeadas | "
                f"Total faturamento: R$ {total:,.2f}"
            )
            alertas = dados_disco.get("nao_mapeados", [])
            sem_fat = dados_disco.get("sem_fat", [])
            if alertas:
                st.warning(
                    f"⚠ {len(alertas)} linha(s) da planilha sem correspondência no YAML: "
                    + ", ".join(a["nome"] for a in alertas)
                )
            if sem_fat:
                sem_fat_nomes = []
                for uid in sem_fat:
                    try:
                        sem_fat_nomes.append(get_unit(uid)["nome"])
                    except Exception:
                        sem_fat_nomes.append(uid)
                st.warning(
                    f"⚠ {len(sem_fat)} unidade(s) do YAML sem faturamento na planilha: "
                    + ", ".join(sem_fat_nomes)
                )
            if st.button("Substituir planilha", key="btn_substituir_fat"):
                st.session_state.fat_importado_confirmado = False
                st.rerun()
            return

        # Carrega dados do disco se existirem mas não confirmados ainda
        if dados_disco and not st.session_state.get("fat_importado_confirmado"):
            _mostrar_preview_fat(dados_disco, mes_ref, unidades, from_disk=True)
            return

        arquivo = st.file_uploader(
            "Selecione a planilha de faturamentos (.xlsx)",
            type=["xlsx"],
            key="fat_upload",
            help="Planilha com nomes das unidades e faturamentos",
        )

        if arquivo is not None:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(arquivo.read())
                tmp_path = tmp.name
            try:
                parsed = fat_parser.parse_xlsx(tmp_path, unidades)
                fat_parser.salvar(mes_ref, parsed, tmp_path)
                st.session_state["_fat_parsed_preview"] = parsed
                _mostrar_preview_fat(parsed, mes_ref, unidades, from_disk=False)
            except Exception as e:
                st.error(f"Erro ao processar planilha: {e}")
            finally:
                os.unlink(tmp_path)
        elif st.session_state.get("_fat_parsed_preview"):
            _mostrar_preview_fat(st.session_state["_fat_parsed_preview"], mes_ref, unidades)
        else:
            st.info("Selecione a planilha para pré-preencher os valores do formulário.")


def _mostrar_preview_fat(parsed: dict, mes_ref: str, unidades: list, from_disk: bool = False):
    import pandas as pd

    uid_map = parsed.get("uid_map", {})
    nao_mapeados = parsed.get("nao_mapeados", [])
    sem_fat = parsed.get("sem_fat", [])
    sheet = parsed.get("sheet", "—")
    col_nome = parsed.get("col_nome", "?")
    col_fat  = parsed.get("col_fat",  "?")

    prefix = "Dados do disco" if from_disk else "Preview da importação"
    st.caption(f"{prefix} | Aba: **{sheet}** | Coluna nome: **{col_nome}** | Coluna valor: **{col_fat}**")

    # Tabela de mapeados
    rows = []
    for uid, fat in uid_map.items():
        try:
            nome_yaml = get_unit(uid)["nome"]
        except Exception:
            nome_yaml = uid
        rows.append({
            "Unidade (YAML)": nome_yaml,
            "ID": uid,
            "Faturamento": f"R$ {fat:,.2f}",
            "Status": "✅ Mapeado",
        })
    for a in nao_mapeados:
        rows.append({
            "Unidade (YAML)": f"— {a['nome']}",
            "ID": "—",
            "Faturamento": f"R$ {a['valor']:,.2f}",
            "Status": "⚠ Não encontrado no YAML",
        })
    for uid in sem_fat:
        try:
            nome_yaml = get_unit(uid)["nome"]
        except Exception:
            nome_yaml = uid
        rows.append({
            "Unidade (YAML)": nome_yaml,
            "ID": uid,
            "Faturamento": "—",
            "Status": "⚠ Sem faturamento na planilha",
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if uid_map:
        if st.button("Usar estes valores no formulário", type="primary", key="btn_confirmar_fat"):
            # Popula session_state.faturamentos
            for uid, fat in uid_map.items():
                st.session_state.faturamentos[uid] = fat
            st.session_state.fat_importado_confirmado = True
            st.session_state.pop("_fat_parsed_preview", None)
            st.rerun()


def _secao_eventos(mes_ref: str):
    """Upload e preview da planilha de eventos (para unidades com_eventos)."""
    with st.expander("📋 Planilha de Eventos (MDO)", expanded=True):
        # Verificar se já existe dados salvos em disco
        dados_disco = eventos_parser.load(mes_ref)
        if dados_disco:
            total = eventos_parser.get_total_competencia(dados_disco, mes_ref)
            ev_mes = eventos_parser.get_eventos_competencia(dados_disco, mes_ref)
            st.success(f"Eventos carregados do disco — {len(ev_mes)} eventos | Total: R$ {total:,.2f}")
            if st.button("Substituir planilha de eventos", key="btn_substituir_ev"):
                st.session_state.eventos_parsed = None
                st.session_state.pop("eventos_arquivo_processado", None)
                st.rerun()
            if st.session_state.eventos_parsed is None:
                st.session_state.eventos_parsed = dados_disco
            return

        arquivo = st.file_uploader(
            "Selecione a planilha de eventos (.xlsx)",
            type=["xlsx"],
            key="eventos_upload",
            help="Planilha com abas 'Eventos' e 'Resumo Mensal'",
        )

        if arquivo is not None:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(arquivo.read())
                tmp_path = tmp.name
            try:
                parsed = eventos_parser.parse_xlsx(tmp_path)
                eventos_parser.salvar(mes_ref, parsed, tmp_path)
                st.session_state.eventos_parsed = parsed

                # Preview
                total = eventos_parser.get_total_competencia(parsed, mes_ref)
                ev_mes = eventos_parser.get_eventos_competencia(parsed, mes_ref)
                st.success(f"Planilha processada — {len(ev_mes)} eventos na competência | Total: R$ {total:,.2f}")

                if ev_mes:
                    import pandas as pd
                    df = pd.DataFrame([{
                        "Data": e["data"], "Evento": e["evento"],
                        "Horário": e["horario"], "Extras": e["qtd_extras"],
                        "Valor Total": f"R$ {e['valor_total']:,.2f}",
                    } for e in ev_mes])
                    st.dataframe(df, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Erro ao processar planilha: {e}")
            finally:
                os.unlink(tmp_path)
        else:
            st.info("Nenhuma planilha carregada. Os blocos de eventos não serão gerados no PDF.")


def _form_simples(u: dict, uid: str):
    with st.expander(f"**{u['nome']}**", expanded=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            val = st.number_input(
                "Faturamento total (R$)",
                min_value=0.0, step=100.0, format="%.2f",
                key=f"fat_{uid}",
                value=st.session_state.faturamentos.get(uid, 0.0),
            )
        with col2:
            st.markdown("")
            if u["tipo_calculo"] == "COM_ALIQUOTA_CUMUL":
                saldo = get_saldo_acumulado(uid)
                st.metric("Prejuízo acumulado", fmt_br(saldo))
            elif u["tipo_calculo"] == "PATIO_MANUTENCAO":
                saldo = get_saldo_acumulado(uid)
                st.metric("Saldo acumulado (mês ant.)", fmt_br(saldo))

        # custos variáveis editáveis para unidades com custos mensais
        if u.get("custos_mensais"):
            st.markdown("**Custos mensais:**")
            cols = st.columns(len(u["custos_mensais"]))
            for i, (k, v) in enumerate(u["custos_mensais"].items()):
                with cols[i]:
                    st.number_input(k.replace("_", " ").title(),
                                    min_value=0.0, step=10.0, format="%.2f",
                                    value=float(v), key=f"custo_{uid}_{k}")

        st.session_state.faturamentos[uid] = val


def _form_patio(u: dict, uid: str):
    with st.expander("**Pátio (Trend Pátio 24)**", expanded=True):
        st.markdown("**Operação Estacionamento**")
        fat = st.number_input("Faturamento total estacionamento (R$)",
                              min_value=0.0, step=100.0, format="%.2f",
                              key="fat_patio")

        st.markdown("**Outros Serviços (Mídias)**")
        c1, c2, c3 = st.columns(3)
        with c1:
            midia = st.number_input("Receita de Mídias", min_value=0.0, step=100.0, format="%.2f", key="patio_midia")
        with c2:
            eq = st.number_input("Invest. Equipamentos", min_value=0.0, step=100.0, format="%.2f", key="patio_equip")
        with c3:
            lona = st.number_input("Troca de Lona", min_value=0.0, step=100.0, format="%.2f", key="patio_lona")

        st.markdown("**Carregadores Elétricos**")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            rec_car = st.number_input("Receita carregadores", min_value=0.0, step=100.0, format="%.2f", key="patio_rec_car")
        with c2:
            en = st.number_input("Custo energia", min_value=0.0, step=10.0, format="%.2f", key="patio_energia")
        with c3:
            inv_car = st.number_input("Investimento inicial", min_value=0.0, step=100.0, format="%.2f", key="patio_inv_car")
        with c4:
            saldo_car = st.number_input("Saldo mês anterior", step=100.0, format="%.2f", key="patio_saldo_car")

        st.markdown("**Custos variáveis mensais**")
        splits_cfg = {s["id"]: s for s in u["splits"]}
        c1, c2 = st.columns(2)
        with c1:
            st.caption("REAL")
            cond_real = st.number_input("Condomínio REAL", min_value=0.0, step=10.0, format="%.2f", key="patio_cond_real")
        with c2:
            st.caption("MAIOJAMA")
            cond_maiojama = st.number_input("Condomínio MAIOJAMA", min_value=0.0, step=10.0, format="%.2f", key="patio_cond_maiojama")
            iptu_maiojama = st.number_input("IPTU MAIOJAMA", min_value=0.0, step=10.0, format="%.2f", key="patio_iptu_maiojama")

        st.session_state.faturamentos["patio"] = fat
        st.session_state.extras_patio = {
            "receitas_midia": midia,
            "outros_custos_midia": {"investimentos_equipamentos": eq, "troca_de_lona": lona},
            "receita_carregadores": rec_car,
            "custo_energia_carregadores": en,
            "investimento_inicial_carregadores": inv_car,
            "saldo_carregadores": saldo_car,
            "custos_variaveis_real": {"condominio": cond_real},
            "custos_variaveis_maiojama": {"condominio": cond_maiojama, "iptu": iptu_maiojama},
        }


def _processar(unidades: list, mes: str):
    resultados = {}
    erros = []

    # Custo de eventos da competência (se disponível)
    eventos_parsed = st.session_state.get("eventos_parsed")

    for u in unidades:
        uid = u["id"]
        fat = st.session_state.faturamentos.get(uid, 0.0)
        if fat == 0.0:
            continue
        try:
            custos_extras = {}
            # Custos mensais fixos (condomínio etc.)
            for k2, v in (u.get("custos_mensais") or {}).items():
                custos_extras[k2] = st.session_state.get(f"custo_{uid}_{k2}", float(v))

            # Custos de eventos (apenas para unidades com_eventos)
            if u.get("tipo_relatorio") == "com_eventos" and eventos_parsed:
                total_ev = eventos_parser.get_total_competencia(eventos_parsed, mes)
                if total_ev > 0:
                    custos_extras["custos_eventos"] = total_ev

            custos_extras = custos_extras or None

            if u["tipo_calculo"] == "PATIO_OPERACAO":
                resultado = calcular("patio", mes, fat,
                                     extras_patio=st.session_state.extras_patio)
            else:
                resultado = calcular(uid, mes, fat, custos_extras=custos_extras)

            resultados[uid] = resultado
        except Exception as e:
            erros.append(f"{u['nome']}: {e}")

    st.session_state.resultados = resultados

    if erros:
        for e in erros:
            st.error(e)
    if resultados:
        st.success(f"{len(resultados)} unidade(s) calculada(s). Vá para **Revisão** para conferir.")
