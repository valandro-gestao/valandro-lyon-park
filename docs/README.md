# Lyon Park — Sistema de Fechamento Mensal

Sistema de geração de relatórios mensais de prestação de contas para os 23 estacionamentos gerenciados pela **Lyon Park Estacionamentos**. Desenvolvido pela Valandro Tecnologia.

| | |
|---|---|
| **Status** | Produção |
| **Versão** | v1.1.0 |
| **Plataforma** | Python · Streamlit · Docker · Render |
| **Unidades** | 23 |
| **Calculadoras** | 9 |

---

## Visão Geral

A cada competência (mês/ano), a operadora importa a planilha de faturamento, edita os parâmetros variáveis do mês, calcula o resultado de cada unidade e gera os PDFs de prestação de contas para envio aos contratantes. O sistema garante rastreabilidade completa: parâmetros aprovados em um mês tornam-se padrão no mês seguinte, e qualquer relatório passado pode ser regenerado com os valores exatos da época.

```mermaid
flowchart LR
    A[Planilha Excel] --> B[Parser]
    B --> C[Motor de Cálculo]
    C --> D[PDF]
    D --> E[Workflow]
    E --> F[Aprovação]
    F -->|memória operacional| C
```

---

## Filosofia do Projeto

Estas decisões guiaram o desenvolvimento e continuam guiando a evolução do produto:

**Simplicidade operacional.** O operador não precisa entender o sistema para usá-lo. O fluxo mensal tem etapas claras, com padrões inteligentes que eliminam trabalho repetitivo.

**Regras de negócio explícitas.** Cada calculadora implementa um contrato real, com parâmetros nomeados e lógica documentada. Não existem números mágicos no código.

**Parametrização antes de customização.** Adicionar uma nova unidade não exige alterar código — apenas configurar parâmetros. Uma nova calculadora só é criada quando o modelo contratual é genuinamente diferente dos existentes.

**Evolução incremental.** Nenhuma versão interrompe o fechamento mensal. Cada entrega é aditiva e validada em produção antes da próxima começar.

**Documentação como parte do produto.** Arquitetura, banco de dados, roadmap e padrão tecnológico são documentos de primeira classe — mantidos junto ao código, não em wikis separadas.

**Arquitetura desacoplada.** Cálculo, workflow e interface são camadas independentes. É possível alterar o template do PDF sem tocar nas calculadoras, e vice-versa.

---

## Principais Funcionalidades

**Motor de cálculo com 9 calculadoras cobrindo 23 unidades**
Cada contrato tem seu próprio modelo de cálculo (percentual simples, faixas progressivas, split de resultado, saldo acumulado, co-gestão de pátio). Adicionar uma nova unidade com modelo existente exige apenas uma entrada no YAML — sem alterar código.

**Memória operacional automática**
Ao aprovar um relatório, todos os parâmetros utilizados no cálculo são persistidos como nova vigência. O operador só edita o que realmente mudou mês a mês.

**Versionamento de PDFs**
Ao recalcular um relatório já aprovado, o PDF anterior é arquivado automaticamente com timestamp antes da nova geração. O histórico de versões fica registrado por competência.

**Matching fuzzy de nomes**
O parser da planilha de faturamento mapeia os nomes do Excel para os UIDs do sistema via score de Jaccard normalizado, eliminando trabalho manual na maioria dos meses.

**Workflow completo de fechamento**
`pendente → gerado → revisado → aprovado` com suporte a reabertura e recalculação a qualquer momento.

---

## Arquitetura

O sistema é construído sobre três camadas independentes:

| Camada | Responsabilidade |
|---|---|
| **Calculadoras** (`app/calculators/`) | Recebem `cfg` + faturamento, retornam `ResultadoUnidade`. Sem dependência de UI ou banco. |
| **Motor** (`app/engine.py`) | Resolve parâmetros vigentes (YAML + DB), seleciona a calculadora, orquestra o cálculo. |
| **Relatório** (`app/reporter.py` → `app/renderer.py`) | Traduz `ResultadoUnidade` para `ReportData`, renderiza o template Jinja2 e gera o PDF via WeasyPrint. |

A configuração estrutural de cada unidade (tipo de cálculo, layout do relatório) vive no `data/units.yaml`. Os valores operacionais (ponto de equilíbrio, alíquotas, custos) são persistidos no SQLite com intervalo de vigência por competência, permitindo trilha de auditoria completa.

> Detalhes em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

---

## Tecnologias

| Componente | Tecnologia | Versão |
|---|---|---|
| Interface | Streamlit | 1.58.0 |
| Geração de PDF | WeasyPrint | 69.0 |
| Banco de dados | SQLite (→ Supabase em v2.0) | — |
| Autenticação | streamlit-authenticator + bcrypt | 0.4.2 / 5.0.0 |
| Planilhas | pandas + openpyxl | — |
| Templates | Jinja2 | 3.1.6 |
| Runtime | Python | 3.14 |
| Container | Docker (python:3.14-slim) | — |
| Deploy | Render (Starter, Persistent Disk) | — |

> Padrão tecnológico e estratégia de migração: [`docs/PADRAO_TECNOLOGICO_VALANDRO.md`](docs/PADRAO_TECNOLOGICO_VALANDRO.md).

---

## Estrutura do Projeto

```
lyon-reports/
├── main.py                     # Entrada da aplicação Streamlit + autenticação + tela de login
├── render.yaml                 # Configuração do serviço no Render
├── Dockerfile                  # Build da imagem (python:3.14-slim + WeasyPrint)
├── requirements.txt            # Dependências Python fixadas
│
├── .streamlit/
│   └── config.toml             # Tema claro fixo (light mode obrigatório — ver docs/03_DESIGN_LANGUAGE.md)
│
├── assets/
│   ├── valandro_logo.png       # Logo Valandro — marca primária em Login e Dashboard
│   ├── logo.png                # Logo Lyon Park (uso contextual)
│   └── logo_alt.png            # Variante do logo Lyon Park
│
├── app/
│   ├── paths.py                # Resolução centralizada de caminhos (DATA_DIR)
│   ├── engine.py               # Orquestrador: parâmetros → calculadora → resultado
│   ├── models.py               # Camada SQLite: init, seed, queries, tipos de dados
│   ├── reporter.py             # ResultadoUnidade → ReportData
│   ├── report_data.py          # Dataclasses do relatório (contrato com o template)
│   ├── renderer.py             # ReportData → HTML → PDF (WeasyPrint)
│   ├── run_manager.py          # Workflow, status e versionamento de PDFs
│   ├── relatorio.py            # Histórico anual e comparativo
│   ├── calculators/            # 9 calculadoras independentes
│   ├── parsers/                # Parser de faturamento (Excel) e eventos (MDO)
│   └── ui/                     # Telas Streamlit: entrada, fechamento, revisão, relatórios
│
├── data/
│   ├── units.yaml              # Configuração estrutural das 23 unidades (versionado)
│   └── seed.db                 # Banco inicial com histórico e parâmetros (versionado)
│
├── templates/
│   ├── relatorio.html          # Template Jinja2 do relatório PDF
│   └── report.css              # Estilos (formato A4)
│
├── scripts/
│   ├── setup_env.py            # Gerador interativo do arquivo .env local
│   └── setup.py                # Inicialização manual do banco
│
└── docs/
    ├── README.md               # Este arquivo
    ├── ARQUITETURA.md          # Referência técnica detalhada
    ├── BANCO_DE_DADOS.md       # Seed, DATA_DIR e ciclo de vida do banco
    ├── CHANGELOG.md            # Histórico de versões
    ├── ROADMAP.md              # Estratégia de evolução do produto
    ├── PADRAO_TECNOLOGICO_VALANDRO.md
    └── 03_DESIGN_LANGUAGE.md  # Identidade visual e padrões de UI
```

Em produção, os dados operacionais ficam separados da imagem Docker:

```
/mnt/data/                     ← Persistent Disk do Render (sobrevive a redeploys)
├── db.sqlite                  ← banco operacional (copiado do seed.db na primeira vez)
└── runs/{AAAA-MM}/            ← planilhas importadas, JSONs processados, PDFs
```

> Ciclo de vida do banco e estratégia de seed: [`docs/BANCO_DE_DADOS.md`](docs/BANCO_DE_DADOS.md).

---

## Como Executar Localmente

**Pré-requisitos:** Python 3.14, dependências do WeasyPrint instaladas no sistema (Cairo, Pango, GDK-Pixbuf).

### 1. Instalar dependências

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configurar credenciais

```bash
python scripts/setup_env.py
```

O script solicita nome e senha, gera o hash bcrypt e escreve o arquivo `.env` com o formato correto. O `.env` nunca é versionado.

> **Atenção ao formato:** a variável `AUTH_USERS_YAML` contém `$` no hash bcrypt. Use aspas simples no `.env` para evitar expansão de variável pelo shell. O script `setup_env.py` cuida disso automaticamente. Veja `.env.example` como referência.

### 3. Iniciar a aplicação

```bash
streamlit run main.py
```

O banco SQLite é criado automaticamente a partir de `data/seed.db` na primeira execução.

---

## Como Publicar no Render

O deploy é feito via Docker com configuração em `render.yaml`. O serviço requer **plano Starter** (para Persistent Disk).

### Variáveis de ambiente necessárias no Render

| Variável | Onde configurar | Observação |
|---|---|---|
| `AUTH_USERS_YAML` | Painel do Render (Environment) | Nunca no `render.yaml` — valor sensível |
| `DATA_DIR` | `render.yaml` | Já configurado como `/mnt/data` |
| `PORT` | `render.yaml` | Já configurado como `8501` |
| `APP_ENV` | `render.yaml` | Já configurado como `production` |

`AUTH_USERS_YAML` é marcado como `sync: false` no `render.yaml` — o valor real é configurado manualmente no painel do Render e nunca é versionado.

### Sequência de primeiro deploy

1. Criar o serviço no Render apontando para este repositório
2. Configurar `AUTH_USERS_YAML` no painel de Environment Variables
3. Aguardar o build Docker — na primeira inicialização, o banco é copiado automaticamente de `data/seed.db` para `/mnt/data/db.sqlite`
4. Redeploys subsequentes não afetam o banco operacional existente

---

## Documentação

Os documentos estão organizados na ordem recomendada de leitura para quem está conhecendo o projeto:

| # | Documento | Conteúdo |
|---|---|---|
| 1 | **README** *(este arquivo)* | Visão geral, execução local e deploy |
| 2 | [`docs/ROADMAP.md`](docs/ROADMAP.md) | Estratégia de evolução do produto por versão, com objetivo e valor entregue |
| 3 | [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) | Referência técnica completa: calculadoras, fluxo de parâmetros, banco de dados, decisões de arquitetura |
| 4 | [`docs/BANCO_DE_DADOS.md`](docs/BANCO_DE_DADOS.md) | Seed vs. banco operacional, DATA_DIR, ciclo de vida por cenário |
| 5 | [`docs/PADRAO_TECNOLOGICO_VALANDRO.md`](docs/PADRAO_TECNOLOGICO_VALANDRO.md) | Stack oficial Valandro e princípios que guiam as decisões técnicas |
| 6 | [`docs/CHANGELOG.md`](CHANGELOG.md) | Histórico detalhado de alterações por versão |
| 7 | [`docs/03_DESIGN_LANGUAGE.md`](03_DESIGN_LANGUAGE.md) | Identidade visual, tokens CSS, tipografia, regras de UI |

---

## Roadmap

| Versão | Entrega | Status |
|---|---|---|
| `v1.0.0` | Produção — 23 unidades, 9 calculadoras, workflow completo | **Lançado** |
| `v1.1.0` | Consolidação Operacional — Design Language aplicado, nova UI (Login, Dashboard, Unidade) | **Lançado** |
| `v1.2.0` | Workflow — motivo de reabertura, memória de cálculo no PDF, comparativo de versões | Planejado |
| `v1.3.0` | Parametrização — tela de edição de parâmetros via UI, sem acesso ao banco | Planejado |
| `v1.4.0` | Analytics — indicadores de fechamento, evolução de saldos, dashboards | Planejado |
| `v1.5.0` | Automações — captura automática de planilha, envio de PDFs por email | Planejado |
| `v2.0.0` | Migração Supabase — PostgreSQL + Storage + Auth (MAJOR) | Futuro |

> Objetivos, valor entregue e justificativa de ordem: [`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## Histórico de Versões

### v1.1.0 — 14/08/2026

Aplicação do Design Language da Valandro em toda a interface operacional:

- Nova tela de Login com identidade Valandro (marca primária) e Lyon Park como contexto
- Novo Dashboard de Fechamento com hierarquia visual, resumo operacional e ações por grupo
- Nova tela de Unidade com layout padronizado de parâmetros e resultado
- Tema claro fixado via `.streamlit/config.toml` — sem alternância dark/light
- Tokens CSS oficiais definidos e aplicados consistentemente em todas as telas
- Documentação completa: README, ROADMAP, CHANGELOG, DESIGN_LANGUAGE incorporados ao repositório

### v1.0.0 — 12/08/2026

Primeira versão em produção. Cobre o ciclo completo de fechamento mensal das 23 unidades:

- Motor de cálculo com 9 calculadoras parametrizadas
- Persistência de parâmetros com vigência por competência e memória operacional automática
- Geração de PDF via WeasyPrint com template Jinja2 e layout A4
- Workflow com versionamento automático de PDFs
- Parser de faturamento com matching fuzzy de nomes
- Deploy Docker no Render com Persistent Disk e seed automático do banco
- Autenticação com bcrypt via `streamlit-authenticator`

---

## Segurança

- Senhas armazenadas exclusivamente como hash bcrypt — nunca em texto puro
- Credenciais de produção configuradas apenas no painel do Render, nunca versionadas
- `.env` local excluído do Git via `.gitignore`
- Banco operacional nunca sobrescrito por redeploy — proteção implementada em `app/paths.py`

---

*Desenvolvido pela [Valandro Tecnologia](https://valandro.com.br) para Lyon Park Estacionamentos.*
