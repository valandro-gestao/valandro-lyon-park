"""
Cobertura permanente da homologação de set/2026 (segunda rodada de feedback
da operadora — Débora). Quatro pontos, unidades já homologadas (MW
Tristeza, Pátio Manutenções, W Tower, Medcenter) preservadas e NÃO tocadas
por nenhuma migração aqui:

  1. Dom Pedro 2021 — março/2021 (Faturamento 0,00, Resultado -9950,00)
     existe na planilha original mas foi descartado do bootstrap por um
     bug de extração (`fat == 0` tratado como "sem dado"). Migration 0014
     restaura esse ÚNICO lançamento em `lancamentos` — arquitetura
     preservada: `lancamentos` continua a única fonte mensal,
     `historico_anual` continua exclusivamente um agregado derivado dela
     (mesma regra genérica de 0006/0011/0012/0013), sem nenhuma tabela
     nem precedência especial. Com os 12 meses reais presentes, o
     agregado fecha sozinho em -104089.03 (confirmado pela operadora).
  2. Viva Trindade — `custos_variaveis.outras_despesas` nunca tinha uma
     linha vigente semeada, por isso não aparecia no editor de Custos
     Variáveis do Fechamento (mesmo mecanismo que já mostra Investimentos
     e Fundo de Recomposição). Migration 0015 semeia a linha que faltava.
  3. Unidade nova criada/configurada só pela Administração (sem YAML,
     modelo COM_FAIXAS — mesmo modelo da EKOS real) — abrir uma
     competência posterior ao início não pode mais lançar
     KeyError('id') em app.rubricas.normalizar_rubricas: o bug estava em
     app.ui.fechamento._get_params_competencia, que tratava QUALQUER
     parâmetro-lista como uma rubrica (mapa_rubricas), mas
     COM_FAIXAS.faixas é uma lista_estruturada SEM campo de identidade.
  4. Taxa de Cobrança (COM_FAIXAS) — schema e calculator já suportavam
     completamente (mesmo mecanismo já usado por Fiergs); cobertura de
     regressão do cálculo completo, mais o metadado "condicao" (existia
     no schema mas nunca era renderizado) e o texto padronizado de ajuda
     de campos percentuais (elimina a ambiguidade "80 ou 0,80").

Execução: python3 tests/testes_homologacao_set2026.py
"""
import os, sys, tempfile, shutil, atexit, json

_SCRATCH = tempfile.mkdtemp(prefix="lyon_testes_homologacao_set2026_")
os.environ["DATA_DIR"] = _SCRATCH
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from migrations import runner
runner.run_all(verbose=False)

_falhas = []


def checar(nome, condicao):
    marca = "[OK]" if condicao else "[FALHOU]"
    print(f"{marca} {nome}")
    if not condicao:
        _falhas.append(nome)


# ═══════════════════════════════════════════════════════════════════════
# 1. Dom Pedro 2021 — backfill defensivo de 2021-03 em `lancamentos`
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. Dom Pedro 2021 — backfill de 2021-03 (arquitetura preservada)")
print("=" * 70)
from app.models import get_historico_anual, get_db

# Nenhuma tabela nova foi criada — historico_anual_oficial NÃO existe.
with get_db() as conn:
    tabela_oficial = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='historico_anual_oficial'"
    ).fetchone()
checar("historico_anual_oficial NÃO foi criada (arquitetura original preservada)", tabela_oficial is None)

with get_db() as conn:
    marco_2021 = conn.execute(
        "SELECT resultado_json FROM lancamentos WHERE unidade_id='dom_pedro' AND mes_referencia='2021-03'"
    ).fetchone()
    total_lancamentos_2021 = conn.execute(
        "SELECT COUNT(*) c FROM lancamentos WHERE unidade_id='dom_pedro' AND mes_referencia LIKE '2021%'"
    ).fetchone()["c"]
checar("2021-03 agora existe em lancamentos (restaurado da planilha original)", marco_2021 is not None)
_dados_marco = json.loads(marco_2021["resultado_json"])
checar("2021-03: Faturamento = 0.00 (planilha)", _dados_marco["faturamento"] == 0.00)
checar("2021-03: Resultado = -9950.00 (planilha)", _dados_marco["resultado"] == -9950.00)
checar("2021-03: status = aprovado (mesma convenção do bootstrap)", _dados_marco["status"] == "aprovado")
checar("Dom Pedro agora tem exatamente 12 lançamentos em 2021", total_lancamentos_2021 == 12)

# historico_anual (único caminho, sem exceção) fecha sozinho em 12 meses.
hist = {h["ano"]: h for h in get_historico_anual("dom_pedro")}
checar("2021: Resultado = -104089.03 (fecha naturalmente com os 12 meses)",
       hist[2021]["resultado"] == -104089.03)
checar("2021: Faturamento = 18299.24 (soma natural dos 12 meses)",
       hist[2021]["faturamento"] == 18299.24)
checar("2021: Aluguel/Repasse = 0.0 (unidade em prejuízo o ano inteiro)",
       hist[2021]["aluguel_calculado"] == 0.0)
checar("2021: quantidade_meses = 12 (agregação natural, sem override)",
       hist[2021]["quantidade_meses"] == 12)

from app.reporter import _formatar_ano_label
checar('rótulo do ano é "2021", não "2021 (11 meses)"',
       _formatar_ano_label(2021, hist[2021]["quantidade_meses"]) == "2021")

# Nenhum outro ano de Dom Pedro foi afetado.
checar("2022 de Dom Pedro continua com 12 meses (inalterado)", hist[2022]["quantidade_meses"] == 12)

# Idempotência: segunda aplicação não insere de novo nem duplica.
with get_db() as conn:
    _mod_0014 = next(m for mid, m in runner._descobrir_migracoes() if mid.startswith("0014"))
    antes = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id='dom_pedro' AND mes_referencia='2021-03'"
    ).fetchone()
    estado_antes = (antes["id"], antes["resultado_json"])
    _mod_0014.apply(conn)
    depois = conn.execute(
        "SELECT id, resultado_json FROM lancamentos WHERE unidade_id='dom_pedro' AND mes_referencia='2021-03'"
    ).fetchone()
    estado_depois = (depois["id"], depois["resultado_json"])
    total_apos_2a = conn.execute(
        "SELECT COUNT(*) c FROM lancamentos WHERE unidade_id='dom_pedro' AND mes_referencia LIKE '2021%'"
    ).fetchone()["c"]
checar("migration 0014 é idempotente (segunda aplicação não altera a linha)", estado_antes == estado_depois)
checar("migration 0014 é idempotente (continua exatamente 12 lançamentos em 2021)", total_apos_2a == 12)

# Defensiva: um valor divergente pré-existente NUNCA é sobrescrito.
_DIR2 = tempfile.mkdtemp(prefix="lyon_testes_homologacao_dompedro_divergente_")
atexit.register(shutil.rmtree, _DIR2, ignore_errors=True)
import subprocess
subprocess.run(
    [sys.executable, "-c",
     "from app.models import init_db, get_db; from migrations import runner; "
     "init_db()\n"
     "with get_db() as conn:\n"
     "    ja = runner.aplicadas(conn)\n"
     "    for mid, mod in runner._descobrir_migracoes():\n"
     "        if mid.startswith('0014') or mid in ja: continue\n"
     "        mod.apply(conn)\n"
     "        conn.execute('INSERT INTO schema_migrations (id) VALUES (?)', (mid,))\n"],
    env={**os.environ, "DATA_DIR": _DIR2}, cwd=_REPO_ROOT, check=True, capture_output=True,
)
import sqlite3
_conn2 = sqlite3.connect(os.path.join(_DIR2, "db.sqlite"))
_conn2.row_factory = sqlite3.Row
_valor_divergente = {
    "unidade_id": "dom_pedro", "mes_referencia": "2021-03", "faturamento": 1.0,
    "resultado": 2.0, "prejuizo_acumulado_entrada": 0.0, "prejuizo_acumulado_saida": 2.0,
    "aluguel_calculado": 0.0, "custos": {}, "extras": {}, "status": "aprovado",
}
_conn2.execute(
    "INSERT INTO lancamentos (unidade_id, mes_referencia, faturamento, resultado_json, status) "
    "VALUES ('dom_pedro', '2021-03', 1.0, ?, 'aprovado')",
    (json.dumps(_valor_divergente),),
)
_conn2.commit()
_mod_0014.apply(_conn2)
_conn2.commit()
_row_final = _conn2.execute(
    "SELECT resultado_json FROM lancamentos WHERE unidade_id='dom_pedro' AND mes_referencia='2021-03'"
).fetchone()
_total_final = _conn2.execute(
    "SELECT COUNT(*) c FROM lancamentos WHERE unidade_id='dom_pedro' AND mes_referencia='2021-03'"
).fetchone()["c"]
_conn2.close()
_dados_final = json.loads(_row_final["resultado_json"])
checar("valor divergente pré-existente NUNCA é sobrescrito (faturamento continua 1.0)",
       _dados_final["faturamento"] == 1.0 and _dados_final["resultado"] == 2.0)
checar("valor divergente: nenhuma linha duplicada foi criada", _total_final == 1)
print()


# ═══════════════════════════════════════════════════════════════════════
# 2. Viva Trindade — Outras Despesas visível/editável no Fechamento
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. Viva Trindade — Outras Despesas aparece no Fechamento")
print("=" * 70)
from app.engine import get_unit_com_params
from app.rubricas import normalizar_rubricas
from app.calculators.cumulativo import calcular_com_aliquota_cumul
from app.calculadora_schema import SCHEMAS_POR_TIPO

u_viva = get_unit_com_params("viva_trindade", "2026-08")
checar("custos_variaveis.outras_despesas agora tem linha vigente",
       "outras_despesas" in (u_viva.get("custos_variaveis") or {}))

itens_cv = normalizar_rubricas(u_viva.get("custos_variaveis"))
ids_cv = {i.id for i in itens_cv}
checar("normalizar_rubricas(custos_variaveis) inclui outras_despesas "
       "(mesmo mecanismo que já renderiza Investimentos no Fechamento)",
       "outras_despesas" in ids_cv)
_item_od = next(i for i in itens_cv if i.id == "outras_despesas")
checar('rótulo resolvido é exatamente "Outras Despesas"', _item_od.nome == "Outras Despesas")
checar("investimentos continua presente ao lado (não foi substituído)", "investimentos" in ids_cv)

# Simula o operador digitando 2400.00 no campo recém-visível (custos_extras
# é exatamente o que app.ui.fechamento._inputs_parametros monta a partir do
# widget e passa para o calculator) — confirma que o valor DIGITADO tem
# prioridade sobre o vigente (0.0), usando a config real resolvida do banco.
r_operacional = calcular_com_aliquota_cumul(
    u_viva, "2026-08", faturamento=48674.03,
    custos_extras={"outras_despesas": 2400.0},
)
checar("outras_despesas digitado no Fechamento (2400.0) chega ao calculator via custos_extras",
       r_operacional.extras.get("outras_despesas") == 2400.0)

# Golden test do fechamento oficial de agosto/2026 (mesmos valores já
# validados em tests/testes_bloco_bloqueia_envio.py) — reconfirma que esta
# migração (só seed de parametros_vigentes) não alterou em nada o cálculo.
_SALDO_ENTRADA_AGOSTO_2026 = -162171.54
cfg_viva_oficial = {
    "id": "viva_trindade", "aliquota_imposto": 0.1425, "percentual_aluguel": 0.85,
    "ponto_equilibrio": 27823.50,
    "custos_mensais": {"condominio": 13039.72, "iptu": 0.0},
    "custos_variaveis": {"outras_despesas": 2400.00, "investimentos": 0.0},
}
r_golden = calcular_com_aliquota_cumul(
    cfg_viva_oficial, "2026-08", faturamento=48674.03,
    saldo_override=_SALDO_ENTRADA_AGOSTO_2026,
)
checar("golden ago/2026: Resultado = -1525.24 (inalterado)", r_golden.resultado == -1525.24)
checar("golden ago/2026: Repasse = 0.0 (inalterado)", r_golden.aluguel_calculado == 0.0)
checar("golden ago/2026: Prejuízo Acumulado final = -163696.78 (inalterado)",
       r_golden.prejuizo_acumulado_saida == -163696.78)

# Idempotência/escopo da migração 0015.
with get_db() as conn:
    _mod_0015 = next(m for mid, m in runner._descobrir_migracoes() if mid.startswith("0015"))
    linhas_antes = conn.execute(
        "SELECT COUNT(*) c FROM parametros_vigentes WHERE unidade_id='viva_trindade' "
        "AND parametro='custos_variaveis.outras_despesas'"
    ).fetchone()["c"]
    _mod_0015.apply(conn)
    linhas_depois = conn.execute(
        "SELECT COUNT(*) c FROM parametros_vigentes WHERE unidade_id='viva_trindade' "
        "AND parametro='custos_variaveis.outras_despesas'"
    ).fetchone()["c"]
    linhas_w_tower = conn.execute(
        "SELECT COUNT(*) c FROM parametros_vigentes WHERE unidade_id='w_tower_caxias' "
        "AND parametro='custos_variaveis.outras_despesas'"
    ).fetchone()["c"]
checar("migration 0015 é idempotente (1 linha antes e depois)", linhas_antes == 1 and linhas_depois == 1)
checar("migration 0015 não criou outras_despesas para W Tower (fora de escopo, homologado)",
       linhas_w_tower == 0)
print()


# ═══════════════════════════════════════════════════════════════════════
# 3. Unidade nova (só Administração, sem YAML) — abre competência sem KeyError
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. Unidade nova via Administração (COM_FAIXAS, sem YAML) — sem KeyError")
print("=" * 70)
from app.models import criar_unidade, salvar_parametros
from app.engine import load_units, calcular
from app.ui.fechamento import _get_params_competencia

criar_unidade(
    id="unidade_nova_teste", nome="Unidade Nova Teste", contratante="Teste LTDA",
    inicio="2026-07-01", tipo_calculo="COM_FAIXAS", tipo_relatorio="SIMPLES",
)
load_units(force=True)

# Configuração via Administração: faixas SEM campo de identidade (mesmo
# formato que o editor de "Faixas de Cálculo" grava — ver
# app.calculadora_schema.SCHEMAS_POR_TIPO["COM_FAIXAS"]["campos"][0]
# ["item_schema"], que não declara nenhum sub-campo gerado_automaticamente),
# mais custos_mensais (mapa_rubricas — DEVE continuar funcionando).
salvar_parametros("unidade_nova_teste", "2026-07", {
    "faixas": [{"ate": 5000.0, "percentual": 0.08}, {"ate": None, "percentual": 0.10}],
    "aliquota_imposto": 0.05,
    "ponto_equilibrio": 0.0,
    "tem_base_taxa_cobranca": True,
    "taxa_cobranca": 0.03,
    "custos_mensais": [{"id": "condominio", "nome": "Condomínio", "valor": 500.0}],
})

# Abrindo uma competência POSTERIOR ao início (início=2026-07, abre 2026-08)
# — exatamente o cenário do bug relatado.
try:
    params = _get_params_competencia("unidade_nova_teste", "2026-08")
    erro_ocorreu = None
except Exception as e:
    params = None
    erro_ocorreu = e
checar("abrir 2026-08 não lança KeyError('id') nem nenhuma outra exceção", erro_ocorreu is None)
if erro_ocorreu:
    print(f"    erro: {erro_ocorreu!r}")
checar("faixas (lista SEM id) não aparece nos params achatados (não é mapa_rubricas)",
       params is not None and not any(k.startswith("faixas") for k in params))
checar("custos_mensais.condominio (mapa_rubricas real) CONTINUA achatado corretamente "
       "(não regrediu ao consertar faixas)",
       params is not None and params.get("custos_mensais.condominio") == 500.0)
checar("aliquota_imposto/taxa_cobranca (escalares) continuam achatados normalmente",
       params is not None and params.get("aliquota_imposto") == 0.05
       and params.get("taxa_cobranca") == 0.03)

# O cálculo completo da competência também funciona de ponta a ponta.
r_nova = calcular("unidade_nova_teste", "2026-08", 10000.0,
                   custos_extras={"base_calculo_taxa_cobranca": 10000.0})
checar("cálculo completo da unidade nova funciona sem erro",
       r_nova.resultado is not None)
# subtotal = 10000*(1-0.05) - taxa_cobranca(300) = 9200; resultado = 9200 -
# custos_mensais(condominio 500) = 8700; faixas: 5000@8%=400 + 3700@10%=370.
checar("faixas aplicadas corretamente (8% até 5000 + 10% do restante = 770.0)",
       r_nova.aluguel_calculado == 770.0)
checar("taxa_cobranca (3% de 10000 = 300.0) descontada no subtotal",
       r_nova.extras.get("taxa_cobranca_valor") == 300.0)
print()


# ═══════════════════════════════════════════════════════════════════════
# 4. Taxa de Cobrança (COM_FAIXAS) — regra já determinada, só cobertura
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. Taxa de Cobrança — schema, calculator e metadado 'condicao'")
print("=" * 70)
_campos_faixas = SCHEMAS_POR_TIPO["COM_FAIXAS"]["campos"]
_campo_taxa = next(c for c in _campos_faixas if c["chave"] == "taxa_cobranca")
checar("schema COM_FAIXAS já declara taxa_cobranca (mesmo mecanismo de Fiergs)",
       _campo_taxa is not None)
checar("taxa_cobranca é condicional a tem_base_taxa_cobranca (obrigatorio_se)",
       _campo_taxa.get("obrigatorio_se") == {"campo": "tem_base_taxa_cobranca", "igual": True})
checar("taxa_cobranca tem metadado 'condicao' explicando a dependência",
       bool(_campo_taxa.get("condicao")))

from app.ui.administracao import _AJUDA_FORMATO_PERCENTUAL, _column_config_editor
checar("texto padrão de ajuda de percentual existe e é inequívoco (0 a 100)",
       "0 a 100" in _AJUDA_FORMATO_PERCENTUAL or "pontos percentuais" in _AJUDA_FORMATO_PERCENTUAL)

_col_percentual = _column_config_editor({"chave": "percentual", "label": "Percentual da Faixa",
                                          "tipo_dado": "percentual", "obrigatorio": True,
                                          "minimo": 0.0, "maximo": 1.0})
checar("coluna de percentual da tabela de faixas usa o texto padrão de ajuda",
       _col_percentual.get("help") == _AJUDA_FORMATO_PERCENTUAL)

print()
if _falhas:
    print(f"=== {len(_falhas)} TESTE(S) FALHARAM: {_falhas} ===")
    sys.exit(1)
print("=== TODOS OS TESTES DA HOMOLOGAÇÃO SET/2026 PASSARAM ===")
