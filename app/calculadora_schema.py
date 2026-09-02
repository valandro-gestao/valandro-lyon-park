"""
Schema de parâmetros por calculadora (v1.2.0 — Parâmetros e Vigências).

Fonte de verdade: leitura direta de `app/calculators/*.py`, confirmando
campo a campo como cada calculadora realmente consome `cfg` — nada aqui foi
inferido só pelo nome do parâmetro. `PATIO_OPERACAO` não tem entrada:
continua fora do cadastro genérico (estrutura hardcoded, splits fixos
REAL/MAIOJAMA, dois PDFs — ver app/calculators/patio.py).

Não expõe parâmetros sem efeito real no motor de cálculo:
  - `prejuizo_acumulado_inicial` — nunca lido por nenhuma calculadora; o
    saldo acumulado real vem de `saldos_acumulados`
    (app.models.get_saldo_acumulado), uma tabela à parte, sem vigência por
    competência (é um saldo corrente único, atualizado a cada lançamento).
  - `prejuizo_correcao_anual` — flag puramente informacional (string tipo
    "IPCA"), consumida só pelo script manual de correção anual
    (app.models.corrigir_saldo_anual), não pela calculadora em si.
  - `tem_investimentos` — declarado em 3 unidades do YAML (fk, in_1183,
    viva_trindade) mas nunca lido por nenhum código; a dedução real de
    "investimentos" é dirigida pela PRESENÇA do valor em
    `custos_variaveis.investimentos`, não por essa flag.
  `adicional_fixo` (COM_ALIQUOTA_CUMUL) FOI mantido — avaliado
  explicitamente: `cumulativo.py` soma seu valor ao aluguel calculado
  quando presente, tem efeito real no motor, mesmo que nenhuma unidade
  real o use hoje.

Estrutura de cada campo:
  chave              dot-notation, mesma usada em parametros_vigentes
  label              nome amigável (operacional, não técnico)
  tipo_dado          "moeda" | "percentual" | "inteiro" | "texto" | "booleano"
  natureza           "escalar" | "lista_estruturada" | "mapa_dinamico"
  obrigatorio        obrigatoriedade ADMINISTRATIVA — independente do
                     default técnico da calculadora (ver docstring do
                     módulo: "default_tecnico" abaixo documenta o que a
                     calculadora usa se o campo estiver ausente, mas isso
                     NUNCA substitui a exigência de configuração explícita
                     quando obrigatorio=True)
  obrigatorio_se     alternativa a `obrigatorio` fixo: dict
                     {"campo": <chave>, "igual": <valor>} — o campo só é
                     obrigatório quando outro campo (tipicamente uma flag
                     booleana) tiver aquele valor
  default_tecnico    o que a calculadora usa via cfg.get(..., X) se o
                     campo estiver ausente — documentação, não dispensa
                     "obrigatorio"
  descricao          linguagem operacional, sem fórmula
  editor             sugestão de widget para a UI da próxima etapa
  aceita_vigencia    sempre True nos campos aqui — todos passam por
                     parametros_vigentes hoje ou passarão a passar (flags
                     booleanas, ver app.models._extrair_editaveis)
  condicao           nota textual livre, quando um campo só faz sentido
                     dado outro (ex.: taxa_cobranca com tem_base_taxa_cobranca)

Campos compostos (natureza != "escalar") têm chaves adicionais:
  lista_estruturada: minimo_itens, item_schema (lista de sub-campos, cada
                      um com chave/label/tipo_dado/obrigatorio e,
                      opcionalmente, minimo/maximo — faixa numérica válida,
                      ex. percentual entre 0.0 e 1.0), estrutura_ordenada
                      (opcional — ver abaixo)
  mapa_dinamico:      tipo_valor_item, permite_adicionar_remover (hoje
                      sempre False — ver nota abaixo)

Sub-campo com `"gerado_automaticamente": True` (ex. "id" em splits/repasses):
não é um campo normal de edição — a UI (app.ui.administracao) nunca o
mostra como coluna editável; o valor é preservado por posição ao editar um
item existente, ou gerado a partir do "nome" (mesmo slug do cadastro de
unidade) para um item novo. Esse mesmo sub-campo é usado genericamente por
`validar_estrutura_lista` para checar unicidade — não é preciso marcar
nada além disso no schema para ganhar a validação de "IDs únicos".

`estrutura_ordenada` (só em listas tipo "faixas", ex. COM_FAIXAS.faixas e
COM_ALIQUOTA_CUMUL.faixas_aluguel): `{"campo_limite": "ate"}` — declara que
a lista representa faixas progressivas ordenadas por um sub-campo "até"
opcional (None = sem limite superior). Habilita, de forma genérica (sem
nenhum "if tipo_calculo=="), as regras: limites informados > 0, em ordem
estritamente crescente, e "sem limite" (None) permitido no máximo uma vez
e só na última posição.

Nota sobre mapa_dinamico (custos_mensais/custos_variaveis): o VALOR de cada
rubrica já é vigência-tracked hoje (cada uma vira uma chave própria em
parametros_vigentes, ex. "custos_mensais.condominio"). A LISTA DE NOMES das
rubricas, porém, ainda vem do YAML — confirmado em app.ui.fechamento:
`_inputs_parametros` só renderiza input para uma chave que já existe no cfg
mesclado. `permite_adicionar_remover=False` documenta essa limitação atual;
o editor de rubricas dinâmicas é trabalho de uma etapa futura, não desta.

Validações de modelo (cruzando campos) ficam em `validacoes`, por tipo:
  {"tipo": "algum_de", "campos": [...], "mensagem": "..."}
      — ao menos um dos campos deve estar presente
  {"tipo": "soma_campos", "campos": [...], "alvo": 1.0, "tolerancia": 0.005,
   "mensagem": "..."}
      — soma dos campos escalares deve ficar dentro da tolerância do alvo
  {"tipo": "soma_itens", "campo": "splits", "subcampo": "percentual_split",
   "alvo": 1.0, "tolerancia": 0.005, "mensagem": "..."}
      — soma de um sub-campo em todos os itens de uma lista_estruturada
"""

_TOLERANCIA_PERCENTUAL = 0.005  # 0,5 ponto percentual


SCHEMAS_POR_TIPO: dict[str, dict] = {

    # ─── PERCENTUAL_SIMPLES (Vasco) ────────────────────────────────────────
    "PERCENTUAL_SIMPLES": {
        "campos": [
            {
                "chave": "percentual_aluguel", "label": "Percentual de Aluguel",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": None,
                "descricao": "Percentual aplicado sobre o valor que ultrapassar o ponto de equilíbrio.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "ponto_equilibrio", "label": "Ponto de Equilíbrio",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Valor mínimo mensal a partir do qual o percentual passa a ser aplicado.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "taxa_admin_fixa", "label": "Taxa de Administração Fixa",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": 0.0,
                "descricao": "Valor mínimo cobrado quando o resultado do mês não ultrapassa o ponto de equilíbrio.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
        ],
        "validacoes": [],
    },

    # ─── COM_ALIQUOTA (FK, In 1183, Park Tower, Praia de Bellas...) ────────
    "COM_ALIQUOTA": {
        "campos": [
            {
                "chave": "aliquota_imposto", "label": "Alíquota de Imposto",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Percentual de imposto descontado do faturamento antes do cálculo do repasse. Pode ser 0%, mas precisa ser configurado explicitamente.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "percentual_aluguel", "label": "Percentual de Aluguel",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Percentual aplicado sobre o valor que ultrapassar o ponto de equilíbrio, já descontado o imposto.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "ponto_equilibrio", "label": "Ponto de Equilíbrio",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Valor mínimo mensal a partir do qual o percentual passa a ser aplicado.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "tem_faturamento_carregadores", "label": "Tem Faturamento de Carregadores",
                "tipo_dado": "booleano", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": False,
                "descricao": "Liga um campo extra de faturamento de carregadores elétricos, somado ao faturamento total antes do cálculo.",
                "editor": "toggle", "aceita_vigencia": True,
            },
            {
                "chave": "custos_variaveis.investimentos", "label": "Investimentos (dedução do aluguel)",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": 0.0,
                "descricao": "Quando informado, é descontado do aluguel calculado, gerando um Saldo a Pagar.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
        ],
        "validacoes": [],
    },

    # ─── COM_ALIQUOTA_CUMUL (Anitta Mall, A. Schneider, Dom Pedro, ILP...) ─
    "COM_ALIQUOTA_CUMUL": {
        "campos": [
            {
                "chave": "aliquota_imposto", "label": "Alíquota de Imposto",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Percentual de imposto descontado do faturamento antes do cálculo do repasse.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "ponto_equilibrio", "label": "Ponto de Equilíbrio",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Valor mínimo mensal a partir do qual o repasse passa a ser calculado.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "percentual_aluguel", "label": "Percentual de Aluguel",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": 0.0,
                "descricao": "Percentual aplicado sobre o resultado (já compensado o prejuízo acumulado, se houver). Alternativa às Faixas de Aluguel — configure um dos dois.",
                "editor": "number_percent", "aceita_vigencia": True,
                "condicao": "Alternativa a faixas_aluguel — pelo menos um dos dois deve estar configurado.",
            },
            {
                "chave": "faixas_aluguel", "label": "Faixas de Aluguel",
                "tipo_dado": "json", "natureza": "lista_estruturada",
                "obrigatorio": False, "default_tecnico": None,
                "descricao": "Percentuais progressivos por faixa de valor do resultado, em vez de um percentual único. Alternativa ao Percentual de Aluguel — configure um dos dois.",
                "editor": "tabela_editavel", "aceita_vigencia": True,
                "minimo_itens": 1,
                "estrutura_ordenada": {"campo_limite": "ate"},
                "item_schema": [
                    {"chave": "ate", "label": "Até (R$) — vazio = sem limite", "tipo_dado": "moeda", "obrigatorio": False},
                    {"chave": "percentual", "label": "Percentual da Faixa", "tipo_dado": "percentual", "obrigatorio": True, "minimo": 0.0, "maximo": 1.0},
                ],
            },
            {
                "chave": "taxa_admin_fixa", "label": "Taxa de Administração Fixa",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": 0.0,
                "descricao": "Valor mínimo garantido de repasse, aplicado quando o cálculo normal resultar em menos que isso.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "adicional_fixo", "label": "Adicional Fixo",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": 0.0,
                "descricao": "Valor fixo somado ao repasse calculado todo mês (ex.: parcelamento de equipamentos).",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "tem_faturamento_carregadores", "label": "Tem Faturamento de Carregadores",
                "tipo_dado": "booleano", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": False,
                "descricao": "Liga um campo extra de faturamento de carregadores elétricos, somado ao faturamento total antes do cálculo.",
                "editor": "toggle", "aceita_vigencia": True,
            },
            {
                "chave": "custos_mensais", "label": "Custos Mensais Fixos",
                "tipo_dado": "moeda", "natureza": "mapa_dinamico",
                "obrigatorio": False, "default_tecnico": None,
                "descricao": "Rubricas de custo fixo descontadas todo mês (condomínio, IPTU etc.).",
                "editor": "lista_nome_valor", "aceita_vigencia": True,
                "tipo_valor_item": "moeda", "permite_adicionar_remover": False,
            },
            {
                "chave": "custos_variaveis.investimentos", "label": "Investimentos (dedução do aluguel)",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": 0.0,
                "descricao": "Quando informado, é descontado do aluguel calculado, gerando um Saldo a Pagar. Mutuamente exclusivo com Fundo de Recomposição — o primeiro com valor prevalece.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "custos_variaveis.fundo_recomposicao", "label": "Fundo de Recomposição (dedução do aluguel)",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": 0.0,
                "descricao": "Quando informado, é descontado do aluguel calculado, gerando um Saldo a Pagar. Mutuamente exclusivo com Investimentos — o primeiro com valor prevalece.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
        ],
        "validacoes": [
            {
                "tipo": "algum_de", "campos": ["percentual_aluguel", "faixas_aluguel"],
                "mensagem": "Informe o percentual de aluguel ou cadastre as faixas de aluguel.",
            },
        ],
    },

    # ─── COM_FAIXAS (Fiergs, Monza, NL 2800, Ekos, OKA) ────────────────────
    "COM_FAIXAS": {
        "campos": [
            {
                "chave": "faixas", "label": "Faixas de Cálculo",
                "tipo_dado": "json", "natureza": "lista_estruturada",
                "obrigatorio": True, "default_tecnico": None,
                "descricao": "Percentuais progressivos aplicados por faixa de valor do resultado.",
                "editor": "tabela_editavel", "aceita_vigencia": True,
                "minimo_itens": 1,
                "estrutura_ordenada": {"campo_limite": "ate"},
                "item_schema": [
                    {"chave": "ate", "label": "Até (R$) — vazio = sem limite", "tipo_dado": "moeda", "obrigatorio": False},
                    {"chave": "percentual", "label": "Percentual da Faixa", "tipo_dado": "percentual", "obrigatorio": True, "minimo": 0.0, "maximo": 1.0},
                ],
            },
            {
                "chave": "aliquota_imposto", "label": "Alíquota de Imposto",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Percentual de imposto descontado da receita bruta antes do cálculo. Pode ser 0%, mas precisa ser configurado explicitamente.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "ponto_equilibrio", "label": "Ponto de Equilíbrio",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Valor mínimo mensal descontado antes de aplicar as faixas.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "tem_receita_selos", "label": "Tem Receita de Selos",
                "tipo_dado": "booleano", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": False,
                "descricao": "Liga um campo extra de receita de selos, somado ao faturamento antes do cálculo.",
                "editor": "toggle", "aceita_vigencia": True,
            },
            {
                "chave": "tem_base_taxa_cobranca", "label": "Tem Taxa de Cobrança",
                "tipo_dado": "booleano", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": False,
                "descricao": "Liga a cobrança de uma taxa sobre uma base de cálculo informada mês a mês.",
                "editor": "toggle", "aceita_vigencia": True,
            },
            {
                "chave": "taxa_cobranca", "label": "Percentual da Taxa de Cobrança",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio_se": {"campo": "tem_base_taxa_cobranca", "igual": True},
                "default_tecnico": 0.0,
                "descricao": "Percentual aplicado sobre a base de cálculo da taxa de cobrança.",
                "editor": "number_percent", "aceita_vigencia": True,
                "condicao": "Só relevante quando \"Tem Taxa de Cobrança\" está ligado.",
            },
            {
                "chave": "custos_mensais", "label": "Custos Mensais Fixos",
                "tipo_dado": "moeda", "natureza": "mapa_dinamico",
                "obrigatorio": False, "default_tecnico": None,
                "descricao": "Rubricas de custo fixo descontadas todo mês.",
                "editor": "lista_nome_valor", "aceita_vigencia": True,
                "tipo_valor_item": "moeda", "permite_adicionar_remover": False,
            },
            {
                "chave": "custos_variaveis", "label": "Custos Variáveis",
                "tipo_dado": "moeda", "natureza": "mapa_dinamico",
                "obrigatorio": False, "default_tecnico": None,
                "descricao": "Rubricas de custo variável descontadas todo mês.",
                "editor": "lista_nome_valor", "aceita_vigencia": True,
                "tipo_valor_item": "moeda", "permite_adicionar_remover": False,
            },
        ],
        "validacoes": [],
    },

    # ─── COM_ALIQUOTA_SPLIT (Axis) ──────────────────────────────────────────
    "COM_ALIQUOTA_SPLIT": {
        "campos": [
            {
                "chave": "aliquota_imposto", "label": "Alíquota de Imposto",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Percentual de imposto descontado do faturamento antes do cálculo do repasse.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "ponto_equilibrio", "label": "Ponto de Equilíbrio",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Valor mínimo mensal descontado antes do rateio entre os contratantes.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "splits", "label": "Contratantes (Rateio)",
                "tipo_dado": "json", "natureza": "lista_estruturada",
                "obrigatorio": True, "default_tecnico": None,
                "descricao": "Cada contratante recebe uma fatia do resultado (percentual de rateio) e, sobre essa fatia, seu próprio percentual de repasse.",
                "editor": "tabela_editavel", "aceita_vigencia": True,
                "minimo_itens": 1,
                "item_schema": [
                    {"chave": "id", "label": "Identificador", "tipo_dado": "texto", "obrigatorio": False, "gerado_automaticamente": True},
                    {"chave": "nome", "label": "Nome do Contratante", "tipo_dado": "texto", "obrigatorio": True},
                    {"chave": "percentual_split", "label": "Percentual do Resultado (Rateio)", "tipo_dado": "percentual", "obrigatorio": True, "minimo": 0.0, "maximo": 1.0},
                    {"chave": "percentual_aluguel", "label": "Percentual de Repasse", "tipo_dado": "percentual", "obrigatorio": True, "minimo": 0.0, "maximo": 1.0},
                ],
                "validacao_cruzada": "soma_percentual_split_100",
            },
        ],
        "validacoes": [
            {
                "tipo": "soma_itens", "campo": "splits", "subcampo": "percentual_split",
                "alvo": 1.0, "tolerancia": _TOLERANCIA_PERCENTUAL,
                "mensagem": "Os percentuais de rateio entre os contratantes devem somar 100%.",
            },
        ],
    },

    # ─── RESULTADO_SPLIT (Medcenter, Viva Open Mall) ────────────────────────
    "RESULTADO_SPLIT": {
        "campos": [
            {
                "chave": "aliquota_imposto", "label": "Alíquota de Imposto",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Percentual de imposto descontado do faturamento antes do cálculo do resultado.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "despesas_fixas", "label": "Despesas Fixas",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Valor fixo mensal descontado da receita líquida antes de dividir o resultado. Conceito diferente de Ponto de Equilíbrio.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "percentual_operador", "label": "Percentual do Operador",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.15,
                "descricao": "Fatia do resultado que fica com o operador. Deve somar 100% com o Percentual do Contratante.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "percentual_contratante", "label": "Percentual do Contratante",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.85,
                "descricao": "Fatia do resultado que fica com o contratante. Deve somar 100% com o Percentual do Operador.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "parcela_fixa", "label": "Parcela Fixa",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": 0.0,
                "descricao": "Valor fixo descontado da fatia do contratante para chegar ao Saldo a Pagar.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "custos_mensais", "label": "Custos Mensais Fixos",
                "tipo_dado": "moeda", "natureza": "mapa_dinamico",
                "obrigatorio": False, "default_tecnico": None,
                "descricao": "Rubricas de custo fixo descontadas todo mês (condomínio, IPTU, energia etc.).",
                "editor": "lista_nome_valor", "aceita_vigencia": True,
                "tipo_valor_item": "moeda", "permite_adicionar_remover": False,
            },
            {
                "chave": "custos_variaveis", "label": "Custos Variáveis",
                "tipo_dado": "moeda", "natureza": "mapa_dinamico",
                "obrigatorio": False, "default_tecnico": None,
                "descricao": "Rubricas de custo variável descontadas todo mês.",
                "editor": "lista_nome_valor", "aceita_vigencia": True,
                "tipo_valor_item": "moeda", "permite_adicionar_remover": False,
            },
        ],
        "validacoes": [
            {
                "tipo": "soma_campos", "campos": ["percentual_operador", "percentual_contratante"],
                "alvo": 1.0, "tolerancia": _TOLERANCIA_PERCENTUAL,
                "mensagem": "Os percentuais do Operador e do Contratante devem somar 100%.",
            },
        ],
    },

    # ─── COM_ALIQUOTA_REPASSE_DUPLO (Terreno OKA) ───────────────────────────
    "COM_ALIQUOTA_REPASSE_DUPLO": {
        "campos": [
            {
                "chave": "aliquota_imposto", "label": "Alíquota de Imposto",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Percentual de imposto descontado do faturamento antes do cálculo do repasse.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "ponto_equilibrio", "label": "Ponto de Equilíbrio",
                "tipo_dado": "moeda", "natureza": "escalar",
                "obrigatorio": True, "default_tecnico": 0.0,
                "descricao": "Valor mínimo mensal descontado antes do cálculo dos repasses.",
                "editor": "number_moeda", "aceita_vigencia": True,
            },
            {
                "chave": "tem_base_taxa_cobranca", "label": "Tem Taxa de Cobrança",
                "tipo_dado": "booleano", "natureza": "escalar",
                "obrigatorio": False, "default_tecnico": False,
                "descricao": "Liga a cobrança de uma taxa sobre uma base de cálculo informada mês a mês.",
                "editor": "toggle", "aceita_vigencia": True,
            },
            {
                "chave": "taxa_cobranca", "label": "Percentual da Taxa de Cobrança",
                "tipo_dado": "percentual", "natureza": "escalar",
                "obrigatorio_se": {"campo": "tem_base_taxa_cobranca", "igual": True},
                "default_tecnico": 0.0,
                "descricao": "Percentual aplicado sobre a base de cálculo da taxa de cobrança.",
                "editor": "number_percent", "aceita_vigencia": True,
                "condicao": "Só relevante quando \"Tem Taxa de Cobrança\" está ligado.",
            },
            {
                "chave": "repasses", "label": "Beneficiários do Repasse",
                "tipo_dado": "json", "natureza": "lista_estruturada",
                "obrigatorio": True, "default_tecnico": None,
                "descricao": "Cada beneficiário recebe um percentual do resultado, com um valor mínimo garantido.",
                "editor": "tabela_editavel", "aceita_vigencia": True,
                "minimo_itens": 1,
                "item_schema": [
                    {"chave": "id", "label": "Identificador", "tipo_dado": "texto", "obrigatorio": False, "gerado_automaticamente": True},
                    {"chave": "nome", "label": "Nome do Beneficiário", "tipo_dado": "texto", "obrigatorio": True},
                    {"chave": "percentual", "label": "Percentual do Resultado", "tipo_dado": "percentual", "obrigatorio": True, "minimo": 0.0, "maximo": 1.0},
                    {"chave": "aluguel_minimo", "label": "Valor Mínimo Garantido", "tipo_dado": "moeda", "obrigatorio": False, "minimo": 0.0},
                ],
            },
            {
                "chave": "custos_mensais", "label": "Custos Mensais Fixos",
                "tipo_dado": "moeda", "natureza": "mapa_dinamico",
                "obrigatorio": False, "default_tecnico": None,
                "descricao": "Rubricas de custo fixo descontadas todo mês.",
                "editor": "lista_nome_valor", "aceita_vigencia": True,
                "tipo_valor_item": "moeda", "permite_adicionar_remover": False,
            },
            {
                "chave": "custos_variaveis", "label": "Custos Variáveis",
                "tipo_dado": "moeda", "natureza": "mapa_dinamico",
                "obrigatorio": False, "default_tecnico": None,
                "descricao": "Rubricas de custo variável descontadas todo mês.",
                "editor": "lista_nome_valor", "aceita_vigencia": True,
                "tipo_valor_item": "moeda", "permite_adicionar_remover": False,
            },
        ],
        "validacoes": [],
    },

    # ─── PATIO_MANUTENCAO (Pátio — Manutenções) ─────────────────────────────
    "PATIO_MANUTENCAO": {
        "campos": [
            {
                "chave": "retencao_iss", "label": "Retenção de ISS",
                "tipo_dado": "percentual", "natureza": "escalar",
                # Obrigatório ADMINISTRATIVAMENTE mesmo tendo default técnico
                # sensato (0.05) no código — decisão explícita: uma unidade
                # nova não deve ser considerada configurada só porque o
                # motor tem um valor de segurança. Unidades históricas que
                # já usam o default continuam funcionando (o valor já está
                # persistido em parametros_vigentes desde o seed inicial —
                # ver seed_parametros_from_yaml).
                "obrigatorio": True, "default_tecnico": 0.05,
                "descricao": "Percentual de ISS retido sobre a receita antes do cálculo do resultado.",
                "editor": "number_percent", "aceita_vigencia": True,
            },
            {
                "chave": "custos_mensais", "label": "Custos Mensais Fixos",
                "tipo_dado": "moeda", "natureza": "mapa_dinamico",
                "obrigatorio": False, "default_tecnico": None,
                "descricao": "Rubricas de custo fixo descontadas todo mês (ex.: manutenção de equipamentos, instalações).",
                "editor": "lista_nome_valor", "aceita_vigencia": True,
                "tipo_valor_item": "moeda", "permite_adicionar_remover": False,
            },
        ],
        "validacoes": [],
    },
}


def campos_do_tipo(tipo_calculo: str) -> list[dict]:
    return SCHEMAS_POR_TIPO.get(tipo_calculo, {}).get("campos", [])


def validacoes_do_tipo(tipo_calculo: str) -> list[dict]:
    return SCHEMAS_POR_TIPO.get(tipo_calculo, {}).get("validacoes", [])


def campos_obrigatorios(tipo_calculo: str) -> list[dict]:
    """Só os incondicionalmente obrigatórios — campos com `obrigatorio_se`
    (obrigatoriedade condicional) não entram aqui; ver
    app.models.validar_configuracao_unidade para a avaliação condicional."""
    return [c for c in campos_do_tipo(tipo_calculo) if c.get("obrigatorio")]


def campo_por_chave(tipo_calculo: str, chave: str) -> dict | None:
    """Busca um campo do schema pela chave exata (dot-notation incluso, ex.
    "custos_variaveis.investimentos"). Usada pela UI (app.ui.administracao)
    para formatar um valor de parametros_vigentes sem duplicar a definição
    do campo — inclui também, quando aplicável, uma correspondência por
    prefixo para chaves de mapa_dinamico (ex. "custos_mensais.condominio"
    casa com o campo "custos_mensais", tipo_valor_item indica o formato)."""
    for c in campos_do_tipo(tipo_calculo):
        if c["chave"] == chave:
            return c
        if c.get("natureza") == "mapa_dinamico" and chave.startswith(c["chave"] + "."):
            return c
    return None


# ─── validação pura de parâmetros (v1.2.0 — Parâmetros e Vigências) ───────────
#
# Tudo abaixo é puro: só lê `params`/`campo`/`regra`, nunca toca banco. É a
# MESMA lógica usada por app.models.validar_configuracao_unidade (com params
# vindos de parametros_vigentes) e por app.ui.administracao (com params
# candidatos, ainda não salvos, para dar feedback imediato ao editar um
# campo composto) — não duplicar esta lógica em nenhum dos dois lugares.

def resolver_valor(params: dict, chave: str):
    """Resolve uma chave simples ou dot-notation dentro de um dict de
    parâmetros já reconstruído (grupos aninhados como dict, listas como
    list — mesmo formato que app.models.get_parametros_vigentes devolve)."""
    if "." in chave:
        grupo, sub = chave.split(".", 1)
        return (params.get(grupo) or {}).get(sub)
    return params.get(chave)


def campo_obrigatorio_efetivo(campo: dict, params: dict) -> bool:
    """True se o campo é obrigatório NESTA avaliação — direto (obrigatorio)
    ou condicionado a outro campo (obrigatorio_se, ex.: taxa_cobranca só é
    obrigatória quando tem_base_taxa_cobranca=True)."""
    condicional = campo.get("obrigatorio_se")
    if condicional:
        return resolver_valor(params, condicional["campo"]) == condicional["igual"]
    return bool(campo.get("obrigatorio"))


def validar_estrutura_lista(campo: dict, itens: list) -> list[str]:
    """Valida a ESTRUTURA INTERNA de uma lista_estruturada já não-vazia —
    sub-campos obrigatórios, faixas numéricas (minimo/maximo) e, quando
    declarado, a ordenação de faixas (estrutura_ordenada) e a unicidade de
    identificadores (sub-campo gerado_automaticamente). Lista vazia é
    sempre válida aqui: "pelo menos 1 item" depende de o campo estar
    obrigatório no contexto atual (algo que esta função não conhece) — ver
    `validar_parametros`, que aplica essa checagem antes de chamar esta."""
    if not itens:
        return []

    erros: list[str] = []
    label = campo["label"]
    item_schema = campo.get("item_schema", [])

    for idx, item in enumerate(itens, start=1):
        for sub in item_schema:
            valor = item.get(sub["chave"]) if isinstance(item, dict) else None
            if sub.get("obrigatorio") and (valor is None or valor == ""):
                erros.append(f'{label}, item {idx}: informe "{sub["label"]}".')
                continue
            if valor is None:
                continue
            eh_percentual = sub.get("tipo_dado") == "percentual"
            minimo, maximo = sub.get("minimo"), sub.get("maximo")
            if minimo is not None and valor < minimo:
                erros.append(
                    f'{label}, item {idx}: "{sub["label"]}" deve ser um percentual entre 0% e 100%.'
                    if eh_percentual else
                    f'{label}, item {idx}: "{sub["label"]}" não pode ser negativo.'
                )
            if maximo is not None and valor > maximo:
                erros.append(
                    f'{label}, item {idx}: "{sub["label"]}" deve ser um percentual entre 0% e 100%.'
                    if eh_percentual else
                    f'{label}, item {idx}: "{sub["label"]}" está acima do máximo permitido.'
                )

    estrutura = campo.get("estrutura_ordenada")
    if estrutura:
        campo_limite = estrutura["campo_limite"]
        limites = [item.get(campo_limite) for item in itens]
        sem_limite_idxs = [i for i, v in enumerate(limites) if v is None]
        if len(sem_limite_idxs) > 1:
            erros.append('No máximo uma faixa pode ser "Sem limite".')
        elif sem_limite_idxs and sem_limite_idxs[0] != len(limites) - 1:
            erros.append('Somente a última faixa pode ser "Sem limite".')
        informados = [v for v in limites if v is not None]
        if any(v <= 0 for v in informados):
            erros.append("Os limites das faixas devem ser maiores que zero.")
        if any(informados[i] >= informados[i + 1] for i in range(len(informados) - 1)):
            erros.append("Os limites das faixas devem estar em ordem crescente.")

    campo_id = next((s["chave"] for s in item_schema if s.get("gerado_automaticamente")), None)
    if campo_id:
        ids = [item.get(campo_id) for item in itens if item.get(campo_id)]
        if len(ids) != len(set(ids)):
            erros.append(f'Existem identificadores duplicados em "{label}" — ajuste os nomes.')

    return erros


def validar_regra_cruzada(regra: dict, params: dict) -> list[str]:
    """Avalia uma única regra de `validacoes` (algum_de/soma_campos/
    soma_itens) contra um dict de parâmetros já resolvido. Pura."""
    erros: list[str] = []
    tipo = regra["tipo"]

    if tipo == "algum_de":
        algum_presente = any(
            resolver_valor(params, c) not in (None, [], {}) for c in regra["campos"]
        )
        if not algum_presente:
            erros.append(regra["mensagem"])

    elif tipo == "soma_campos":
        valores = [resolver_valor(params, c) for c in regra["campos"]]
        if any(v is None for v in valores):
            return erros  # ausência já reportada individualmente
        soma = sum(valores)
        if abs(soma - regra["alvo"]) > regra["tolerancia"]:
            erros.append(f"{regra['mensagem']} (hoje soma {soma * 100:.1f}%)")

    elif tipo == "soma_itens":
        itens = resolver_valor(params, regra["campo"]) or []
        if not itens:
            return erros  # ausência já reportada individualmente
        soma = sum(item.get(regra["subcampo"], 0.0) or 0.0 for item in itens)
        if abs(soma - regra["alvo"]) > regra["tolerancia"]:
            erros.append(f"{regra['mensagem']} (hoje soma {soma * 100:.1f}%)")

    return erros


def validar_parametros(tipo_calculo: str, params: dict) -> list[str]:
    """Valida um dict de parâmetros já resolvido contra o schema completo do
    tipo de cálculo — mensagens em português operacional, lista vazia
    quando está tudo completo. Pura: usada por
    app.models.validar_configuracao_unidade (params vindos do banco) e por
    app.ui.administracao (params candidatos, ainda não salvos)."""
    campos = campos_do_tipo(tipo_calculo)
    erros: list[str] = []

    for campo in campos:
        chave = campo["chave"]
        natureza = campo.get("natureza", "escalar")
        valor = resolver_valor(params, chave)
        obrig = campo_obrigatorio_efetivo(campo, params)

        if natureza == "lista_estruturada":
            # A estrutura do que já foi digitado é validada sempre — mesmo
            # num campo opcional (ex.: faixas_aluguel quando percentual_
            # aluguel também está presente) — mas "precisa ter pelo menos
            # um item" só se aplica quando o campo está de fato obrigatório
            # nesta avaliação; vazio num campo opcional é só "não usado".
            if not valor:
                if obrig:
                    erros.append(f'Cadastre pelo menos uma linha em "{campo["label"]}".')
                continue
            if len(valor) < campo.get("minimo_itens", 1):
                erros.append(f'Cadastre pelo menos uma linha em "{campo["label"]}".')
            erros.extend(validar_estrutura_lista(campo, valor))
            continue

        if not obrig:
            continue

        if natureza == "mapa_dinamico":
            if not valor:
                erros.append(f'Configure ao menos uma rubrica em "{campo["label"]}".')
        else:
            if valor is None:
                erros.append(f'Informe "{campo["label"]}".')

    for regra in validacoes_do_tipo(tipo_calculo):
        erros.extend(validar_regra_cruzada(regra, params))

    return erros
