"""
Leitura de Repasse ao Contratante x Parcela Fixa x Saldo a Pagar das unidades
RESULTADO_SPLIT (Medcenter, Viva Open Mall e qualquer unidade nesse modelo).

POR QUE EXISTE. A calculadora RESULTADO_SPLIT grava o SALDO A PAGAR em
`lancamentos.aluguel_calculado` (ver app.calculators.resultado_split); o
repasse ao contratante (`extras.resultado_contratante`) e a parcela fixa
(`extras.parcela_fixa`) só existem nos meses calculados pelo sistema (a partir
de 2026-06). O histórico restaurado de planilhas (até 2026-05) tem `extras`
vazio. Este módulo é o ÚNICO ponto que traduz um lançamento nesses três
valores, para o PDF e para a tela "Competências anteriores" nunca divergirem.

SOMENTE LEITURA. Nada aqui escreve em `lancamentos`, `parametros_vigentes`,
`historico_anual`, `saldos_acumulados` nem em arquivos. `aluguel_calculado`
nunca é alterado nem reinterpretado no banco: continua sendo o saldo.

REGRA DE LEITURA (por lançamento):
  - COM `extras.resultado_contratante` (calculado pelo sistema): usa os
    valores efetivamente persistidos — repasse, parcela fixa e saldo — sem
    recalcular. Origem "persistido".
  - SEM ele (histórico legado): saldo = `aluguel_calculado` persistido,
    intocado; repasse = round(resultado x percentual_contratante vigente na
    competência, 2) — a mesma fórmula do calculador; parcela fixa derivada =
    repasse - saldo (informativa; só quando saldo > 0). Origem "reconstruído".
  - Percentual sem vigência na competência: NÃO há reserva no YAML (o YAML
    traz o percentual atual e daria um repasse errado para competências
    antigas): repasse e parcela ficam None ("—") e o saldo continua o
    persistido. Origem "indisponível".

COMPETÊNCIAS CONSIDERADAS NO HISTÓRICO. Um relatório aprovado não pode exibir
valores de competências ainda em elaboração ou reabertas. Uma competência só
entra no histórico se `lancamentos.status = 'aprovado'` E, quando existe o
`runs/{mês}/status.json` com a unidade, o workflow não a coloca "em
elaboração":
  - `aprovado`: entra;
  - `reaberto` e `pendente`: ficam de fora;
  - `gerado`, `revisado` e `erro`: entram SOMENTE se a competência já foi
    aprovada (`last_approved_at`) e não foi reaberta depois dessa aprovação
    (`reopened_at`). É o caso de "Gerar PDF" numa competência já aprovada — o
    run_manager devolve o status a `gerado`, mas nada voltou a ser elaborado —
    e de uma regeração de PDF que falhou (`erro`). Já uma competência reaberta
    e depois "gerada" de novo, ainda não reaprovada, continua de fora.
Competências sem status.json (histórico restaurado de planilhas) valem pelo
lançamento. A competência do PRÓPRIO relatório é sempre incluída, vinda da
memória — assim o PDF de conferência, gerado antes da aprovação, continua
mostrando o mês corrente, uma única vez.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from app.models import get_db
from app.paths import RUNS_DIR

ORIGEM_PERSISTIDO = "persistido"
ORIGEM_RECONSTRUIDO = "reconstruído"
ORIGEM_INDISPONIVEL = "indisponível"

ROTULO_REPASSE = "Repasse ao Contratante"
ROTULO_SALDO = "Saldo a Pagar"
ROTULO_PARCELA = "Parcela Fixa"


@dataclass(frozen=True)
class ValoresSplit:
    repasse: Optional[float]      # repasse ao contratante (antes da parcela fixa)
    saldo: Optional[float]        # saldo a pagar (depois da parcela fixa)
    parcela: Optional[float]      # parcela fixa (persistida ou derivada)
    percentual: Optional[float]   # percentual do contratante usado, se conhecido
    origem: str                   # ORIGEM_*


def _num(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


class PercentualContratante:
    """Percentual do contratante vigente em cada competência de uma unidade.

    Uma única leitura de `parametros_vigentes` por instância; a resolução por
    competência é em memória, com a mesma regra de cobertura de
    app.models.get_parametros_vigentes/salvar_parametros (início <= mês <=
    fim, ou vigência aberta; vence a de início mais recente). Sem vigência que
    cubra o mês: None — nunca o YAML.
    """

    def __init__(self, unidade_id: str):
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, valor, competencia_inicio, competencia_fim FROM parametros_vigentes "
                "WHERE unidade_id=? AND parametro='percentual_contratante'",
                (unidade_id,),
            ).fetchall()
        self._vigencias = []
        for r in rows:
            try:
                valor = _num(json.loads(r["valor"]))
            except (json.JSONDecodeError, TypeError):
                valor = None
            self._vigencias.append((r["competencia_inicio"], r["competencia_fim"], r["id"], valor))

    def na_competencia(self, mes_ref: str) -> Optional[float]:
        cobrem = [v for v in self._vigencias
                  if v[0] <= mes_ref and (v[1] is None or v[1] >= mes_ref)]
        if not cobrem:
            return None
        return max(cobrem, key=lambda v: (v[0], v[2]))[3]


def valores_split(lancamento: dict, resolver: Optional[PercentualContratante]) -> ValoresSplit:
    """Traduz um lançamento (dict do resultado_json, com a competência em
    `mes`, `mes_ref` ou `mes_referencia`) em repasse, saldo e parcela fixa.
    Não altera o dicionário recebido."""
    mes = lancamento.get("mes") or lancamento.get("mes_ref") or lancamento.get("mes_referencia")
    extras = lancamento.get("extras")
    extras = extras if isinstance(extras, dict) else {}
    saldo_persistido = _num(lancamento.get("aluguel_calculado"))

    repasse_persistido = _num(extras.get("resultado_contratante"))
    if repasse_persistido is not None:
        saldo = _num(extras.get("saldo_a_pagar"))
        return ValoresSplit(
            repasse=repasse_persistido,
            saldo=saldo if saldo is not None else saldo_persistido,
            parcela=_num(extras.get("parcela_fixa")),
            percentual=_num(extras.get("percentual_contratante")),
            origem=ORIGEM_PERSISTIDO,
        )

    resultado = _num(lancamento.get("resultado"))
    pct = resolver.na_competencia(mes) if (resolver is not None and mes) else None
    if resultado is None or pct is None:
        return ValoresSplit(None, saldo_persistido, None, pct, ORIGEM_INDISPONIVEL)

    repasse = round(resultado * pct, 2)
    # Saldo <= 0 não permite derivar a parcela: a extração legada chegou a
    # gravar max(0, valor) — o repasse continua válido, a parcela não.
    parcela = (round(repasse - saldo_persistido, 2)
               if saldo_persistido is not None and saldo_persistido > 0 else None)
    return ValoresSplit(repasse, saldo_persistido, parcela, pct, ORIGEM_RECONSTRUIDO)


# ── competências aprovadas ───────────────────────────────────────────────────

def _info_workflow(mes_ref: str, unidade_id: str) -> Optional[dict]:
    """Bloco do workflow da unidade na competência, lido de
    runs/{mês}/status.json. None = sem informação (arquivo ou unidade
    ausente, ou arquivo ilegível) — nunca levanta."""
    caminho = RUNS_DIR / mes_ref / "status.json"
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            run = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    info = run.get(unidade_id) if isinstance(run, dict) else None
    return info if isinstance(info, dict) else None


def _workflow_admite_no_historico(info: Optional[dict]) -> bool:
    """True se o workflow NÃO coloca a competência em elaboração (ver o
    docstring do módulo). Sem informação de workflow, vale o lançamento."""
    if info is None:
        return True
    status = info.get("status")
    if status == "aprovado":
        return True
    if status in ("reaberto", "pendente"):
        return False
    # gerado / revisado / erro (e qualquer status desconhecido): só vale se já
    # houve aprovação e ela não é anterior a uma reabertura. Timestamps ISO com
    # a mesma precisão — a comparação textual é cronológica; na dúvida
    # (mesmo segundo) a competência fica de fora.
    aprovada_em, reaberta_em = info.get("last_approved_at"), info.get("reopened_at")
    if not aprovada_em:
        return False
    return not (reaberta_em and reaberta_em >= aprovada_em)


def competencias_aprovadas(unidade_id: str) -> set[str]:
    """Competências da unidade elegíveis ao histórico de um relatório
    (ver docstring do módulo)."""
    with get_db() as conn:
        meses = [r["mes_referencia"] for r in conn.execute(
            "SELECT mes_referencia FROM lancamentos WHERE unidade_id=? AND status='aprovado'",
            (unidade_id,),
        )]
    return {m for m in meses if _workflow_admite_no_historico(_info_workflow(m, unidade_id))}


def lancamentos_aprovados_ate(unidade_id: str, mes_ref: str, resultado_atual) -> list[dict]:
    """Histórico para o relatório de `mes_ref`: todas as competências
    aprovadas até `mes_ref` (inclusive), cada uma como {"mes": ..., **resultado_json},
    com a competência do próprio relatório SEMPRE vinda de `resultado_atual`
    (memória) — nunca do banco, mesmo que já persistida, aprovada ou não."""
    aprovadas = competencias_aprovadas(unidade_id)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT mes_referencia, resultado_json FROM lancamentos "
            "WHERE unidade_id=? AND mes_referencia<=? ORDER BY mes_referencia",
            (unidade_id, mes_ref),
        ).fetchall()
    out = []
    for r in rows:
        if r["mes_referencia"] == mes_ref or r["mes_referencia"] not in aprovadas:
            continue
        try:
            out.append({"mes": r["mes_referencia"], **json.loads(r["resultado_json"])})
        except json.JSONDecodeError:
            continue
    out.append({"mes": mes_ref, **resultado_atual.__dict__})
    return sorted(out, key=lambda l: l["mes"])


def agregar_por_ano(lancamentos: list[dict], resolver: Optional[PercentualContratante]) -> dict[int, dict]:
    """Soma, por ano, faturamento, resultado, repasse e saldo.

    `repasse` do ano é None se QUALQUER mês do ano não tiver repasse
    calculável — nunca uma soma parcial apresentada como total. `meses` é a
    quantidade de competências efetivamente somadas."""
    anos: dict[int, dict] = {}
    for l in lancamentos:
        ano = int(l["mes"][:4])
        a = anos.setdefault(ano, {"meses": 0, "faturamento": 0.0, "resultado": 0.0,
                                  "repasse": 0.0, "saldo": 0.0, "_repasse_ok": True})
        v = valores_split(l, resolver)
        a["meses"] += 1
        a["faturamento"] += _num(l.get("faturamento")) or 0.0
        a["resultado"] += _num(l.get("resultado")) or 0.0
        a["saldo"] += v.saldo or 0.0
        if v.repasse is None:
            a["_repasse_ok"] = False
        else:
            a["repasse"] += v.repasse
    for a in anos.values():
        ok = a.pop("_repasse_ok")
        for k in ("faturamento", "resultado", "repasse", "saldo"):
            a[k] = round(a[k], 2)
        if not ok:
            a["repasse"] = None
    return anos


def rotulo_percentual(p: Optional[float]) -> str:
    """0.85 -> '85'; 0.825 -> '82,5' (sem truncar frações do percentual)."""
    if p is None:
        return "—"
    s = f"{p * 100:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")
