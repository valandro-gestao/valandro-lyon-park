#!/usr/bin/env python3
"""
Diagnóstico READ-ONLY de produção — homologação set/2026, 4ª rodada
(fechamento Setembro/2026): A. Schneider (faturamento Aucon), Terreno OKA
(prejuízo acumulado) e Viva Trindade (Outras Despesas de Agosto em Setembro).

Só faz SELECT. Abre o banco em modo read-only (URI `?mode=ro` do SQLite +
`PRAGMA query_only=ON` — o próprio SQLite recusa qualquer escrita nessa
conexão) e nunca importa `app.*` (sem init_db()/seed/efeito colateral de
import). Só biblioteca padrão — roda com o `python3` do sistema. Lê (sem
escrever) o `status.json` dos runs de Ago/Set ao lado do banco.

Uso (Render Shell):
    python3 scripts/diagnostico_producao_set2026_v12.py > /tmp/diag_v12.txt; \
        sed -n '/SINALIZADORES/,$p' /tmp/diag_v12.txt

Por padrão lê de $DATA_DIR/db.sqlite (em produção /mnt/data). Para apontar
para outro arquivo:
    python3 scripts/diagnostico_producao_set2026_v12.py /caminho/db.sqlite
A seção "SINALIZADORES AUTOMÁTICOS", no fim da saída, resume os achados.
"""
import json, os, sqlite3, sys
from pathlib import Path

UNIDADES = ("a_schneider", "terreno_oka", "viva_trindade")
MESES = ("2026-08", "2026-09")
CADEIA_DESDE = "2026-06"          # = app.models.CADEIA_SALDO_DESDE
MENSAIS = ("custos_variaveis.outras_despesas", "custos_variaveis.investimentos")

db_path = (sys.argv[1] if len(sys.argv) > 1 else
           str(Path(os.environ.get("DATA_DIR") or "/mnt/data") / "db.sqlite"))
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")


def q(sql, *a):
    return [dict(r) for r in conn.execute(sql, a).fetchall()]


def j(v):
    try:
        return json.loads(v)
    except Exception:
        return v


def sec(t):
    print("\n" + "=" * 100 + f"\n{t}\n" + "=" * 100)


def dump(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


print(f"banco: {db_path}")
tabelas = {r["name"] for r in q("select name from sqlite_master where type='table'")}
sec("0. migrations aplicadas (0008=âncoras, 0015=outras_despesas VT, 0016=aucon, 0017=histórico)")
if "schema_migrations" in tabelas:
    print([r["id"] for r in q("select id from schema_migrations order by id")])

for uid in UNIDADES:
    sec(f"##### {uid}")
    # ── cadastro ───────────────────────────────────────────────────────────────
    cad = q("select * from unidades where id=?", uid)
    print("--- cadastro (unidades) ---")
    dump(cad or "NÃO ENCONTRADA em unidades")
    if not cad:
        continue

    # ── parâmetros: histórico completo + o que cobre Ago/Set ──────────────────
    print("--- parametros_vigentes: HISTÓRICO COMPLETO ---")
    hist = q("""select id, parametro, valor, competencia_inicio, competencia_fim, alterado_por, alterado_em
                from parametros_vigentes where unidade_id=? order by parametro, competencia_inicio""", uid)
    for h in hist:
        h["valor"] = j(h["valor"])
    dump(hist)
    for mes in MESES:
        cob = q("""select parametro, valor, competencia_inicio, competencia_fim, alterado_por
                   from parametros_vigentes where unidade_id=? and competencia_inicio<=?
                   and (competencia_fim is null or competencia_fim>=?)
                   order by parametro, competencia_inicio desc""", uid, mes, mes)
        for c in cob:
            c["valor"] = j(c["valor"])
        print(f"--- parâmetros que COBREM {mes} (linhas candidatas; vale a de maior competencia_inicio por parametro) ---")
        dump(cob)

    # ── rascunhos ─────────────────────────────────────────────────────────────
    print("--- rascunhos_unidade (Ago/Set; inclui _aucon_meta) ---")
    rasc = q("select mes_referencia, dados_json, atualizado_em from rascunhos_unidade "
             "where unidade_id=? and mes_referencia in (?,?)", uid, *MESES)
    for r in rasc:
        r["dados"] = j(r.pop("dados_json"))
    dump(rasc or "nenhum rascunho")

    # ── lançamentos ───────────────────────────────────────────────────────────
    print(f"--- lancamentos >= {CADEIA_DESDE} (resultado resumido) ---")
    lanc = q("select mes_referencia, faturamento, status, criado_em, resultado_json from lancamentos "
             "where unidade_id=? and mes_referencia>=? order by mes_referencia", uid, CADEIA_DESDE)
    for l in lanc:
        d = j(l.pop("resultado_json"))
        ex = d.get("extras") or {}
        l["resumo"] = {
            "faturamento_json": d.get("faturamento"), "resultado": d.get("resultado"),
            "subtotal": d.get("subtotal"), "pe": d.get("ponto_equilibrio"),
            "prejuizo_entrada": d.get("prejuizo_acumulado_entrada"),
            "prejuizo_saida": d.get("prejuizo_acumulado_saida"),
            "aluguel_calculado": d.get("aluguel_calculado"), "custos": d.get("custos"),
            "extras.outras_despesas": ex.get("outras_despesas"),
            "extras.investimentos": ex.get("investimentos"),
            "extras.origem_faturamento(_aucon_meta)": ex.get("origem_faturamento"),
            "extras_keys": sorted(ex.keys()),
        }
    dump(lanc)
    print("--- saldos_acumulados (legado, só exibição) ---")
    dump(q("select * from saldos_acumulados where unidade_id=?", uid))

    # ── replica get_saldo_entrada(Set) ────────────────────────────────────────
    print("--- cadeia de saldo: entrada resolvida para 2026-09 (réplica de get_saldo_entrada) ---")
    ult = q("""select mes_referencia, resultado_json from lancamentos
               where unidade_id=? and status='aprovado' and mes_referencia<? and mes_referencia>=?
               order by mes_referencia desc limit 1""", uid, "2026-09", CADEIA_DESDE)
    anc = q("""select valor, competencia_inicio, competencia_fim from parametros_vigentes
               where unidade_id=? and parametro='saldo_acumulado_inicial'
               and competencia_inicio<='2026-09' and (competencia_fim is null or competencia_fim>='2026-09')
               order by competencia_inicio desc limit 1""", uid)
    dump({
        "ultimo_aprovado_anterior": (ult[0]["mes_referencia"] if ult else None),
        "prejuizo_saida_dele": (j(ult[0]["resultado_json"]).get("prejuizo_acumulado_saida") if ult else None),
        "ancora_saldo_acumulado_inicial": (anc[0] if anc else None),
    })

# ── status de workflow (status.json) ──────────────────────────────────────────
sec("Workflow (runs/<mes>/status.json) — só leitura")
runs = Path(db_path).parent / "runs"
for mes in MESES:
    p = runs / mes / "status.json"
    if p.exists():
        st = json.loads(p.read_text(encoding="utf-8"))
        dump({mes: {u: st.get(u) for u in UNIDADES}})
    else:
        print(f"{mes}: sem status.json em {p}")

# ── sinalizadores automáticos ─────────────────────────────────────────────────
sec("SINALIZADORES AUTOMÁTICOS")
flags = []
# (1) Aucon
u = {r["id"]: r for r in q("select * from unidades")}
for uid in UNIDADES:
    r = u.get(uid)
    if not r:
        continue
    pcode = q("""select valor, competencia_inicio, competencia_fim, alterado_por from parametros_vigentes
                 where unidade_id=? and parametro='aucon_codigo_filial'""", uid)
    if pcode:
        vals = {str(j(p["valor"])) for p in pcode}
        if str(r["aucon_codigo_filial"]) not in vals:
            flags.append(f"[AUCON] {uid}: unidades.aucon_codigo_filial={r['aucon_codigo_filial']} DIVERGE de "
                         f"parametros_vigentes.aucon_codigo_filial={sorted(vals)} -> lote usa a coluna, botão individual usa o param")
for mes in MESES:
    for rr in q("select unidade_id, dados_json from rascunhos_unidade where mes_referencia=?", mes):
        if rr["unidade_id"] not in UNIDADES:
            continue
        d = j(rr["dados_json"]); meta = d.get("_aucon_meta") if isinstance(d, dict) else None
        fat = d.get(f"fat_{rr['unidade_id']}") if isinstance(d, dict) else None
        if meta:
            flags.append(f"[AUCON] {rr['unidade_id']} {mes}: meta presente (filial {meta.get('codigo_filial_usado')}, "
                         f"valor_importado={meta.get('valor_importado')}, bruto={meta.get('bruto')}, "
                         f"cancelados={meta.get('cancelados')}, em {meta.get('importado_em')}); fat no rascunho={fat}")
            if not meta.get("valor_importado"):
                flags.append(f"[AUCON] {rr['unidade_id']} {mes}: API devolveu ZERO (importação 'ok' com R$ 0,00)")
            elif fat is not None and abs(float(fat) - float(meta["valor_importado"])) > 0.005:
                flags.append(f"[AUCON] {rr['unidade_id']} {mes}: fat editado à mão após importação (CONFLITO provável)")
        else:
            flags.append(f"[AUCON] {rr['unidade_id']} {mes}: rascunho SEM _aucon_meta (lote/botão nunca gravou nada aqui)")
    if not q("select 1 from rascunhos_unidade where unidade_id='a_schneider' and mes_referencia=?", mes):
        flags.append(f"[AUCON] a_schneider {mes}: NÃO há rascunho (nunca importado, ou já aprovado/limpo)")
# (3) rubricas mensais virando vigência
for p in MENSAIS:   # TODAS as unidades (a contaminação não é exclusiva da Viva Trindade)
    for row in q("""select unidade_id, valor, competencia_inicio, competencia_fim, alterado_por from parametros_vigentes
                    where parametro=? and alterado_por not in ('migration_0015','seed_yaml')
                    order by unidade_id, competencia_inicio""", p):
        v = j(row["valor"])
        cobre_set = row["competencia_inicio"] <= "2026-09" and (row["competencia_fim"] is None or row["competencia_fim"] >= "2026-09")
        flags.append(f"[RUBRICA-MENSAL] {row['unidade_id']} {p}={v} vigência {row['competencia_inicio']}→{row['competencia_fim']} "
                     f"por '{row['alterado_por']}'" + ("  <-- COBRE 2026-09 (contamina Setembro)" if cobre_set and v else ""))
# (2) cadeia do saldo
for uid in UNIDADES:
    tc = u.get(uid, {}).get("tipo_calculo")
    ag = q("select status, resultado_json from lancamentos where unidade_id=? and mes_referencia='2026-08'", uid)
    saida = j(ag[0]["resultado_json"]).get("prejuizo_acumulado_saida") if ag else None
    flags.append(f"[SALDO] {uid}: tipo_calculo={tc}; Agosto lancamento={'sim ('+ag[0]['status']+')' if ag else 'NÃO'}; "
                 f"prejuizo_saida_Ago={saida}"
                 + ("  <-- tipo SEM cadeia de saldo (só COM_ALIQUOTA_CUMUL/_DU e PATIO_MANUTENCAO usam get_saldo_entrada)"
                    if tc not in ("COM_ALIQUOTA_CUMUL", "COM_ALIQUOTA_CUMUL_DU", "PATIO_MANUTENCAO") else ""))
print("\n".join(flags) or "nenhum")
conn.close()
