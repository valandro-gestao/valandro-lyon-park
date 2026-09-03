from dataclasses import dataclass, field
from typing import Optional
import sqlite3, json, os, yaml
from datetime import date as _date

from app.paths import DB_PATH, UNITS_YAML

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
    # Custos variáveis — Viva Open Mall (v1.1.1)
    "custos_variaveis.seguranca":                ("moeda",      "Segurança"),
    "custos_variaveis.internet":                 ("moeda",      "Internet"),
    "custos_variaveis.sistemas_voip":            ("moeda",      "Sistemas VOIP"),
    "custos_variaveis.perto":                    ("moeda",      "Perto"),
    # Flags booleanas (v1.2.0) — antes só existiam em data/units.yaml,
    # nunca vigência-tracked. Ver _extrair_editaveis.
    "tem_faturamento_carregadores":              ("booleano",   "Faturamento de Carregadores"),
    "tem_receita_selos":                         ("booleano",   "Receita de Selos"),
    "tem_base_taxa_cobranca":                    ("booleano",   "Taxa de Cobrança"),
}


def _infer_meta(chave: str, valor) -> tuple[str, str]:
    """Fallback para parâmetros não mapeados em _PARAM_META."""
    if chave in _PARAM_META:
        return _PARAM_META[chave]
    if isinstance(valor, bool):
        return ("booleano", chave)
    if isinstance(valor, list):
        return ("json", chave)
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
    from app.paths import ensure_dirs, seed_db_if_missing
    ensure_dirs()
    seed_db_if_missing()
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

            -- Rascunho de trabalho (v1.1.1): estado bruto dos campos de entrada
            -- de uma unidade, salvo a cada alteração, antes da aprovação.
            -- Não afeta lançamentos, saldos acumulados nem parâmetros vigentes.
            -- Salvar estado != aprovar: este rascunho é apenas o trabalho em
            -- andamento da operadora, limpo quando a unidade é aprovada.
            CREATE TABLE IF NOT EXISTS rascunhos_unidade (
                unidade_id TEXT NOT NULL,
                mes_referencia TEXT NOT NULL,
                dados_json TEXT NOT NULL,
                atualizado_em TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (unidade_id, mes_referencia)
            );

            -- Configuração ESTRUTURAL das unidades (v1.2.0) — identidade e
            -- roteamento (qual calculadora, qual template de relatório),
            -- nunca parâmetro operacional (isso continua em
            -- parametros_vigentes). O schema é criado aqui; o BOOTSTRAP
            -- inicial (só quando a tabela está vazia — ver
            -- bootstrap_unidades_se_vazia logo abaixo) também acontece
            -- aqui, para que uma instalação nova nunca fique com 0
            -- unidades disponíveis. A migration 0007 formaliza o mesmo
            -- bootstrap como um passo auditável do histórico de deploy —
            -- reaproveita esta função, não duplica a lógica.
            CREATE TABLE IF NOT EXISTS unidades (
                id             TEXT PRIMARY KEY,
                nome           TEXT NOT NULL,
                contratante    TEXT NOT NULL,
                ativo          INTEGER NOT NULL DEFAULT 1,
                inicio         TEXT NOT NULL,
                tipo_calculo   TEXT NOT NULL,
                tipo_relatorio TEXT NOT NULL DEFAULT 'padrao',
                criado_em      TEXT DEFAULT (datetime('now')),
                atualizado_em  TEXT DEFAULT (datetime('now'))
            );
        """)
        # Migration: adiciona colunas em DBs criados antes desta versão
        for col in ("tipo_dado TEXT", "descricao TEXT"):
            try:
                conn.execute(f"ALTER TABLE parametros_vigentes ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass  # coluna já existe

        bootstrap_unidades_se_vazia(conn)


def bootstrap_unidades_se_vazia(conn) -> int:
    """
    Carrega as unidades de data/units.yaml na tabela `unidades` — SOMENTE
    se ela estiver completamente vazia. Não é sincronização: se a tabela já
    tiver qualquer linha (mesmo uma só, mesmo uma unidade criada manualmente
    sem bloco YAML correspondente), esta função não faz absolutamente nada
    — nunca insere unidades "faltantes", nunca atualiza uma já existente.
    Depois do bootstrap inicial (aqui ou pela migration 0007, que reaproveita
    esta mesma função), o banco é a única autoridade; data/units.yaml só
    volta a ser lido para os campos ainda não migrados para tabela própria
    (ver app.engine._yaml_blocos) — nunca mais para popular `unidades`.

    Corrida entre duas inicializações quase simultâneas: o INSERT usa
    "OR IGNORE" deliberadamente — mesmo que ambas leiam a tabela vazia antes
    de qualquer uma escrever, a segunda apenas não duplica nada (SQLite
    serializa as duas transações de escrita; a que perder a corrida encontra
    os ids já presentes e os ignora, sem erro). Retorna quantas linhas esta
    chamada efetivamente inseriu (0 se não fez nada).
    """
    total = conn.execute("SELECT COUNT(*) AS c FROM unidades").fetchone()["c"]
    if total > 0:
        return 0

    if not UNITS_YAML.exists():
        return 0

    with open(UNITS_YAML, encoding="utf-8") as f:
        dados = yaml.safe_load(f)

    inseridas = 0
    for u in dados["unidades"]:
        cur = conn.execute("""
            INSERT OR IGNORE INTO unidades
                (id, nome, contratante, ativo, inicio, tipo_calculo, tipo_relatorio)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            u["id"],
            u["nome"],
            u["contratante"],
            1 if u.get("ativo", True) else 0,
            u["inicio"],
            u["tipo_calculo"],
            u.get("tipo_relatorio", "padrao"),
        ))
        inseridas += cur.rowcount
    return inseridas


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
      - booleanos (tem_faturamento_carregadores, tem_receita_selos,
        tem_base_taxa_cobranca — v1.2.0: passam a ter vigência por
        competência como qualquer outro parâmetro, em vez de só existir no
        YAML. Antes desta versão, todo `tem_*`/`has_*` era explicitamente
        excluído aqui; isso nunca mudou o comportamento das 23 unidades
        existentes porque app.ui.fechamento ainda lê essas 3 flags de
        app.engine.get_unit() — YAML/`_yaml_blocos()` — não daqui. Capturar
        o valor no banco é só o que faltava para uma unidade cadastrada só
        pela Administração conseguir configurá-las também.)
      - listas operacionais (faixas, faixas_aluguel, splits, repasses)
      - strings operacionais (reajuste_indice)
    """
    for k, v in cfg.items():
        if k in _ESTRUTURAIS:
            continue
        chave = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            _extrair_editaveis(v, destino, chave)
        elif isinstance(v, bool):
            destino[chave] = v
        elif isinstance(v, (int, float)):
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


# ─── rascunho de trabalho (persistência de estado antes da aprovação) ────────

def salvar_rascunho_unidade(unidade_id: str, mes_ref: str, dados: dict):
    """
    Persiste o estado bruto dos campos de entrada de uma unidade (faturamento,
    parâmetros, custos etc.), chamado a cada rerender da tela de detalhe.
    Não toca lançamentos, saldos acumulados ou parâmetros vigentes — é apenas
    o trabalho em andamento da operadora antes de aprovar.
    """
    with get_db() as conn:
        conn.execute("""
            INSERT INTO rascunhos_unidade (unidade_id, mes_referencia, dados_json, atualizado_em)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(unidade_id, mes_referencia)
            DO UPDATE SET dados_json=excluded.dados_json, atualizado_em=excluded.atualizado_em
        """, (unidade_id, mes_ref, json.dumps(dados, ensure_ascii=False)))


def carregar_rascunho_unidade(unidade_id: str, mes_ref: str) -> dict | None:
    """Retorna o último rascunho salvo para a unidade/competência, ou None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT dados_json FROM rascunhos_unidade WHERE unidade_id=? AND mes_referencia=?",
            (unidade_id, mes_ref)
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["dados_json"])
    except (json.JSONDecodeError, TypeError):
        return None


def limpar_rascunho_unidade(unidade_id: str, mes_ref: str):
    """Remove o rascunho após a aprovação — os parâmetros vigentes passam a
    ser a fonte de verdade a partir daqui (memória operacional)."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM rascunhos_unidade WHERE unidade_id=? AND mes_referencia=?",
            (unidade_id, mes_ref)
        )


def get_historico_anual(unidade_id: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT ano, dados_json FROM historico_anual WHERE unidade_id=? ORDER BY ano",
            (unidade_id,)
        ).fetchall()
        return [{"ano": r["ano"], **json.loads(r["dados_json"])} for r in rows]


# ─── administração de unidades (v1.2.0) ───────────────────────────────────────
# Persistência dos campos ESTRUTURAIS de `unidades` (nome, contratante,
# início, status, tipo_calculo, tipo_relatorio) para a tela de Administração.
# Nunca grava parâmetro operacional aqui — isso continua em
# parametros_vigentes, via salvar_parametros (inalterado).

def unidade_id_existe(unidade_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT 1 FROM unidades WHERE id=?", (unidade_id,)).fetchone()
    return row is not None


def unidade_possui_lancamentos(unidade_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM lancamentos WHERE unidade_id=? LIMIT 1", (unidade_id,)
        ).fetchone()
    return row is not None


def unidade_possui_lancamento_no_mes(unidade_id: str, mes_referencia: str) -> bool:
    """Existe lançamento (rascunho ou aprovado) desta unidade nesta
    competência específica — diferente de unidade_possui_lancamentos, que
    é "em algum mês, qualquer um". Usada por app.engine.get_unidades_ativas
    para nunca esconder do Fechamento uma competência que já teve
    cálculo/consulta real, mesmo que a configuração de hoje não cubra mais
    aquele mês (ex.: parâmetro corrigido depois, unidade que só passou a
    ter configuração válida numa competência posterior)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM lancamentos WHERE unidade_id=? AND mes_referencia=? LIMIT 1",
            (unidade_id, mes_referencia),
        ).fetchone()
    return row is not None


def status_operacional(u: dict) -> str:
    """"ativa" | "inativa" — direto do campo `ativo` da unidade, sem
    heurística. Substitui a antiga status_unidade(): ativo é a única
    autoridade sobre este eixo; "está com parâmetro configurado ou não" é
    um eixo SEPARADO (ver status_configuracao), nunca misturado aqui."""
    return "ativa" if u.get("ativo") else "inativa"


def status_configuracao(u: dict, competencia: str) -> str:
    """"completa" | "incompleta" | "nao_aplicavel" (tipo_calculo sem schema
    declarado em SCHEMAS_POR_TIPO, ex. PATIO_OPERACAO — validar_configuracao
    _unidade não tem opinião sobre esses, então não faz sentido rotular
    como "completa"). Delega inteiramente a validar_configuracao_unidade —
    nunca usa "tem algum parâmetro salvo" como atalho para esta decisão."""
    from app.calculadora_schema import campos_do_tipo
    if not campos_do_tipo(u["tipo_calculo"]):
        return "nao_aplicavel"
    return "incompleta" if validar_configuracao_unidade(u["id"], competencia) else "completa"


def pode_ativar_unidade(unidade_id: str, competencia: str) -> list[str]:
    """Mensagens que bloqueiam a ativação da unidade na competência
    informada — lista vazia quando pode ativar. Verifica, nesta ordem:
    (1) a competência não pode ser anterior ao início estrutural da
    unidade — não faz sentido operar antes de existir; (2) configuração
    completa na competência (validar_configuracao_unidade).

    Função de leitura pura — não decide sozinha o status: quem ativa de
    fato é a UI, chamando atualizar_unidade(ativo=True) só depois de ver
    esta função devolver []. Nunca inativa nada — não existe caminho de
    código que desative uma unidade automaticamente por falha aqui."""
    unidade = get_unidade(unidade_id)
    if not unidade:
        return [f"Unidade '{unidade_id}' não encontrada."]

    erros = []
    inicio_mes = (unidade["inicio"] or "")[:7]  # "AAAA-MM-DD" -> "AAAA-MM"
    if inicio_mes and competencia < inicio_mes:
        erros.append(f"A unidade inicia sua operação em {inicio_mes[5:7]}/{inicio_mes[:4]}.")
    erros.extend(validar_configuracao_unidade(unidade_id, competencia))
    return erros


def get_unidade(unidade_id: str) -> dict | None:
    """Leitura direta de `unidades`, sem cache — a tela de Administração
    precisa sempre do valor mais recente gravado. Diferente de
    app.engine.get_unit(), que é cacheado por processo para o fluxo
    operacional e não deve ser usado para popular um formulário de edição."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM unidades WHERE id=?", (unidade_id,)).fetchone()
    return dict(row) if row else None


def listar_unidades_admin() -> list[dict]:
    """Todas as unidades, direto do banco, sem cache — para a lista da tela
    de Administração."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM unidades ORDER BY nome").fetchall()
    return [dict(r) for r in rows]


def unidades_exemplo_por_tipo(tipo_calculo: str, limite: int = 3) -> list[str]:
    """Nomes de até `limite` unidades ATIVAS que usam este tipo_calculo hoje
    — alimenta a ajuda contextual do cadastro (app.calculadora_labels).
    Nunca hardcoded: reflete o estado real do banco a cada chamada."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT nome FROM unidades WHERE tipo_calculo=? AND ativo=1 ORDER BY nome LIMIT ?",
            (tipo_calculo, limite),
        ).fetchall()
    return [r["nome"] for r in rows]


def criar_unidade(id: str, nome: str, contratante: str, inicio: str,
                   tipo_calculo: str, tipo_relatorio: str = "padrao") -> None:
    """Cria uma unidade nova — sempre `ativo=0` (nasce inativa e, via de
    regra, com configuração incompleta — ver status_operacional/
    status_configuracao). Não existe caminho de código para criar já
    ativa; é a proteção contra uso operacional sem parâmetros válidos
    (ver pode_ativar_unidade / regra de ativação na UI).

    Levanta ValueError se o id já existir. A UI deve checar
    unidade_id_existe antes para dar uma mensagem amigável sem precisar
    tratar exceção, mas a proteção final — a que realmente impede duplicar —
    é esta, não a checagem prévia na tela."""
    if unidade_id_existe(id):
        raise ValueError(f"Já existe uma unidade com o identificador '{id}'.")
    with get_db() as conn:
        conn.execute("""
            INSERT INTO unidades (id, nome, contratante, ativo, inicio, tipo_calculo, tipo_relatorio)
            VALUES (?, ?, ?, 0, ?, ?, ?)
        """, (id, nome, contratante, inicio, tipo_calculo, tipo_relatorio))


def atualizar_unidade(unidade_id: str, *, nome: str = None, contratante: str = None,
                       inicio: str = None, tipo_calculo: str = None,
                       tipo_relatorio: str = None, ativo: bool = None) -> None:
    """Atualiza campos estruturais de uma unidade existente — só altera os
    campos passados (None = não mexe nesse campo). `id` nunca é parâmetro
    aqui: não existe caminho de código para renomear o identificador de uma
    unidade.

    Esta função não decide se pode alterar tipo_calculo (unidade já tem
    lançamento?) nem se pode ativar (configuração completa na competência
    de ativação?) — quem chama (a UI) já deve ter checado
    unidade_possui_lancamentos / pode_ativar_unidade antes. Não duplicar
    essa decisão aqui evita a regra de negócio divergir entre dois
    lugares. `ativo=True`/`False` aqui é só a escrita mecânica do campo —
    a decisão de permitir ativar mora inteiramente em pode_ativar_unidade."""
    campos = {
        "nome": nome, "contratante": contratante, "inicio": inicio,
        "tipo_calculo": tipo_calculo, "tipo_relatorio": tipo_relatorio,
        "ativo": (1 if ativo else 0) if ativo is not None else None,
    }
    sets = [f"{k}=?" for k, v in campos.items() if v is not None]
    valores = [v for v in campos.values() if v is not None]
    if not sets:
        return
    sets.append("atualizado_em=datetime('now')")
    with get_db() as conn:
        conn.execute(
            f"UPDATE unidades SET {', '.join(sets)} WHERE id=?",
            (*valores, unidade_id),
        )


# ─── validação de configuração por modelo (v1.2.0) ────────────────────────────
#
# A lógica de validação em si (pura, sem banco) mora em app.calculadora_schema
# — validar_parametros() e as funções que ela usa — para ser compartilhada
# entre esta função (params vindos do banco) e app.ui.administracao (params
# candidatos, ainda não salvos, para feedback imediato ao editar um campo
# composto). Não duplicar essa lógica aqui.

def validar_configuracao_unidade(unidade_id: str, competencia: str) -> list[str]:
    """
    "Configuração completa" para a competência informada, avaliando os
    PARÂMETROS EFETIVOS daquela competência — a mesma resolução que o
    motor de cálculo usaria para calcular (bloco legado do YAML como base,
    parâmetros já vigentes no banco por cima, DB sempre prevalecendo; ver
    app.engine.get_parametros_efetivos). Não é mais "banco puro": uma
    unidade cujo YAML legado já carrega um valor plenamente válido não é
    mais considerada incompleta só por esse valor nunca ter sido copiado
    para parametros_vigentes — o motor já usaria esse valor do YAML de
    qualquer forma, então a validação administrativa deve concordar com
    ele. O que continua nunca acontecendo aqui: aceitar um valor que o
    motor NÃO usaria (ex. um default técnico interno da calculadora que
    nunca aparece em cfg) — get_parametros_efetivos não inventa nada, só
    resolve exatamente a mesma mescla YAML+DB que get_unit_com_params usa,
    sem o efeito colateral de escrever (lazy seed).

    Retorna uma lista de mensagens em português operacional — vazia quando
    a configuração está completa. Não altera nada no banco (função de
    leitura pura — get_parametros_efetivos também é pura, nunca faz
    INSERT). Usada hoje só pela tela de Administração — não afeta o fluxo
    de fechamento nem bloqueia aprovação de relatório.
    """
    from app.calculadora_schema import campos_do_tipo, validar_parametros
    from app.engine import get_parametros_efetivos

    unidade = get_unidade(unidade_id)
    if not unidade:
        return [f"Unidade '{unidade_id}' não encontrada."]

    tipo_calculo = unidade["tipo_calculo"]
    if not campos_do_tipo(tipo_calculo):
        # PATIO_OPERACAO (ou qualquer tipo sem schema declarado): fora do
        # escopo desta validação — não é papel deste módulo opinar sobre ele.
        return []

    params = get_parametros_efetivos(unidade_id, competencia)
    return validar_parametros(tipo_calculo, params)
