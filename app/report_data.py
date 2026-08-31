"""
Objeto de dados padronizado que o template HTML consome.
Não conhece regras de cálculo nem estrutura de planilhas.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UnidadeInfo:
    nome: str
    contratante: str
    competencia: str        # "2026-06"
    competencia_label: str  # "Junho / 2026"
    data_emissao: str       # "25/06/2026"
    tipo_relatorio: str     # padrao | com_receitas_extras | com_eventos


@dataclass
class Cards:
    faturamento: float
    resultado: float
    repasse: float


@dataclass
class ComparativoMes:
    competencia: str        # "2026-06"
    competencia_label: str  # "Jun/26"
    faturamento: float
    variacao_faturamento: Optional[float]   # None na primeira linha
    resultado: float
    variacao_resultado: Optional[float]
    repasse: float


@dataclass
class LinhaPrestacao:
    descricao: str
    valor: float | None     # None → linha sem valor monetário (ex: tipo "aliquota")
    tipo: str = "normal"    # normal | deducao | subtotal | destaque | total | aliquota | info


@dataclass
class Prestacao:
    linhas: list[LinhaPrestacao]


@dataclass
class LinhaHistoricoAnual:
    ano: int
    ano_label: str
    # ano_label: rótulo pronto para exibição — "2025" quando o ano tem as 12
    # competências, "2024 (10 meses)" / "2026 (1 mês)" quando é parcial (ver
    # app/reporter.py _formatar_ano_label). O template exibe ano_label, nunca
    # ano puro — mesmo padrão de competencia/competencia_label já usado em
    # UnidadeInfo e ComparativoMes.
    valores: dict
    # valores: {"Faturamento": 100.0, "Resultado": None, ...} — chaveado
    # pelo mesmo rótulo que aparece em Historico.colunas, na mesma ordem.


@dataclass
class Historico:
    """Histórico anual — anos em linha, indicadores em coluna (layout
    definido para não crescer horizontalmente conforme novos anos surgem).
    Visão gerencial sintética: `colunas` é sempre o mesmo trio — Faturamento,
    Resultado e Repasse —, os mesmos conceitos dos cards principais. Nunca
    inclui indicador específico de calculadora (Receita Líquida, Ponto de
    Equilíbrio, impostos etc. ficam só na Prestação de Contas da
    competência). Quando a unidade não tiver o dado para um ano, o valor
    fica `None` — o template exibe '—' em vez de inventar ou substituir por
    outro campo."""
    colunas: list[str]
    linhas: list[LinhaHistoricoAnual]


@dataclass
class BlocoReceita:
    """Bloco de receita extra (Outros Serviços, Carregadores etc.)"""
    titulo: str
    linhas: list[LinhaPrestacao]
    repasse_label: Optional[str] = None   # ex: "Repasse 50% (REAL)"


@dataclass
class EventoCompetencia:
    data: str
    evento: str
    horario: str
    qtd_extras: int
    valor_unitario: float
    valor_total: float


@dataclass
class ResumoEvento:
    mes: str
    qtd_extras: int
    valor_total: float


@dataclass
class BlocoEventos:
    eventos_competencia: list[EventoCompetencia]
    resumo: list[ResumoEvento]


@dataclass
class ReportData:
    """Objeto único entregue ao template. O template não conhece nada além deste objeto."""
    unidade: UnidadeInfo
    cards: Cards
    comparativo_12m: list[ComparativoMes]
    prestacao: Prestacao
    historico: Historico
    # Blocos opcionais — template renderiza apenas os que existirem
    blocos_receitas: list[BlocoReceita] = field(default_factory=list)
    bloco_eventos: Optional[BlocoEventos] = None
    # Meta — usado para avisos no template
    comparativo_meses_disponiveis: int = 0   # total de meses encontrados no DB
