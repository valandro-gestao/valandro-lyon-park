#!/usr/bin/env python3
"""
Diagnóstico READ-ONLY de produção — Repasse x Parcela Fixa x Saldo a Pagar
das unidades RESULTADO_SPLIT (Medcenter e Viva Open Mall).

CONTEXTO. A calculadora RESULTADO_SPLIT grava o SALDO A PAGAR em
`lancamentos.aluguel_calculado`, e o relatório lê esse campo como "Repasse".
O repasse real ao contratante (`extras.resultado_contratante`), a parcela fixa
(`extras.parcela_fixa`) e o saldo (`extras.saldo_a_pagar`) só existem nos
meses calculados pelo sistema; o histórico restaurado de planilhas
(até 2026-05) tem `extras` vazio. Este script mostra, mês a mês, o que seria
possível reconstruir — sem reconstruir nada.

O QUE ELE MOSTRA
  1. VIGÊNCIAS em produção (percentual_contratante, percentual_operador,
     parcela_fixa, despesas_fixas, aliquota_imposto) e sua comparação com a
     referência da cópia local de desenvolvimento (16/10/2026): linhas só em
     produção, linhas só na referência, e anomalias (fim < início, sobreposição).
  2. TODOS os lançamentos das unidades: percentual aplicado (de `extras` se
     existir, senão da vigência que cobre a competência), repasse calculado
     (round(resultado x percentual, 2), a mesma fórmula do calculador),
     parcela fixa derivada (repasse - saldo persistido), saldo persistido e se
     há `extras`.
  3. REGIMES de parcela fixa derivada (grupos de meses consecutivos com a mesma
     parcela) e comparação com a vigência de `parcela_fixa` — é aqui que a
     necessidade de corrigir vigências históricas do Viva Open Mall aparece.
  4. Valores ATÍPICOS: parcela fora de qualquer regime (ex.: Viva abr/2023),
     divergência de centavos (ex.: Medcenter fev/2026, R$ 0,08), saldo <= 0,
     `extras` ausentes/parciais/divergentes, percentual fora do esperado.
  5. Histórico anual PROJETADO (o que o PDF mostraria somando `lancamentos`) e
     comparação com o cache `historico_anual`.

Só faz SELECT. Abre o banco em modo read-only (URI `?mode=ro` do SQLite +
`PRAGMA query_only=ON` — o próprio SQLite recusa qualquer escrita nessa
conexão) e nunca importa `app.*` (sem init_db()/seed/efeito colateral de
import). Só biblioteca padrão — roda com o `python3` do sistema. NÃO corrige,
NÃO migra e NÃO grava nada, nem arquivo: a saída é só stdout.

Uso (Render Shell):
    python3 scripts/diagnostico_split_repasse.py > /tmp/diag_split.txt; \
        sed -n '/SINALIZADORES/,$p' /tmp/diag_split.txt
    # tabela mensal em TSV (para colar numa planilha):
    python3 scripts/diagnostico_split_repasse.py --tsv > /tmp/diag_split.tsv

Por padrão lê de $DATA_DIR/db.sqlite (em produção /mnt/data) e analisa todas as
unidades com tipo_calculo = RESULTADO_SPLIT. Opções:
    python3 scripts/diagnostico_split_repasse.py [/caminho/db.sqlite] \
        [--unidades medcenter,viva_open_mall] [--tsv]
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

# ── referências embutidas (cópia local de desenvolvimento, 16/10/2026) ───────
PARAMETROS = ("percentual_contratante", "percentual_operador", "parcela_fixa",
              "despesas_fixas", "aliquota_imposto")
UNIDADES_PADRAO = ("medcenter", "viva_open_mall")

# (parametro, competencia_inicio, competencia_fim|None, valor)
REFERENCIA_VIGENCIAS = {
    "medcenter": [
        ("aliquota_imposto", "2020-01", None, 0.1425),
        ("despesas_fixas", "2020-01", None, 42332.29),
        ("parcela_fixa", "2020-01", None, 80000.0),
        ("percentual_contratante", "2020-01", "2026-06", 0.75),
        ("percentual_contratante", "2026-07", None, 0.85),
        ("percentual_operador", "2020-01", None, 0.15),
    ],
    "viva_open_mall": [
        ("aliquota_imposto", "2020-01", None, 0.1425),
        ("despesas_fixas", "2020-01", None, 26626.96),
        ("parcela_fixa", "2020-01", None, 32533.36),
        ("percentual_contratante", "2020-01", None, 0.85),
        ("percentual_operador", "2020-01", None, 0.15),
    ],
}

# Percentual do contratante esperado por competência (apurado nos dados locais:
# com ele a parcela derivada fecha em valor redondo em 100% dos meses).
# (de, ate, valor) — limites inclusivos.
PERCENTUAL_ESPERADO = {
    "medcenter": [("0000-00", "2026-06", 0.75), ("2026-07", "9999-99", 0.85)],
    "viva_open_mall": [("0000-00", "9999-99", 0.85)],
}

PRIMEIRA_COMPETENCIA_DO_SISTEMA = "2026-06"   # a partir daqui o Lyon Reports calcula
TOL_CENTAVO = 0.011      # até 1 centavo de arredondamento é normal
LIMITE_MESMO_REGIME = 1.00   # meses cuja parcela difere menos que isto = mesmo regime
MIN_MESES_REGIME = 3
LISTAR_ATE = 40


# ── utilitários ──────────────────────────────────────────────────────────────
def brl(v) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{s}" if v < 0 else s


def pct(v) -> str:
    return "—" if v is None else f"{v * 100:.2f}%".replace(".", ",")


def linha(char="=", n=110):
    print(char * n)


def titulo(txt):
    print()
    linha()
    print(txt)
    linha()


def jval(v):
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return v


def num(v):
    try:
        return float(jval(v))
    except (TypeError, ValueError):
        return None


def conectar_ro(caminho: Path) -> sqlite3.Connection:
    if not caminho.exists():
        sys.exit(f"Banco não encontrado em {str(caminho)!r}. Passe o caminho correto como argumento.")
    conn = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def tabela_existe(conn, nome: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)).fetchone() is not None


def mes_anterior(mes: str) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    m -= 1
    if m == 0:
        a, m = a - 1, 12
    return f"{a:04d}-{m:02d}"


def proximo_mes(mes: str) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    m += 1
    if m == 13:
        a, m = a + 1, 1
    return f"{a:04d}-{m:02d}"


# ── descoberta de unidades ───────────────────────────────────────────────────
def descobrir_unidades(conn, forcadas: list[str] | None) -> tuple[list[str], list[str]]:
    avisos = []
    if forcadas:
        return forcadas, avisos
    if tabela_existe(conn, "unidades"):
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM unidades WHERE tipo_calculo='RESULTADO_SPLIT' ORDER BY id")]
        if set(ids) != set(UNIDADES_PADRAO):
            avisos.append(f"unidades RESULTADO_SPLIT encontradas {ids} diferem das esperadas {list(UNIDADES_PADRAO)}")
        return ids, avisos
    avisos.append("tabela `unidades` ausente — usando as unidades padrão")
    return list(UNIDADES_PADRAO), avisos


# ── vigências ────────────────────────────────────────────────────────────────
def ler_vigencias(conn, uid: str) -> list[dict]:
    if not tabela_existe(conn, "parametros_vigentes"):
        return []
    marcas = ",".join("?" * len(PARAMETROS))
    return [dict(r) for r in conn.execute(
        f"SELECT id, parametro, valor, competencia_inicio, competencia_fim, alterado_em, alterado_por "
        f"FROM parametros_vigentes WHERE unidade_id=? AND parametro IN ({marcas}) "
        f"ORDER BY parametro, competencia_inicio, id", (uid, *PARAMETROS))]


def vigencia_cobrindo(vigs: list[dict], parametro: str, mes: str):
    """Mesma regra de app.models.salvar_parametros: a vigência que efetivamente
    cobre `mes` (início <= mes <= fim ou aberta), a de início mais recente."""
    cand = [v for v in vigs if v["parametro"] == parametro
            and v["competencia_inicio"] <= mes
            and (v["competencia_fim"] is None or v["competencia_fim"] >= mes)]
    return max(cand, key=lambda v: (v["competencia_inicio"], v["id"])) if cand else None


def anomalias_vigencia(vigs: list[dict]) -> list[tuple[str, str]]:
    achados = []
    for p in PARAMETROS:
        linhas_p = [v for v in vigs if v["parametro"] == p]
        for v in linhas_p:
            if v["competencia_fim"] is not None and v["competencia_fim"] < v["competencia_inicio"]:
                achados.append(("VIGENCIA_CORROMPIDA",
                                f"{p}: fim {v['competencia_fim']} < início {v['competencia_inicio']} "
                                f"(valor {jval(v['valor'])}, por {v['alterado_por']})"))
        ordenadas = sorted(linhas_p, key=lambda v: (v["competencia_inicio"], v["id"]))
        for a, b in zip(ordenadas, ordenadas[1:]):
            if a["competencia_fim"] is None or a["competencia_fim"] >= b["competencia_inicio"]:
                achados.append(("VIGENCIA_SOBREPOSTA",
                                f"{p}: {a['competencia_inicio']}→{a['competencia_fim'] or 'aberta'} "
                                f"({jval(a['valor'])}) sobrepõe {b['competencia_inicio']}→"
                                f"{b['competencia_fim'] or 'aberta'} ({jval(b['valor'])})"))
    return achados


def comparar_com_referencia(uid: str, vigs: list[dict]):
    ref = REFERENCIA_VIGENCIAS.get(uid)
    if ref is None:
        return None, None
    def chave(p, i, f, v):
        return (p, i, f, round(float(v), 4))
    prod = {chave(v["parametro"], v["competencia_inicio"], v["competencia_fim"], num(v["valor"]) if num(v["valor"]) is not None else 0.0): v
            for v in vigs}
    refs = {chave(*r): r for r in ref}
    so_prod = [prod[k] for k in prod if k not in refs]
    so_ref = [refs[k] for k in refs if k not in prod]
    return so_prod, so_ref


# ── análise mensal ───────────────────────────────────────────────────────────
def percentual_esperado(uid: str, mes: str):
    for de, ate, val in PERCENTUAL_ESPERADO.get(uid, []):
        if de <= mes <= ate:
            return val
    return None


def analisar_unidade(conn, uid: str, vigs: list[dict]) -> list[dict]:
    rows = conn.execute(
        "SELECT mes_referencia, status, faturamento, resultado_json FROM lancamentos "
        "WHERE unidade_id=? ORDER BY mes_referencia", (uid,)).fetchall()
    out = []
    for r in rows:
        try:
            d = json.loads(r["resultado_json"])
        except json.JSONDecodeError:
            d = {}
        extras = d.get("extras") or {}
        mes = r["mes_referencia"]
        res = num(d.get("resultado"))
        saldo = num(d.get("aluguel_calculado"))
        chaves_necessarias = ("resultado_contratante", "parcela_fixa", "saldo_a_pagar")
        tem_extras = bool(extras)
        faltando = [k for k in chaves_necessarias if extras.get(k) is None] if tem_extras else []

        vig = vigencia_cobrindo(vigs, "percentual_contratante", mes)
        pct_vig = num(vig["valor"]) if vig else None
        pct_ext = num(extras.get("percentual_contratante")) if tem_extras else None
        pct_usado, origem = (pct_ext, "extras") if pct_ext is not None else (pct_vig, "vigência" if vig else None)

        repasse = round(res * pct_usado, 2) if (res is not None and pct_usado is not None) else None
        # Saldo <= 0 (ou ausente): a derivação repasse - saldo não vale (a extração legada
        # chegou a usar max(0, valor)) — não se deriva parcela, só se sinaliza.
        parcela = (round(repasse - saldo, 2)
                   if (repasse is not None and saldo is not None and saldo > 0) else None)

        out.append({
            "uid": uid, "mes": mes, "status": r["status"], "faturamento": num(r["faturamento"]),
            "resultado": res, "saldo": saldo, "tem_extras": tem_extras, "faltando": faltando,
            "extras": extras, "pct": pct_usado, "pct_origem": origem, "pct_vig": pct_vig,
            "repasse": repasse, "parcela": parcela, "flags": [],
        })
    return out


def detectar_regimes(meses: list[dict]):
    """Agrupa meses consecutivos (na ordem cronológica) cuja parcela derivada
    difere menos que LIMITE_MESMO_REGIME da do primeiro mês do grupo."""
    grupos, atual = [], []
    for m in meses:
        if m["parcela"] is None:
            continue
        if atual and abs(m["parcela"] - atual[0]["parcela"]) <= LIMITE_MESMO_REGIME:
            atual.append(m)
        else:
            if atual:
                grupos.append(atual)
            atual = [m]
    if atual:
        grupos.append(atual)
    regimes = []
    for g in grupos:
        if len(g) >= MIN_MESES_REGIME:
            cont = Counter(x["parcela"] for x in g)
            nominal = sorted(cont.items(), key=lambda kv: (-kv[1], abs(kv[0] - g[0]["parcela"])))[0][0]
            regimes.append({"de": g[0]["mes"], "ate": g[-1]["mes"], "n": len(g), "nominal": nominal, "meses": g})
        else:
            for x in g:
                x["flags"].append(("PARCELA_ATIPICA", f"parcela derivada {brl(x['parcela'])} fora de qualquer regime "
                                                      f"(grupo de {len(g)} mês(es) < {MIN_MESES_REGIME})"))
    return regimes


def marcar_flags(uid: str, meses: list[dict], regimes: list[dict]):
    for r in regimes:
        for m in r["meses"]:
            delta = round(m["parcela"] - r["nominal"], 2)
            if abs(delta) > TOL_CENTAVO:
                m["flags"].append(("DIVERGENCIA_CENTAVOS",
                                   f"parcela derivada {brl(m['parcela'])} vs regime {brl(r['nominal'])} "
                                   f"(Δ R$ {brl(delta)})"))
    anterior = None
    for m in meses:
        if anterior is not None and proximo_mes(anterior) != m["mes"]:
            m["flags"].append(("LACUNA", f"sem lançamento entre {anterior} e {m['mes']}"))
        anterior = m["mes"]

        if m["pct"] is None:
            m["flags"].append(("SEM_PERCENTUAL", "nenhuma vigência de percentual_contratante cobre a competência"))
        esperado = percentual_esperado(uid, m["mes"])
        if esperado is not None and m["pct"] is not None and abs(m["pct"] - esperado) > 1e-9:
            m["flags"].append(("PERCENTUAL_FORA_DO_ESPERADO",
                               f"{pct(m['pct'])} ({m['pct_origem']}) vs esperado {pct(esperado)}"))
        if m["pct_origem"] == "extras" and m["pct_vig"] is not None and abs(m["pct"] - m["pct_vig"]) > 1e-9:
            m["flags"].append(("PERCENTUAL_EXTRAS_DIFERE_DA_VIGENCIA",
                               f"extras {pct(m['pct'])} vs vigência {pct(m['pct_vig'])}"))
        if m["saldo"] is None or m["saldo"] <= 0:
            m["flags"].append(("SALDO_NAO_POSITIVO", f"aluguel_calculado={brl(m['saldo'])} — a derivação da parcela não vale"))
        if m["tem_extras"] and m["faltando"]:
            m["flags"].append(("EXTRAS_PARCIAIS", f"extras sem {', '.join(m['faltando'])}"))
        if not m["tem_extras"] and m["mes"] >= PRIMEIRA_COMPETENCIA_DO_SISTEMA:
            m["flags"].append(("SEM_EXTRAS_POS_JUN2026", "competência calculada pelo sistema sem extras"))
        if m["tem_extras"]:
            ex = m["extras"]
            diffs = []
            if num(ex.get("resultado_contratante")) is not None and m["repasse"] is not None \
                    and abs(num(ex["resultado_contratante"]) - m["repasse"]) > TOL_CENTAVO:
                diffs.append(f"resultado_contratante extras {brl(num(ex['resultado_contratante']))} vs calculado {brl(m['repasse'])}")
            if num(ex.get("saldo_a_pagar")) is not None and m["saldo"] is not None \
                    and abs(num(ex["saldo_a_pagar"]) - m["saldo"]) > TOL_CENTAVO:
                diffs.append(f"extras.saldo_a_pagar {brl(num(ex['saldo_a_pagar']))} vs aluguel_calculado {brl(m['saldo'])}")
            if num(ex.get("parcela_fixa")) is not None and m["parcela"] is not None \
                    and abs(num(ex["parcela_fixa"]) - m["parcela"]) > TOL_CENTAVO:
                diffs.append(f"extras.parcela_fixa {brl(num(ex['parcela_fixa']))} vs derivada {brl(m['parcela'])}")
            for dtext in diffs:
                m["flags"].append(("DIVERGE_EXTRAS", dtext))
        if m["status"] != "aprovado":
            m["flags"].append(("STATUS_NAO_APROVADO", f"lancamentos.status={m['status']!r}"))
        m["flags"].append(("COM_EXTRAS" if m["tem_extras"] else "SEM_EXTRAS_LEGADO", ""))


def vigencia_parcela_vs_regimes(vigs: list[dict], regimes: list[dict]):
    achados = []
    for r in regimes:
        divergentes = []
        for m in r["meses"]:
            v = vigencia_cobrindo(vigs, "parcela_fixa", m["mes"])
            valor = num(v["valor"]) if v else None
            if valor is None or abs(valor - r["nominal"]) > TOL_CENTAVO:
                divergentes.append((m["mes"], valor))
        if divergentes:
            valores = sorted({d[1] for d in divergentes}, key=lambda x: (x is None, x))
            achados.append({
                "regime": r, "n_div": len(divergentes), "primeiro": divergentes[0][0], "ultimo": divergentes[-1][0],
                "vigencia": ", ".join("sem vigência" if x is None else brl(x) for x in valores),
            })
    return achados


# ── impressão ────────────────────────────────────────────────────────────────
def imprimir_vigencias(uid, vigs, so_prod, so_ref, anomalias):
    print(f"\n[{uid}] vigências em produção ({len(vigs)} linha(s)):")
    if not vigs:
        print("  (nenhuma)")
    for v in vigs:
        print(f"  [id={v['id']:>5}] {v['parametro']:<24} {v['competencia_inicio']} → {v['competencia_fim'] or 'ABERTA':<8} "
              f"valor={jval(v['valor'])!s:<12} alterado_em={v['alterado_em']} por={v['alterado_por']}")
    if so_prod is None:
        print("  (sem referência local embutida para esta unidade — comparação não feita)")
    else:
        print(f"  vs referência local: {len(so_prod)} linha(s) SÓ em produção, {len(so_ref)} SÓ na referência")
        for v in so_prod:
            print(f"    + produção: {v['parametro']:<24} {v['competencia_inicio']} → {v['competencia_fim'] or 'ABERTA':<8} "
                  f"valor={jval(v['valor'])} por={v['alterado_por']}")
        for p, i, f, val in so_ref:
            print(f"    - referência: {p:<24} {i} → {f or 'ABERTA':<8} valor={val}")
    for classe, texto in anomalias:
        print(f"    !! {classe}: {texto}")


def imprimir_meses(uid, meses):
    print(f"\n[{uid}] {len(meses)} lançamento(s):")
    print(f"  {'Mês':<8}{'status':<10}{'resultado':>15}{'saldo persist.':>16}{'extras':>8}{'%contr.':>9}"
          f"{'repasse calc.':>16}{'parcela deriv.':>16}  observações")
    linha("-")
    for m in meses:
        obs = "; ".join(f"{c}" for c, _ in m["flags"] if c not in ("COM_EXTRAS", "SEM_EXTRAS_LEGADO", "STATUS_NAO_APROVADO"))
        print(f"  {m['mes']:<8}{m['status']:<10}{brl(m['resultado']):>15}{brl(m['saldo']):>16}"
              f"{('sim' if m['tem_extras'] else 'não'):>8}{pct(m['pct']):>9}"
              f"{brl(m['repasse']):>16}{brl(m['parcela']):>16}  {obs}")


def imprimir_regimes(uid, regimes, div_vig):
    print(f"\n[{uid}] regimes de parcela fixa derivada (≥ {MIN_MESES_REGIME} meses seguidos):")
    if not regimes:
        print("  (nenhum regime identificado)")
    for r in regimes:
        print(f"  {r['de']} → {r['ate']}: parcela {brl(r['nominal'])}  ({r['n']} mês(es))")
    for a, b in zip(regimes, regimes[1:]):
        print(f"  MUDANÇA_DE_PARCELA entre {a['ate']} e {b['de']}: {brl(a['nominal'])} → {brl(b['nominal'])}")
    for d in div_vig:
        r = d["regime"]
        print(f"  !! VIGENCIA_PARCELA_DIVERGENTE: regime {r['de']}→{r['ate']} ({brl(r['nominal'])}) mas a vigência de "
              f"`parcela_fixa` cobre {d['n_div']} desses mês(es) ({d['primeiro']}…{d['ultimo']}) com {d['vigencia']}")


def imprimir_atipicos(uid, meses):
    itens = [(m, c, t) for m in meses for c, t in m["flags"]
             if c in ("PARCELA_ATIPICA", "DIVERGENCIA_CENTAVOS", "SEM_PERCENTUAL", "SALDO_NAO_POSITIVO", "EXTRAS_PARCIAIS",
                      "DIVERGE_EXTRAS", "PERCENTUAL_FORA_DO_ESPERADO", "PERCENTUAL_EXTRAS_DIFERE_DA_VIGENCIA",
                      "SEM_EXTRAS_POS_JUN2026", "LACUNA")]
    print(f"\n[{uid}] valores atípicos / divergências:")
    if not itens:
        print("  (nenhum)")
    for m, c, t in itens:
        print(f"  [{c:<30}] {m['mes']}  {t}")


def projetar_anual(conn, uid, meses):
    por_ano = {}
    for m in meses:
        a = por_ano.setdefault(int(m["mes"][:4]), {"n": 0, "ncalc": 0, "fat": 0.0, "res": 0.0, "rep": 0.0, "sal": 0.0, "par": 0.0})
        a["n"] += 1
        a["fat"] += m["faturamento"] or 0.0
        a["res"] += m["resultado"] or 0.0
        a["sal"] += m["saldo"] or 0.0
        if m["repasse"] is not None and m["parcela"] is not None:
            a["ncalc"] += 1
            a["rep"] += m["repasse"]
            a["par"] += m["parcela"]
    cache = {}
    if tabela_existe(conn, "historico_anual"):
        for r in conn.execute("SELECT ano, dados_json FROM historico_anual WHERE unidade_id=?", (uid,)):
            try:
                cache[r["ano"]] = json.loads(r["dados_json"])
            except json.JSONDecodeError:
                pass
    print(f"\n[{uid}] histórico anual PROJETADO a partir de `lancamentos` (e cache `historico_anual`):")
    print(f"  {'Ano':<6}{'meses':>6}{'faturamento':>17}{'resultado':>16}{'repasse proj.':>16}{'saldo proj.':>16}"
          f"{'parcela Σ':>14}   cache.aluguel_calculado")
    desatualizados = []
    for ano, a in sorted(por_ano.items()):
        c = cache.get(ano)
        txt = "(sem cache)"
        if c is not None:
            dif = round((c.get("aluguel_calculado") or 0.0) - a["sal"], 2)
            txt = f"{brl(c.get('aluguel_calculado'))} ({c.get('quantidade_meses')} meses)" + \
                  ("" if abs(dif) <= TOL_CENTAVO and c.get("quantidade_meses") == a["n"] else f"  <-- Δ {brl(dif)} vs saldo Σ")
            if abs(dif) > TOL_CENTAVO or c.get("quantidade_meses") != a["n"]:
                desatualizados.append(f"{ano}")
        parcial = "" if a["ncalc"] == a["n"] else f"  (repasse só de {a['ncalc']}/{a['n']} meses)"
        print(f"  {ano:<6}{a['n']:>6}{brl(a['fat']):>17}{brl(a['res']):>16}{brl(a['rep']):>16}{brl(a['sal']):>16}"
              f"{brl(a['par']):>14}   {txt}{parcial}")
    return desatualizados


def imprimir_tsv(todas):
    cols = ["unidade", "competencia", "status", "faturamento", "resultado", "saldo_persistido", "tem_extras",
            "percentual", "origem_percentual", "repasse_calculado", "parcela_derivada", "flags"]
    print("\t".join(cols))
    for m in todas:
        print("\t".join([
            m["uid"], m["mes"], str(m["status"]), "" if m["faturamento"] is None else f"{m['faturamento']:.2f}",
            "" if m["resultado"] is None else f"{m['resultado']:.2f}", "" if m["saldo"] is None else f"{m['saldo']:.2f}",
            "sim" if m["tem_extras"] else "nao", "" if m["pct"] is None else f"{m['pct']:.4f}", m["pct_origem"] or "",
            "" if m["repasse"] is None else f"{m['repasse']:.2f}", "" if m["parcela"] is None else f"{m['parcela']:.2f}",
            ",".join(c for c, _ in m["flags"]),
        ]))


# ── principal ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Diagnóstico read-only Repasse x Parcela x Saldo (RESULTADO_SPLIT)")
    ap.add_argument("banco", nargs="?", help="caminho do db.sqlite (padrão: $DATA_DIR/db.sqlite ou /mnt/data/db.sqlite)")
    ap.add_argument("--unidades", help="ids separados por vírgula (padrão: todas as RESULTADO_SPLIT)")
    ap.add_argument("--tsv", action="store_true", help="imprime só a tabela mensal em TSV")
    args = ap.parse_args()

    db_path = Path(args.banco) if args.banco else Path(os.environ.get("DATA_DIR") or "/mnt/data") / "db.sqlite"
    conn = conectar_ro(db_path)
    forcadas = [u.strip() for u in args.unidades.split(",") if u.strip()] if args.unidades else None
    unidades, avisos = descobrir_unidades(conn, forcadas)

    todas, resumo = [], {}
    dados = {}
    for uid in unidades:
        vigs = ler_vigencias(conn, uid)
        meses = analisar_unidade(conn, uid, vigs)
        regimes = detectar_regimes(meses)
        marcar_flags(uid, meses, regimes)
        dados[uid] = (vigs, meses, regimes)
        todas.extend(meses)

    if args.tsv:
        imprimir_tsv(todas)
        return

    print(f"banco: {db_path}")
    print(f"unidades analisadas: {', '.join(unidades) or '(nenhuma)'}")
    for a in avisos:
        print(f"AVISO: {a}")

    flags_gerais: list[tuple[str, str, str]] = []   # (classe, unidade, texto)
    desatualizados_cache = {}

    titulo("1. VIGÊNCIAS (produção x referência local de 16/10/2026)")
    for uid in unidades:
        vigs, meses, regimes = dados[uid]
        an = anomalias_vigencia(vigs)
        so_prod, so_ref = comparar_com_referencia(uid, vigs)
        imprimir_vigencias(uid, vigs, so_prod, so_ref, an)
        for classe, texto in an:
            flags_gerais.append((classe, uid, texto))
        for v in (so_prod or []):
            flags_gerais.append(("VIGENCIAS_DIFERENTES_DO_LOCAL", uid,
                                 f"só em produção: {v['parametro']} {v['competencia_inicio']}→{v['competencia_fim'] or 'aberta'} = {jval(v['valor'])}"))
        for p, i, f, val in (so_ref or []):
            flags_gerais.append(("VIGENCIAS_DIFERENTES_DO_LOCAL", uid, f"só na referência: {p} {i}→{f or 'aberta'} = {val}"))

    titulo("2. LANÇAMENTOS — percentual, repasse calculado, parcela derivada, saldo persistido")
    for uid in unidades:
        imprimir_meses(uid, dados[uid][1])

    titulo("3. REGIMES DE PARCELA FIXA x VIGÊNCIA DE `parcela_fixa`")
    for uid in unidades:
        vigs, meses, regimes = dados[uid]
        div = vigencia_parcela_vs_regimes(vigs, regimes)
        imprimir_regimes(uid, regimes, div)
        for d in div:
            r = d["regime"]
            flags_gerais.append(("VIGENCIA_PARCELA_DIVERGENTE", uid,
                                 f"regime {r['de']}→{r['ate']} = {brl(r['nominal'])}; vigência: {d['vigencia']} ({d['n_div']} mês(es))"))
        for a, b in zip(regimes, regimes[1:]):
            flags_gerais.append(("MUDANCA_DE_PARCELA", uid, f"{a['ate']}→{b['de']}: {brl(a['nominal'])} → {brl(b['nominal'])}"))

    titulo("4. VALORES ATÍPICOS E DIVERGÊNCIAS")
    for uid in unidades:
        imprimir_atipicos(uid, dados[uid][1])

    titulo("5. HISTÓRICO ANUAL PROJETADO x CACHE `historico_anual`")
    for uid in unidades:
        desatualizados_cache[uid] = projetar_anual(conn, uid, dados[uid][1])

    # consolida flags por competência
    por_classe: dict[str, list[str]] = {}
    for uid in unidades:
        for m in dados[uid][1]:
            for c, t in m["flags"]:
                por_classe.setdefault(c, []).append(f"{uid}/{m['mes']}" + (f" ({t})" if t and c not in ("COM_EXTRAS", "SEM_EXTRAS_LEGADO") else ""))
    for classe, uid, texto in flags_gerais:
        por_classe.setdefault(classe, []).append(f"{uid}: {texto}")
    for uid, anos in desatualizados_cache.items():
        for ano in anos:
            por_classe.setdefault("CACHE_DESATUALIZADO", []).append(f"{uid}/{ano}")

    titulo("SINALIZADORES")
    total_meses = sum(len(dados[u][1]) for u in unidades)
    print(f"unidades: {len(unidades)}   lançamentos analisados: {total_meses}")
    graves = ("SEM_PERCENTUAL", "SALDO_NAO_POSITIVO", "DIVERGE_EXTRAS", "EXTRAS_PARCIAIS", "SEM_EXTRAS_POS_JUN2026",
              "VIGENCIA_CORROMPIDA", "VIGENCIA_SOBREPOSTA", "PERCENTUAL_FORA_DO_ESPERADO", "PERCENTUAL_EXTRAS_DIFERE_DA_VIGENCIA")
    atencao = ("PARCELA_ATIPICA", "DIVERGENCIA_CENTAVOS", "VIGENCIA_PARCELA_DIVERGENTE", "VIGENCIAS_DIFERENTES_DO_LOCAL",
               "LACUNA", "CACHE_DESATUALIZADO", "STATUS_NAO_APROVADO")
    info = ("COM_EXTRAS", "SEM_EXTRAS_LEGADO", "MUDANCA_DE_PARCELA")
    for grupo, marca in ((graves, "!!"), (atencao, "! "), (info, "..")):
        for classe in grupo:
            itens = por_classe.get(classe, [])
            m = marca if itens else "ok"
            if not itens and grupo is info:
                m = ".."
            print(f"  [{m}] {classe:<38} {len(itens)}")
            if itens and grupo is not info:
                for it in itens[:LISTAR_ATE]:
                    print(f"        - {it}")
                if len(itens) > LISTAR_ATE:
                    print(f"        … e mais {len(itens) - LISTAR_ATE}")
    pode = [m for u in unidades for m in dados[u][1]
            if m["parcela"] is not None and (m["saldo"] or 0) > 0 and not m["tem_extras"]]
    print(f"\n  reconstruíveis (sem extras, percentual conhecido, saldo > 0): {len(pode)}")
    print("\nEste script NÃO corrige, NÃO migra e NÃO grava nada. A decisão sobre cada item é manual.")


if __name__ == "__main__":
    main()
