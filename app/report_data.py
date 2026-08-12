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
class Historico:
    anos: list[int]
    indicadores: list[dict]
    # indicadores: [{"label": "Faturamento", "valores": [100, 200, 300]}]


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
