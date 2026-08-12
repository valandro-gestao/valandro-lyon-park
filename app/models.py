from dataclasses import dataclass, field
from typing import Optional
import sqlite3, json, os
from datetime import date as _date

from app.paths import DB_PATH

# ─── metadados de parâmetros operacionais ────────────────────────────────────
# Chave dot-notation → (tipo_dado, descrição amigável)
# tipo_dado é consumido pela futura UI para escolher o componente correto.
_PARAM_META: dict[str, tuple[str, str]] = {
    # Ponto de equilíbrio
    "ponto_equilibrio":                         ("moeda",      "Ponto de Equilíbrio Contratual"),
    # Alíquotas
    "aliquota_imposto":                         ("percentual", "Alíquota de Imposto"),
    # Percentuais de repasse
    "percentual_aluguel":                       ("percentual", "Percentual de Aluguel"),
    "percentual_operador":                      ("percentual", "Percentual do Operador"),
    "percentual_contratante":                   ("percentual", "Percentual do Contratante"),
    # Taxas e parcelas fixas
    "taxa_admin_fixa":                          ("moeda",      "Taxa de Administração Fixa"),
    "parcela_fixa":                             ("moeda",      "Parcela Fixa"),
    "despesas_fixas":                           ("moeda",      "Despesas Fixas"),
    # Custos mensais fixos
    "custos_mensais.condominio":                ("moeda",      "Condomínio"),
    "custos_mensais.iptu":                      ("moeda",      "IPTU"),
    "custos_mensais.agua":                      ("moeda",      "Água"),
    "custos_mensais.internet":                  ("moeda",      "Internet"),
    "custos_mensais.manutencao_equipamentos":   ("moeda",      "Manutenção de Equipamentos"),
    # Custos variáveis
    "custos_variaveis.investimentos":           ("moeda",      "Investimentos"),
    "custos_variaveis.fundo_recomposicao":      ("moeda",      "Fundo de Recomposição"),
    # Reajuste
    "reajuste_mes":                             ("inteiro",    "Mês de Reajuste Anual"),
    "reajuste_indice":                          ("texto",      "Índice de Reajuste"),
    # Listas operacionais (editadas como tabela na UI)
    "faixas":                                   ("json",       "Faixas de Cálculo"),
    "faixas_aluguel":                           ("json",       "Faixas de Aluguel"),
    "splits":                                   ("json",       "Splits de Resultado"),
    "repasses":                                 ("json",       "Repasses Contratuais"),
}


def _infer_meta(chave: str, valor) -> tuple[str, str]:
    """Fallback para parâmetros não mapeados em _PARAM_META."""
    if chave in _PARAM_META:
        return _PARAM_META[chave]
    if isinstance(valor, list):
        return ("json", chave)
    if isinstance(valor, bool):
        return ("boolean", chave)
    if isinstance(valor, int):
        return ("inteiro", chave)
    if isinstance(valor, float):
        return ("decimal", chave)
    if isinstance(valor, str):
        return ("texto", chave)
    return ("json", chave)

# DB_PATH resolvido via app.paths (lê DATA_DIR do ambiente)


@dataclass
class ResultadoUnidade:
    unidade_id: str
    mes_referencia: str          # "2026-06"
    faturamento: float
    aliquota_imposto: float = 0.0
    subtotal: float = 0.0
    ponto_equilibrio: float = 0.0
    custos: dict = field(default_factory=dict)
    resultado: float = 0.0
    prejuizo_acumulado_entrada: float = 0.0
    prejuizo_acumulado_saida: float = 0.0
    aluguel_calculado: float = 0.0
    splits: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)
    observacoes: str = ""
    status: str = "rascunho"


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    from app.paths import ensure_dirs
    ensure_dirs()
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS lancamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unidade_id TEXT NOT NULL,
                mes_referencia TEXT NOT NULL,
                faturamento REAL NOT NULL,
                resultado_json TEXT NOT NULL,
                status TEXT DEFAULT 'rascunho',
                criado_em TEXT DEFAULT (datetime('now')),
                UNIQUE(unidade_id, mes_referencia)
            );

            CREATE TABLE IF NOT EXISTS saldos_acumulados (
                unidade_id TEXT PRIMARY KEY,
                prejuizo_acumulado REAL NOT NULL DEFAULT 0.0,
                atualizado_em TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS historico_anual (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unidade_id TEXT NOT NULL,
                ano INTEGER NOT NULL,
                dados_json TEXT NOT NULL,
                UNIQUE(unidade_id, ano)
            );

            -- Parâmetros editáveis com vigência por competência
            CREATE TABLE IF NOT EXISTS parametros_vigentes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unidade_id TEXT NOT NULL,
                parametro TEXT NOT NULL,
                valor TEXT NOT NULL,
                tipo_dado TEXT,
                descricao TEXT,
                competencia_inicio TEXT NOT NULL,
                competencia_fim TEXT,
                alterado_em TEXT DEFAULT (datetime('now')),
                alterado_por TEXT DEFAULT 'sistema'
            );

            CREATE INDEX IF NOT EXISTS idx_params_unit_comp
                ON parametros_vigentes (unidade_id, parametro, competencia_inicio);
        """)
        # Migration: adiciona colunas em DBs criados antes desta versão
        for col in ("tipo_dado TEXT", "descricao TEXT"):
            try:
                conn.execute(f"ALTER TABLE parametros_vigentes ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass  # coluna já existe


# ─── parâmetros com vigência ──────────────────────────────────────────────────

def get_parametros_vigentes(unidade_id: str, mes_ref: str) -> dict:
    """
    Retorna todos os parâmetros vigentes em mes_ref para a unidade.
    Reconstrói dicts aninhados: "custos_mensais.condominio" → {custos_mensais: {condominio: v}}.
    """
    with get_db() as conn:
        rows = conn.execute("""
            SELECT parametro, valor
            FROM parametros_vigentes
            WHERE unidade_id = ?
              AND competencia_inicio <= ?
              AND (competencia_fim IS NULL OR competencia_fim >= ?)
            ORDER BY competencia_inicio DESC
        """, (unidade_id, mes_ref, mes_ref)).fetchall()

    seen: set = set()
    params: dict = {}
    for row in rows:
        chave = row["parametro"]
        if chave in seen:
            continue
        seen.add(chave)
        try:
            valor = json.loads(row["valor"])
        except (json.JSONDecodeError, TypeError):
            valor = row["valor"]

        if "." in chave:
            partes = chave.split(".", 1)
            grupo, subchave = partes[0], partes[1]
            params.setdefault(grupo, {})[subchave] = valor
        else:
            params[chave] = valor

    return params


def salvar_parametros(unidade_id: str, mes_ref: str, parametros: dict,
                       alterado_por: str = "operador"):
    """
    Persiste parâmetros editados pelo usuário ao aprovar o relatório.
    - Fecha a vigência do valor anterior (competencia_fim = mês anterior)
    - Insere novo registro com competencia_inicio = mes_ref
    Aceita dicts aninhados: {custos_mensais: {condominio: 1880.51}}.
    """
    linhas = _flatten_parametros(parametros)
    now = _date.today().isoformat()

    with get_db() as conn:
        for chave, valor in linhas.items():
            if valor is None:
                continue
            valor_json = json.dumps(valor, ensure_ascii=False)
            tipo_dado, descricao = _infer_meta(chave, valor)

            atual = conn.execute("""
                SELECT id, valor, competencia_inicio FROM parametros_vigentes
                WHERE unidade_id=? AND parametro=? AND competencia_fim IS NULL
                ORDER BY competencia_inicio DESC LIMIT 1
            """, (unidade_id, chave)).fetchone()

            if atual:
                if atual["competencia_inicio"] == mes_ref:
                    # Mesmo mês: atualiza no lugar (inclui tipo_dado/descricao caso estejam ausentes)
                    if atual["valor"] != valor_json:
                        conn.execute("""
                            UPDATE parametros_vigentes
                            SET valor=?, tipo_dado=?, descricao=?,
                                alterado_em=?, alterado_por=?
                            WHERE id=?
                        """, (valor_json, tipo_dado, descricao, now, alterado_por, atual["id"]))
                    else:
                        # Valor igual mas pode faltar metadados (migration de dados antigos)
                        conn.execute("""
                            UPDATE parametros_vigentes
                            SET tipo_dado=COALESCE(tipo_dado, ?),
                                descricao=COALESCE(descricao, ?)
                            WHERE id=?
                        """, (tipo_dado, descricao, atual["id"]))
                else:
                    # Novo mês: fecha anterior e insere
                    if atual["valor"] != valor_json:
                        comp_fim = _mes_anterior(mes_ref)
                        conn.execute("""
                            UPDATE parametros_vigentes SET competencia_fim=?
                            WHERE id=?
                        """, (comp_fim, atual["id"]))
                        conn.execute("""
                            INSERT INTO parametros_vigentes
                                (unidade_id, parametro, valor, tipo_dado, descricao,
                                 competencia_inicio, alterado_por, alterado_em)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (unidade_id, chave, valor_json, tipo_dado, descricao,
                              mes_ref, alterado_por, now))
            else:
                # Primeiro registro
                conn.execute("""
                    INSERT INTO parametros_vigentes
                        (unidade_id, parametro, valor, tipo_dado, descricao,
                         competencia_inicio, alterado_por, alterado_em)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (unidade_id, chave, valor_json, tipo_dado, descricao,
                      mes_ref, alterado_por, now))


def seed_parametros_from_yaml(unidade_id: str, cfg: dict,
                               competencia_inicio: str = "2020-01"):
    """
    Semeia parâmetros do YAML no banco como ponto de partida histórico.
    Comportamento idempotente: semeia apenas os parâmetros que ainda
    não existem no DB, preservando todos os registros já gravados.
    """
    para_gravar: dict = {}
    _extrair_editaveis(cfg, para_gravar)
    if not para_gravar:
        return

    with get_db() as conn:
        existentes = {row["parametro"] for row in conn.execute(
            "SELECT DISTINCT parametro FROM parametros_vigentes WHERE unidade_id=?",
            (unidade_id,)
        ).fetchall()}

    novos = {k: v for k, v in para_gravar.items() if k not in existentes}
    if novos:
        salvar_parametros(unidade_id, competencia_inicio, novos,
                          alterado_por="seed_yaml")


def get_historico_parametros(unidade_id: str) -> list[dict]:
    """Retorna histórico completo de parâmetros para auditoria."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT parametro, valor, tipo_dado, descricao,
                   competencia_inicio, competencia_fim,
                   alterado_em, alterado_por
            FROM parametros_vigentes
            WHERE unidade_id=?
            ORDER BY parametro, competencia_inicio DESC
        """, (unidade_id,)).fetchall()
    result = []
    for r in rows:
        try:
            val = json.loads(r["valor"])
        except Exception:
            val = r["valor"]
        result.append({
            "parametro":          r["parametro"],
            "descricao":          r["descricao"],
            "tipo_dado":          r["tipo_dado"],
            "valor":              val,
            "competencia_inicio": r["competencia_inicio"],
            "competencia_fim":    r["competencia_fim"] or "Em aberto",
            "alterado_em":        r["alterado_em"],
            "alterado_por":       r["alterado_por"],
        })
    return result


# ─── helpers internos ─────────────────────────────────────────────────────────

# Chaves puramente estruturais: definem o TIPO de contrato, nunca os valores.
# Tudo que não está aqui pode (e deve) ir para o banco.
_ESTRUTURAIS = frozenset({
    # Identidade do contrato — nunca mudam operacionalmente
    "id", "nome", "contratante", "ativo", "inicio",
    # Tipo de calculador e template — mudança requer alteração de código
    "tipo_calculo", "tipo_relatorio", "relatorio", "pdfs", "linhas",
    # Blocos complexos do Pátio — gerenciados pela calculadora própria
    "outros_servicos", "carregadores", "manutencao",
    # Legado: parcelas fixas estruturadas (Medcenter antigo)
    "pagamento_parcelado",
    # Flag puramente informacional
    "prejuizo_correcao_anual",
})

# Listas cujos VALORES são operacionais (percentuais, faixas, mínimos)
_OPERACIONAIS_LISTA = frozenset({
    "faixas", "faixas_aluguel", "splits", "repasses",
})

# Strings operacionais (índice de reajuste)
_OPERACIONAIS_STR = frozenset({"reajuste_indice"})


def _flatten_parametros(d: dict, prefix: str = "") -> dict:
    """
    Achata dicts aninhados em dot-notation.
    Listas e valores simples são preservados como estão.
      {custos_mensais: {condominio: 1880}} → {"custos_mensais.condominio": 1880}
      {faixas: [{ate:100000, percentual:0.85}]}  → {"faixas": [{...}]}
    """
    result = {}
    for k, v in d.items():
        chave = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten_parametros(v, chave))
        elif v is not None:
            result[chave] = v
    return result


def _extrair_editaveis(cfg: dict, destino: dict, prefix: str = ""):
    """
    Extrai parâmetros operacionais do YAML para seed/persistência no banco.
    Captura:
      - escalares numéricos (PE, alíquotas, percentuais, custos)
      - listas operacionais (faixas, faixas_aluguel, splits, repasses)
      - strings operacionais (reajuste_indice)
    """
    flags = {k for k in cfg if k.startswith("tem_") or k.startswith("has_")}
    ignorar = _ESTRUTURAIS | flags

    for k, v in cfg.items():
        if k in ignorar:
            continue
        chave = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            _extrair_editaveis(v, destino, chave)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            destino[chave] = v
        elif isinstance(v, list) and k in _OPERACIONAIS_LISTA:
            destino[chave] = v
        elif isinstance(v, str) and k in _OPERACIONAIS_STR:
            destino[chave] = v


def _mes_anterior(mes_ref: str) -> str:
    """'2026-06' → '2026-05'"""
    ano, mes = int(mes_ref[:4]), int(mes_ref[5:7])
    if mes == 1:
        return f"{ano-1}-12"
    return f"{ano}-{mes-1:02d}"


# ─── funções de domínio ────────────────────────────────────────────────────────

def salvar_lancamento(resultado: ResultadoUnidade):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(unidade_id, mes_referencia)
            DO UPDATE SET faturamento=excluded.faturamento,
                          resultado_json=excluded.resultado_json,
                          status=excluded.status
        """, (
            resultado.unidade_id,
            resultado.mes_referencia,
            resultado.faturamento,
            json.dumps(resultado.__dict__, ensure_ascii=False),
            resultado.status,
        ))
        if resultado.prejuizo_acumulado_saida != 0 or resultado.status == "aprovado":
            conn.execute("""
                INSERT INTO saldos_acumulados (unidade_id, prejuizo_acumulado)
                VALUES (?, ?)
                ON CONFLICT(unidade_id)
                DO UPDATE SET prejuizo_acumulado=excluded.prejuizo_acumulado,
                              atualizado_em=datetime('now')
            """, (resultado.unidade_id, resultado.prejuizo_acumulado_saida))


def corrigir_saldo_anual(unidade_id: str, percentual_ipca: float,
                         alterado_por: str = "operador") -> float:
    """
    Aplica correção anual pelo IPCA ao prejuízo acumulado de uma unidade.
    O saldo é NEGATIVO (prejuízo), então multiplica por (1 + ipca) tornando-o
    mais negativo — ou seja, o prejuízo cresce com a inflação.
    Retorna o novo saldo.
    """
    saldo_atual = get_saldo_acumulado(unidade_id)
    if saldo_atual >= 0:
        return saldo_atual
    novo_saldo = round(saldo_atual * (1 + percentual_ipca), 2)
    now = _date.today().isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO saldos_acumulados (unidade_id, prejuizo_acumulado, atualizado_em)
            VALUES (?, ?, ?)
            ON CONFLICT(unidade_id)
            DO UPDATE SET prejuizo_acumulado=excluded.prejuizo_acumulado,
                          atualizado_em=excluded.atualizado_em
        """, (unidade_id, novo_saldo, now))
    return novo_saldo


def get_saldo_acumulado(unidade_id: str) -> float:
    with get_db() as conn:
        row = conn.execute(
            "SELECT prejuizo_acumulado FROM saldos_acumulados WHERE unidade_id=?",
            (unidade_id,)
        ).fetchone()
        return row["prejuizo_acumulado"] if row else 0.0


def get_lancamentos_mes(mes_referencia: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM lancamentos WHERE mes_referencia=? ORDER BY unidade_id",
            (mes_referencia,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_historico_anual(unidade_id: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT ano, dados_json FROM historico_anual WHERE unidade_id=? ORDER BY ano",
            (unidade_id,)
        ).fetchall()
        return [{"ano": r["ano"], **json.loads(r["dados_json"])} for r in rows]
