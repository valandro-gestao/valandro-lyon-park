"""
Rubricas dinâmicas de custos (v1.2.0 — "Custos e Rubricas Dinâmicas").

`custos_mensais` e `custos_variaveis` (quando mapa livre — ver
app.calculadora_schema, natureza "mapa_rubricas") coexistem em duas
representações em `parametros_vigentes`:

  legado — dict simples, nome técnico é o próprio rótulo:
      {"condominio": 1880.51, "iptu": 500.0}

  novo — lista de itens com id técnico estável e nome editável,
  ordem da lista = ordem de apresentação:
      [{"id": "condominio", "nome": "Condomínio", "valor": 1880.51}, ...]

Este módulo é o ÚNICO lugar que interpreta as duas formas. Nenhum outro
consumidor (calculators, app.ui.fechamento, app.reporter,
app.ui.administracao) faz `isinstance(x, list)` por conta própria —
todos passam por `normalizar_rubricas` e pelas funções auxiliares abaixo.

Por que isso resolve o problema do fallback do YAML sem tocar em
`_merge_dict`: uma unidade legada tem `custos_mensais` como DICT no
YAML. Quando a Administração salva uma nova vigência como LISTA, o
merge em app.engine._merge_dict só mescla recursivamente quando os dois
lados são dict — uma lista sempre SUBSTITUI o valor do YAML por
inteiro. Trocar a forma de armazenamento de dict para lista já é, por
si só, o mecanismo de substituição atômica — nenhuma mudança em
_merge_dict foi necessária.
"""
from __future__ import annotations

import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True)
class RubricaItem:
    id: str
    nome: str
    valor: float


# Rótulos conhecidos de rubricas legadas (nome técnico == chave do dict no
# YAML/dot-notation antiga) — substitui os dicts que antes existiam,
# duplicados, em app.ui.fechamento (_custo_label) e app.reporter
# (_CUSTO_LABELS).
_LABELS_LEGADO: dict[str, str] = {
    "condominio": "Condomínio",
    "iptu": "IPTU",
    "energia_eletrica": "Energia Elétrica",
    "sistema_perto": "Sistema Perto",
    "sistema_automacao": "Sistema Automação",
    "monitoramento": "Monitoramento",
    "aucon": "Aucon / Equip.",
    "instalacoes": "Manutenção Instalações",
    "investimentos": "Investimentos",
    "fundo_recomposicao": "Fundo Recomposição",
    "agua": "Água",
    "internet": "Internet",
    "manutencao_equipamentos": "Manutenção Equip.",
    "seguranca": "Segurança",
    "sistemas_voip": "Sistemas VOIP",
    "perto": "Perto",
    # Chaves de custos_extras dinâmicos (eventos etc. — nunca vêm de cfg,
    # só existiam antes no dict duplicado de app.reporter._CUSTO_LABELS).
    "custos_eventos": "Colaboradores Eventos",
    "investimentos_equipamentos": "Investimentos / Equipamentos",
    "troca_de_lona": "Troca de Lona",
}


def rotulo_exibicao(chave: str) -> str:
    """Resolve o rótulo de exibição de uma chave de `resultado.custos`
    (já computado, congelado num lançamento) ou de uma chave crua de
    dict legado. Três casos:
      1. chave conhecida do vocabulário legado -> rótulo fixo histórico;
      2. chave desconhecida mas "parece" identificador técnico (tudo
         minúsculo/snake_case) -> title-case automático (mesmo fallback
         de sempre para uma rubrica legada nunca antes vista);
      3. chave já é um `nome` digitado pelo operador (tem alguma letra
         maiúscula) -> passa INALTERADA — preserva siglas como "VOIP",
         "ISS", "IPCA" que o operador tenha digitado, e nunca reformata
         o nome vigente de uma rubrica do formato novo.
    Usada só como rede de segurança para JSON histórico já congelado
    (resultado_json de lançamentos antigos) — o formato novo já grava o
    nome pronto em resultado.custos, sem precisar desta função."""
    if chave in _LABELS_LEGADO:
        return _LABELS_LEGADO[chave]
    if chave == chave.lower():
        return chave.replace("_", " ").title()
    return chave


def normalizar_rubricas(valor) -> list[RubricaItem]:
    """Aceita legado (dict nome->valor), novo (lista de
    {id,nome,valor}) ou None/vazio. Devolve sempre uma lista de
    RubricaItem, na ordem de apresentação (ordem do dict/lista de
    origem — dict Python e JSON preservam ordem de inserção)."""
    if not valor:
        return []
    if isinstance(valor, list):
        return [
            RubricaItem(
                id=str(item["id"]),
                nome=str(item.get("nome") or item["id"]),
                valor=float(item.get("valor") or 0.0),
            )
            for item in valor
        ]
    if isinstance(valor, dict):
        return [
            RubricaItem(id=str(k), nome=rotulo_exibicao(str(k)), valor=float(v or 0.0))
            for k, v in valor.items()
        ]
    raise TypeError(f"formato de rubricas não reconhecido: {type(valor)!r}")


def total(itens: list[RubricaItem]) -> float:
    return sum(i.valor for i in itens)


def por_id(itens: list[RubricaItem]) -> "OrderedDict[str, float]":
    """id → valor. Identidade estável — não muda com rename. Usada para
    comparação/diff (ver app.ui.fechamento._get_params_competencia) e
    para aplicar overrides vindos da tela de Fechamento (também
    chaveados por id, nunca por nome, exatamente por serem estáveis
    entre reruns/renomeações)."""
    return OrderedDict((i.id, i.valor) for i in itens)


def custos_com_overrides(valor_cfg, custos_extras: dict | None = None) -> "OrderedDict[str, float]":
    """Nome → valor final, já aplicando overrides de `custos_extras`
    (dict vindo da tela de Fechamento, chaveado por id). É isto — e
    SÓ isto — que os calculators genéricos (faixas, cumulativo,
    resultado_split, repasse_duplo, patio, patio_manutencao) usam para
    popular `resultado.custos`: nenhum deles sabe se `valor_cfg` era
    dict legado ou lista nova.

    O nome já resolvido (rótulo legado ou nome vigente do formato novo)
    vira a própria chave do dict devolvido — é o que flui para dentro
    de `resultado.custos`, e por extensão para o JSON congelado de um
    lançamento aprovado. Por isso reporter.py/fechamento.py nunca
    precisam re-rotular uma chave de `resultado.custos`: ela já está
    pronta para exibição desde que saiu daqui."""
    resultado: "OrderedDict[str, float]" = OrderedDict()
    for item in normalizar_rubricas(valor_cfg):
        valor = (custos_extras or {}).get(item.id, item.valor)
        resultado[item.nome] = float(valor)
    return resultado


def ids_normalizados(*valores) -> set:
    """União dos ids de um ou mais valores de cfg (ex. custos_mensais e
    custos_variaveis juntos). Usada pelos calculators para excluir, do
    loop de "custos extras dinâmicos" (eventos etc. — chaves que nunca
    estiveram em cfg), qualquer chave que já tenha sido consumida como
    override de uma rubrica normal em `custos_com_overrides` — o
    override é sempre chaveado por id, mas o resultado final de
    `custos_com_overrides` é chaveado por nome, então o loop de extras
    não consegue detectar sozinho "isto já foi tratado" só olhando as
    chaves de `resultado.custos`."""
    ids: set = set()
    for valor in valores:
        ids.update(item.id for item in normalizar_rubricas(valor))
    return ids


def gerar_id_unico(nome: str, ids_usados: set) -> str:
    """snake_case sem acentos a partir do nome, com sufixo numérico se
    colidir — mesmo algoritmo usado para o id de unidades e de
    itens de splits/repasses (app.ui.administracao)."""
    base = unicodedata.normalize("NFKD", nome or "")
    base = base.encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    base = re.sub(r"_+", "_", base) or "rubrica"
    novo_id, sufixo = base, 2
    while novo_id in ids_usados:
        novo_id = f"{base}_{sufixo}"
        sufixo += 1
    return novo_id


def para_persistencia(itens: list[RubricaItem]) -> list[dict]:
    """Forma plana (lista de dicts) usada tanto para salvar em
    parametros_vigentes quanto como entrada do editor genérico de
    lista_estruturada (app.ui.administracao._editor_lista_estruturada),
    que não conhece RubricaItem — só listas de dicts comuns."""
    return [{"id": i.id, "nome": i.nome, "valor": i.valor} for i in itens]
