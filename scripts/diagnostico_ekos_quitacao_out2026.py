#!/usr/bin/env python3
"""
Diagnóstico READ-ONLY de produção — Ekos: quitação de prejuízo acumulado
(competência out/2026, recebimento de R$ 4.858,56 em 21/10/2026).

Responde, com os dados reais gravados:
  1. prejuízo acumulado transportado de setembro (entrada de outubro);
  2. evolução mensal do prejuízo acumulado (e de onde cada parte veio);
  3. resultado operacional de outubro e seu efeito sobre o saldo;
  4. saldo ANTES da quitação;
  5. quitação recebida, valor aplicável, excedente pendente de conciliação e
     saldo final a transportar para novembro;
  6. situação do lançamento de outubro e do workflow (rascunho/gerado/aprovado);
  7. a classificação do caso: INTEGRAL, PARCIAL, EXCEDENTE ou ABSORVIDO.

A classificação aplica as regras definidas para a futura rubrica, SOBRE OS
VALORES JÁ GRAVADOS (nada é recalculado): a quitação entra depois do repasse,
só sobre o prejuízo remanescente (saída de outubro antes da quitação), nunca
gera saldo positivo, repasse nem receita; se o prejuízo já foi absorvido pelo
resultado de outubro, não é aplicada e o valor inteiro fica como excedente.

Só faz SELECT e só lê arquivos. Abre o banco em modo read-only (URI `?mode=ro`
do SQLite + `PRAGMA query_only=ON` — o próprio SQLite recusa qualquer escrita
nessa conexão) e nunca importa `app.*` (sem init_db()/seed/migration/efeito
colateral de import). Só biblioteca padrão. Não imprime credenciais, tokens
nem dados de clientes; metadados de usuário da importação Aucon são omitidos.

Uso (Render Shell, a partir da raiz do app):
    cd /app && python3 scripts/diagnostico_ekos_quitacao_out2026.py

Por padrão lê de $DATA_DIR/db.sqlite (em produção, /mnt/data/db.sqlite) e de
$DATA_DIR/runs/<mês>/status.json. Opções:
    python3 scripts/diagnostico_ekos_quitacao_out2026.py [/caminho/db.sqlite] \
        [--unidade ekos] [--mes 2026-10] [--valor 4858.56]
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

CADEIA_DESDE = "2026-06"                     # = app.models.CADEIA_SALDO_DESDE
CHAVE_ANCORA = "saldo_acumulado_inicial"     # = app.models._CHAVE_SALDO_ACUMULADO_INICIAL
EPS = 0.005
QUITACAO_PADRAO = 4858.56
_OMITIR_META = ("user", "usuario", "email", "login", "senha", "token", "nome", "pass")


# ─── helpers puros (testáveis; sem banco) ────────────────────────────────────

def brl(v):
    if v is None:
        return "n/d"
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def mes_seguinte(mes):
    a, m = int(mes[:4]), int(mes[5:7])
    return f"{a + (m == 12)}-{1 if m == 12 else m + 1:02d}"


def mes_anterior(mes):
    a, m = int(mes[:4]), int(mes[5:7])
    return f"{a - (m == 1)}-{12 if m == 1 else m - 1:02d}"


def meses_entre(ini, fim):
    out, m = [], ini
    while m <= fim:
        out.append(m)
        m = mes_seguinte(m)
    return out


def classificar_quitacao(saida_antes, quitacao):
    """Regra da quitação aplicada sobre a saída de outubro ANTES dela.

    `saida_antes` é o prejuízo remanescente (<= 0). Devolve cenário, valor
    aplicado, excedente (pendente de conciliação) e saldo final (nunca > 0).
    """
    s = min(0.0, round(num(saida_antes), 2))
    q = round(num(quitacao), 2)
    if q <= EPS:
        return {"cenario": "SEM_QUITACAO", "aplicada": 0.0, "excedente": 0.0, "saldo_final": s}
    if s >= -EPS:
        return {"cenario": "ABSORVIDO", "aplicada": 0.0, "excedente": q, "saldo_final": 0.0}
    resto = abs(s)
    if abs(q - resto) < EPS:
        return {"cenario": "INTEGRAL", "aplicada": q, "excedente": 0.0, "saldo_final": 0.0}
    if q < resto:
        return {"cenario": "PARCIAL", "aplicada": q, "excedente": 0.0,
                "saldo_final": round(s + q, 2)}
    return {"cenario": "EXCEDENTE", "aplicada": round(resto, 2),
            "excedente": round(q - resto, 2), "saldo_final": 0.0}


# ─── acesso (somente leitura) ────────────────────────────────────────────────

def abrir_ro(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _q(conn, sql, *a):
    return [dict(r) for r in conn.execute(sql, a).fetchall()]


def _j(v):
    if not isinstance(v, str):
        return v
    try:
        return json.loads(v)
    except ValueError:
        return v


def ancora(conn, uid, mes):
    r = _q(conn, """select valor, competencia_inicio, competencia_fim from parametros_vigentes
                    where unidade_id=? and parametro=? and competencia_inicio<=?
                    and (competencia_fim is null or competencia_fim>=?)
                    order by competencia_inicio desc limit 1""", uid, CHAVE_ANCORA, mes, mes)
    return (num(_j(r[0]["valor"])), r[0]) if r else (None, None)


def entrada_pela_cadeia(conn, uid, mes):
    """Réplica de leitura de app.models.get_saldo_entrada: saída do último
    lançamento APROVADO estritamente anterior (>= CADEIA_DESDE); senão a
    âncora vigente; senão 0."""
    r = _q(conn, """select mes_referencia, resultado_json from lancamentos
                    where unidade_id=? and status='aprovado' and mes_referencia<?
                    and mes_referencia>=? order by mes_referencia desc limit 1""",
           uid, mes, CADEIA_DESDE)
    if r:
        d = _j(r[0]["resultado_json"]) or {}
        return num(d.get("prejuizo_acumulado_saida")), f"saída do aprovado {r[0]['mes_referencia']}"
    v, _ = ancora(conn, uid, mes)
    if v is not None:
        return v, f"âncora {CHAVE_ANCORA}"
    return 0.0, "sem aprovado anterior nem âncora (0)"


def decompor(row):
    d = _j(row["resultado_json"]) or {}
    ex = d.get("extras") or {}
    e, s = num(d.get("prejuizo_acumulado_entrada")), num(d.get("prejuizo_acumulado_saida"))
    res, inv = num(d.get("resultado")), num(ex.get("investimentos"))
    disp = round(res - inv, 2)
    base = round(disp + e, 2)
    return {"mes": row["mes_referencia"], "status": row["status"], "fat": num(row["faturamento"]),
            "resultado": res, "invest": inv, "disponivel": disp, "entrada": e, "saida": s,
            "base": base, "saida_formula": round(min(0.0, base), 2),
            "aluguel": num(d.get("aluguel_calculado")), "extras_keys": sorted(ex.keys())}


def sec(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("db", nargs="?", default=None)
    ap.add_argument("--unidade", default="ekos")
    ap.add_argument("--mes", default="2026-10")
    ap.add_argument("--valor", type=float, default=QUITACAO_PADRAO)
    ap.add_argument("--saida-antes", type=float, default=None,
                    help="só se a competência ainda NÃO tem lançamento (o lançamento é gravado na aprovação): "
                         "saída/prejuízo acumulado exibido na tela de Fechamento, antes da quitação")
    a = ap.parse_args(argv)

    data_dir = Path(os.environ.get("DATA_DIR") or "/mnt/data")
    db_path = Path(a.db) if a.db else data_dir / "db.sqlite"
    if not db_path.is_file():
        print(f"ERRO: banco não encontrado em {db_path} (nada foi criado).", file=sys.stderr)
        return 2
    conn = abrir_ro(db_path)
    uid, mes, Q = a.unidade, a.mes, a.valor
    sinal = []

    sec(f"0. Contexto — banco {db_path} (somente leitura) | unidade={uid} | competência={mes}")
    try:
        print("últimas migrations:", [r["id"] for r in _q(conn, "select id from schema_migrations order by id")][-3:])
    except sqlite3.Error as e:
        print("schema_migrations indisponível:", e)
    un = _q(conn, "select * from unidades where id=?", uid)
    if not un:
        un = _q(conn, "select * from unidades where lower(nome) like ?", f"%{uid.lower()}%")
        if un:
            uid = un[0]["id"]
    if not un:
        print(f"Unidade '{a.unidade}' NÃO encontrada em `unidades`.")
        return 1
    u = un[0]
    print({k: u.get(k) for k in ("id", "nome", "tipo_calculo", "ativo", "inicio") if k in u})
    if u.get("tipo_calculo") != "COM_ALIQUOTA_CUMUL":
        sinal.append(f"tipo_calculo={u.get('tipo_calculo')} (a rubrica de quitação é desenhada para COM_ALIQUOTA_CUMUL)")
    if not u.get("ativo"):
        sinal.append("unidade com ativo=0 em `unidades`")

    sec("1. Parâmetros vigentes na competência (maior competencia_inicio por parâmetro)")
    vistos = set()
    for p in _q(conn, """select parametro, valor, competencia_inicio, competencia_fim from parametros_vigentes
                         where unidade_id=? and competencia_inicio<=? and (competencia_fim is null or competencia_fim>=?)
                         order by parametro, competencia_inicio desc""", uid, mes, mes):
        if p["parametro"] in vistos:
            continue
        vistos.add(p["parametro"])
        print(f"  {p['parametro']:<40} {str(p['valor'])[:70]:<72} desde {p['competencia_inicio']}"
              f"{' até ' + p['competencia_fim'] if p['competencia_fim'] else ''}")
    hist_anc = _q(conn, "select valor, competencia_inicio, competencia_fim, alterado_em from parametros_vigentes "
                        "where unidade_id=? and parametro=? order by competencia_inicio", uid, CHAVE_ANCORA)
    print(f"  histórico da âncora {CHAVE_ANCORA}:", hist_anc or "nenhuma")

    sec("2. Evolução mensal do prejuízo acumulado (valores GRAVADOS em lancamentos; nada recalculado)")
    rows = _q(conn, "select mes_referencia, status, faturamento, resultado_json from lancamentos "
                    "where unidade_id=? and mes_referencia>=? order by mes_referencia", uid, CADEIA_DESDE)
    L = {r["mes_referencia"]: decompor(r) for r in rows}
    print(f"{'mês':8}{'status':10}{'resultado':>11}{'invest.':>10}{'entrada':>11}{'Δ saldo':>11}{'saída':>11}"
          f"{'repasse':>11}  verificação")
    ini = max((u.get("inicio") or CADEIA_DESDE)[:7], CADEIA_DESDE)
    for m in meses_entre(ini, mes):
        if m not in L:
            print(f"{m:8}— SEM LANÇAMENTO"); sinal.append(f"{m}: sem lançamento na cadeia"); continue
        x = L[m]
        esp, origem = entrada_pela_cadeia(conn, uid, m)
        v = []
        v.append("entrada=cadeia" if abs(x["entrada"] - esp) < EPS else f"ENTRADA DIVERGE DA CADEIA ({brl(esp)}; {origem})")
        v.append("fórmula OK" if abs(x["saida"] - x["saida_formula"]) < 0.015 else f"SAÍDA≠FÓRMULA ({brl(x['saida_formula'])})")
        if x["status"] != "aprovado" and m < mes:
            v.append("NÃO APROVADO: não alimenta a cadeia")
        d = x["saida"] - x["entrada"]
        tag = "GERA" if d < -EPS else ("ABSORVE" if d > EPS else "-")
        print(f"{m:8}{x['status']:10}{brl(x['resultado']):>11}{brl(x['invest']):>10}{brl(x['entrada']):>11}"
              f"{brl(d):>11}{brl(x['saida']):>11}{brl(x['aluguel']):>11}  {tag}; " + "; ".join(v))
        for t in v[:2]:
            if "DIVERGE" in t or "≠" in t or "NÃO APROVADO" in t:
                sinal.append(f"{m}: {t}")
    posteriores = [m for m in L if m > mes]
    if posteriores:
        print("competências POSTERIORES já lançadas (precisarão ser reprocessadas em ordem):",
              [(m, L[m]["status"]) for m in posteriores])
        sinal.append(f"existem lançamentos posteriores a {mes}: {posteriores}")

    sec(f"3. Situação de {mes}: lançamento, rascunho e workflow")
    runs = db_path.parent / "runs"
    for m in (mes_anterior(mes), mes):
        p = runs / m / "status.json"
        if not p.is_file():
            print(f"  workflow {m}: status.json inexistente"); continue
        try:
            s = (json.loads(p.read_text(encoding="utf-8")) or {}).get(uid) or {}
            print(f"  workflow {m}:", {k: s.get(k) for k in ("status", "version", "last_generated_at",
                                                           "last_approved_at", "reopened_at")},
                  "| PDFs arquivados:", len(s.get("versions") or []))
        except (OSError, ValueError) as e:
            print(f"  workflow {m}: status.json ilegível ({e})")
    print(f"  lançamento {mes}:", (f"status={L[mes]['status']}" if mes in L else "NÃO EXISTE (ainda não calculado/salvo)"))
    for r in _q(conn, "select dados_json, atualizado_em from rascunhos_unidade where unidade_id=? and mes_referencia=?", uid, mes):
        d = _j(r["dados_json"]) or {}
        meta = d.get("_aucon_meta")
        if isinstance(meta, dict):
            meta = {k: v for k, v in meta.items() if not any(t in k.lower() for t in _OMITIR_META)}
        print(f"  rascunho {mes}: atualizado_em={r['atualizado_em']} fat_{uid}={d.get('fat_' + uid)} _aucon_meta={meta}")
    if mes in L and L[mes]["status"] == "aprovado":
        sinal.append(f"{mes} APROVADO: aplicar a quitação exige reabrir/reaprovar e sobrescreve a linha de lancamentos "
                     f"(guarde esta saída como fotografia do estado anterior; PDFs antigos ficam em versions/)")

    sec(f"4. CONCILIAÇÃO DA QUITAÇÃO — {mes} (valores gravados; regra pós-repasse)")
    e_cad, origem = entrada_pela_cadeia(conn, uid, mes)
    print(f"  (1) Prejuízo transportado do mês anterior, pela cadeia ...... {brl(e_cad):>12}   [{origem}]")
    resumo = {}
    if mes in L:
        x = L[mes]
        efeito = ("reduz o prejuízo" if x["disponivel"] > EPS else "amplia o prejuízo" if x["disponivel"] < -EPS else "neutro")
        print(f"  (1b) Entrada gravada no lançamento de {mes} ................ {brl(x['entrada']):>12}"
              f"{'' if abs(x['entrada'] - e_cad) < EPS else '   <-- DIVERGE da cadeia'}")
        print(f"  (2) Resultado operacional de {mes} ......................... {brl(x['resultado']):>12}")
        print(f"  (3) (-) Investimentos ...................................... {brl(x['invest']):>12}")
        print(f"  (4) Resultado disponível (efeito no saldo: {efeito}) .. {brl(x['disponivel']):>12}")
        print(f"  (5) Base após absorver o prejuízo de entrada (4)+(1b) ...... {brl(x['base']):>12}"
              f"   {'-> sobra para repasse' if x['base'] > EPS else '-> sem repasse; vira saída'}")
        print(f"  (6) SALDO ANTES DA QUITAÇÃO (saída gravada) ................ {brl(x['saida']):>12}"
              f"   [fórmula: {brl(x['saida_formula'])}]")
        print(f"  (7) Repasse gravado (NÃO muda com a quitação) .............. {brl(x['aluguel']):>12}")
        c = classificar_quitacao(x["saida"], Q)
        print(f"  (8) Quitação recebida ...................................... {brl(Q):>12}")
        print(f"  (9) Valor aplicável ........................................ {brl(c['aplicada']):>12}")
        print(f"  (10) Excedente PENDENTE DE CONCILIAÇÃO ..................... {brl(c['excedente']):>12}")
        print(f"  (11) Saldo final a transportar para {mes_seguinte(mes)} ................ {brl(c['saldo_final']):>12}")
        rot = {"INTEGRAL": "QUITAÇÃO INTEGRAL (valor = prejuízo remanescente)",
               "PARCIAL": "QUITAÇÃO PARCIAL (resta saldo negativo, sem baixa automática)",
               "EXCEDENTE": "EXCEDENTE (paga mais que o prejuízo remanescente; sobra pendente)",
               "ABSORVIDO": ("SALDO JÁ ABSORVIDO pelo resultado do mês (quitação NÃO aplicada; valor inteiro pendente)"
                             if x["entrada"] < -EPS else "SEM PREJUÍZO REMANESCENTE (saldo já era zero; valor inteiro pendente)"),
               "SEM_QUITACAO": "valor da quitação <= 0"}[c["cenario"]]
        print(f"\n  CENÁRIO: {c['cenario']} — {rot}")
        resumo = {"entrada_cadeia": e_cad, "entrada_gravada": x["entrada"], "resultado": x["resultado"],
                  "disponivel": x["disponivel"], "saldo_antes": x["saida"], "quitacao": Q, **c, "repasse": x["aluguel"]}
        if abs(x["saida"] - x["saida_formula"]) >= 0.015:
            sinal.append(f"{mes}: saída gravada ≠ fórmula; conferir se o lançamento está atualizado")
    elif a.saida_antes is not None:
        c = classificar_quitacao(a.saida_antes, Q)
        print(f"  Lançamento de {mes} inexistente; usando a saída INFORMADA MANUALMENTE (tela): {brl(a.saida_antes)}")
        print(f"  (8) Quitação recebida ...................................... {brl(Q):>12}")
        print(f"  (9) Valor aplicável ........................................ {brl(c['aplicada']):>12}")
        print(f"  (10) Excedente PENDENTE DE CONCILIAÇÃO ..................... {brl(c['excedente']):>12}")
        print(f"  (11) Saldo final a transportar para {mes_seguinte(mes)} ................ {brl(c['saldo_final']):>12}")
        print(f"\n  CENÁRIO (indicativo, valor não gravado): {c['cenario']}")
        resumo = {"entrada_cadeia": e_cad, "saldo_antes_informado": a.saida_antes, "quitacao": Q, **c}
        sinal.append(f"{mes}: classificação baseada em valor digitado, não em dado gravado")
    else:
        print(f"  Lançamento de {mes} inexistente (só é gravado na aprovação): sem dados gravados para classificar.")
        print(f"  Referência indicativa (não é classificação): quitação {brl(Q)} vs |entrada| {brl(abs(e_cad))} "
              f"-> diferença {brl(Q - abs(e_cad))}.")
        print("  Se a competência ainda não foi aprovada, leia na tela de Fechamento o 'Prejuízo Acumulado' (saída) e rode com "
              "--saida-antes <valor negativo>.")
        sinal.append(f"{mes}: sem lançamento; caso não classificável com dados gravados")

    sec("RESUMO PARA COLAR")
    for k, v in resumo.items():
        print(f"  {k:<16} {brl(v) if isinstance(v, float) else v}")
    print("  sinalizadores:", "nenhum" if not sinal else "")
    for s in sinal:
        print("   -", s)
    print("\nFIM — nenhuma escrita feita (mode=ro + query_only; sem importar app.*).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
