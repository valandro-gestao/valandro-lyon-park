"""
Nomes amigáveis e descrições conceituais dos modelos de cálculo e dos tipos
de relatório — consumidos só pela tela de Administração > Unidades
(app.ui.administracao), para nunca expor código técnico (COM_ALIQUOTA,
RESULTADO_SPLIT etc.) na interface da operadora.

Os exemplos de unidades que usam cada modelo NÃO ficam hardcoded aqui — são
consultados em tempo real no banco (app.models.unidades_exemplo_por_tipo),
para sempre refletir a configuração real do sistema, não uma lista congelada
no momento em que este arquivo foi escrito.
"""

# tipo_calculo (código técnico) -> label amigável exibido na UI.
# Inclui PATIO_OPERACAO (para a edição da unidade "patio" já existente
# continuar mostrando o modelo dela) mesmo esse tipo não aparecendo como
# opção no cadastro de unidade nova — ver TIPOS_CALCULO_PARA_CADASTRO.
TIPO_CALCULO_LABELS: dict[str, str] = {
    "PERCENTUAL_SIMPLES":         "Percentual Simples",
    "COM_ALIQUOTA":               "Percentual com Imposto",
    "COM_ALIQUOTA_CUMUL":         "Percentual com Imposto e Saldo Acumulado",
    "COM_FAIXAS":                 "Faixas Progressivas",
    "COM_ALIQUOTA_SPLIT":         "Percentual com Rateio entre Contratantes",
    "RESULTADO_SPLIT":            "Divisão de Resultado (Operador/Contratante)",
    "COM_ALIQUOTA_REPASSE_DUPLO": "Percentual com Repasse a Dois Beneficiários",
    "PATIO_MANUTENCAO":           "Manutenção com Retenção de ISS",
    "PATIO_OPERACAO":             "Operação de Pátio",
}

# Descrição curta, em linguagem operacional (sem fórmula, sem jargão de
# desenvolvimento) — mostrada abaixo do campo "Modelo de Cálculo" quando o
# operador seleciona ou pede a ajuda contextual.
TIPO_CALCULO_DESCRICOES: dict[str, str] = {
    "PERCENTUAL_SIMPLES": (
        "Aplica um percentual sobre o valor que ultrapassar um mínimo mensal "
        "combinado (ponto de equilíbrio). Abaixo desse mínimo, não há repasse."
    ),
    "COM_ALIQUOTA": (
        "Desconta o imposto do faturamento e aplica um percentual sobre o "
        "que ultrapassar o ponto de equilíbrio."
    ),
    "COM_ALIQUOTA_CUMUL": (
        "Funciona como o modelo com imposto, mas compensa meses de "
        "prejuízo com os resultados dos meses seguintes antes de calcular "
        "o repasse."
    ),
    "COM_FAIXAS": (
        "Aplica percentuais diferentes por faixa de valor do resultado — "
        "cada faixa pode ter um percentual próprio, geralmente crescente."
    ),
    "COM_ALIQUOTA_SPLIT": (
        "Calcula o resultado da unidade e divide entre dois ou mais "
        "contratantes, cada um com seu próprio percentual de repasse."
    ),
    "RESULTADO_SPLIT": (
        "Calcula o resultado após impostos e despesas e divide esse "
        "resultado entre operador e contratante."
    ),
    "COM_ALIQUOTA_REPASSE_DUPLO": (
        "Calcula o resultado da unidade e repassa a dois beneficiários "
        "diferentes, cada um com percentual e valor mínimo garantido próprios."
    ),
    "PATIO_MANUTENCAO": (
        "Desconta a retenção de ISS da receita, depois os custos do "
        "período, e mantém um saldo acumulado entre competências."
    ),
    "PATIO_OPERACAO": (
        "Modelo de co-gestão específico do Pátio, com estrutura própria — "
        "não disponível para novas unidades."
    ),
}

# tipo_relatorio (código técnico) -> label amigável.
TIPO_RELATORIO_LABELS: dict[str, str] = {
    "padrao":              "Padrão",
    "com_eventos":         "Com Eventos",
    "com_receitas_extras": "Com Receitas Extras",
}

# Modelos oferecidos no cadastro de uma unidade NOVA. PATIO_OPERACAO fica de
# fora deliberadamente: estrutura hardcoded (splits fixos REAL/MAIOJAMA,
# dois PDFs, blocos de outros_servicos/carregadores/manutencao próprios) —
# cadastrar um "novo Pátio" pela tela criaria uma unidade que nunca calcula
# nada corretamente. Não aparece nem como opção desabilitada: simplesmente
# não é oferecida.
TIPOS_CALCULO_PARA_CADASTRO: list[str] = [
    "PERCENTUAL_SIMPLES",
    "COM_ALIQUOTA",
    "COM_ALIQUOTA_CUMUL",
    "COM_FAIXAS",
    "COM_ALIQUOTA_SPLIT",
    "RESULTADO_SPLIT",
    "COM_ALIQUOTA_REPASSE_DUPLO",
    "PATIO_MANUTENCAO",
]

# Tipos de relatório oferecidos no cadastro de uma unidade nova.
# "com_receitas_extras" fica de fora — hoje só funciona para a unidade
# "patio", e mesmo assim porque o próprio tipo_calculo PATIO_OPERACAO aciona
# esse fluxo explicitamente no reporter (não este campo); oferecer para
# outra unidade não geraria o bloco correspondente.
TIPOS_RELATORIO_PARA_CADASTRO: list[str] = ["padrao", "com_eventos"]
