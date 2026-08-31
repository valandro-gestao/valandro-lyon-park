# Changelog

## Objetivo

Este documento registra apenas as mudanças relevantes do produto ao longo das versões.

O CHANGELOG complementa o ROADMAP:

- **ROADMAP** → para onde o produto vai.
- **CHANGELOG** → como o produto evoluiu.

---

Este documento registra as mudanças relevantes do produto Lyon Park por versão.

O projeto segue [Semantic Versioning](https://semver.org): `MAJOR.MINOR.PATCH`.
- **MAJOR** — mudança de plataforma que exige migração de dados ou janela de manutenção.
- **MINOR** — funcionalidade nova que não interrompe a operação existente.
- **PATCH** — correção de bug, ajuste de UX ou atualização de dependência.

Para a filosofia de produto e a estratégia de evolução, consulte [`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## [v1.0.0] — 2026-08-12

Primeira versão em produção. Cobre o ciclo completo de fechamento mensal das 23 unidades de estacionamento gerenciadas pela Lyon Park.

### Added

**Motor de cálculo**
- 9 calculadoras cobrindo todos os modelos contratuais ativos: `PERCENTUAL_SIMPLES`, `COM_ALIQUOTA`, `COM_ALIQUOTA_CUMUL`, `COM_FAIXAS`, `COM_ALIQUOTA_SPLIT`, `RESULTADO_SPLIT`, `COM_ALIQUOTA_REPASSE_DUPLO`, `PATIO_OPERACAO`, `PATIO_MANUTENCAO`.
- Suporte completo às 23 unidades, cada uma com configuração estrutural própria em `data/units.yaml`.
- Acumulação de saldo entre competências para contratos com prejuízo carregado (`COM_ALIQUOTA_CUMUL`, `PATIO_MANUTENCAO`).
- Correção anual por IPCA do saldo acumulado (MW Tristeza).
- Calculadora de co-gestão de pátio com dois operadores independentes, cada um com ponto de equilíbrio, custos e percentual próprios (`PATIO_OPERACAO`).
- Repasse para múltiplos beneficiários com aluguel mínimo garantido individual (`COM_ALIQUOTA_REPASSE_DUPLO`).

**Parametrização**
- Tabela `parametros_vigentes` com intervalo de validade por competência (`competencia_inicio` / `competencia_fim`), permitindo regenerar qualquer relatório passado com os parâmetros exatos da época.
- Memória operacional automática: ao aprovar um relatório, todos os parâmetros utilizados no cálculo tornam-se padrão para a competência seguinte. O operador edita apenas o que mudou.
- Seed idempotente de parâmetros a partir do YAML: novos parâmetros são inseridos automaticamente sem sobrescrever valores já editados pelo operador.
- Metadados `tipo_dado` e `descricao` armazenados com cada parâmetro, preparando a base para a futura tela de parametrização via UI (v1.3.0).

**Importação de planilha**
- Parser da planilha de faturamento mensal (Excel `.xlsx`) com detecção automática de colunas.
- Matching fuzzy por score de Jaccard normalizado: os nomes da planilha do cliente são mapeados automaticamente para os UIDs do sistema, sem intervenção manual na maioria dos meses.
- Parser de eventos de MDO (mão de obra) para unidades com custo variável por evento (Fiergs, ILP).
- Confirmação de mapeamento pelo operador antes de prosseguir, com opção de correção manual para casos ambíguos.

**Geração de relatórios**
- Geração de PDF de prestação de contas por unidade, por competência, via WeasyPrint e template Jinja2.
- Layout A4 padronizado com cabeçalho institucional, bloco de resultado, histórico anual de 12 meses e comparativo de indicadores.
- Suporte a relatórios compostos (Pátio Pellegrin gera dois sub-relatórios: Real e Maiojama).
- Versionamento automático de PDFs: ao recalcular um relatório já aprovado, o PDF anterior é arquivado com timestamp antes da nova geração.

**Workflow de fechamento**
- Ciclo completo: `pendente → gerado → revisado → aprovado`, com suporte a reabertura e recalculação a qualquer momento.
- Tela de entrada para importação da planilha e confirmação do mapeamento de nomes.
- Tela de fechamento para edição de parâmetros, cálculo e geração de PDF por unidade.
- Tela de revisão para conferência e aprovação dos relatórios gerados.
- Tela de histórico para acesso a relatórios de competências anteriores.

### Infrastructure

- Deploy Docker no Render com runtime `python:3.14-slim`. Dependências nativas do WeasyPrint (Cairo, Pango, GDK-Pixbuf) instaladas na imagem.
- Persistent Disk de 5 GB em `/mnt/data` (Render Starter): banco de dados e arquivos de runs sobrevivem a redeploys e reinicializações.
- Variável `DATA_DIR` resolvida centralmente em `app/paths.py`: em produção aponta para `/mnt/data`, localmente para `./data`. Todos os módulos importam caminhos deste módulo — nenhum caminho hardcoded no restante da aplicação.
- Banco seed (`data/seed.db`) versionado no repositório com dados históricos das unidades (90 registros de histórico anual, saldos acumulados iniciais, parâmetros vigentes). Copiado automaticamente para `DATA_DIR/db.sqlite` na primeira inicialização — sem intervenção manual no primeiro deploy.
- Proteção explícita contra sobrescrita do banco operacional: se `DB_PATH` já existir, o seed é ignorado. Redeploys não afetam dados de produção.
- Autenticação com `streamlit-authenticator` e senhas armazenadas como hash bcrypt. Hash gerado pelo script `scripts/setup_env.py` — nunca em texto puro.
- Credenciais de produção configuradas exclusivamente no painel do Render via `AUTH_USERS_YAML` (`sync: false` no `render.yaml` — valor nunca versionado).
- `python-dotenv` para carregamento do `.env` local sem expansão de variáveis de shell — evita corrupção do hash bcrypt que contém caracteres `$`.
- Health check configurado em `/_stcore/health` para monitoramento do Render.

### Documentation

- `README.md` — porta de entrada do projeto: visão geral, filosofia, funcionalidades, arquitetura, tecnologias, estrutura, execução local, deploy e navegação da documentação.
- `docs/ARQUITETURA.md` — referência técnica completa: descrição de cada calculadora, fluxo de parâmetros, esquema do banco de dados, decisões de arquitetura e justificativas.
- `docs/BANCO_DE_DADOS.md` — documentação do ciclo de vida do banco: seed vs. banco operacional, comportamento por cenário (primeiro deploy, redeploys, desenvolvimento local), procedimento de atualização do seed.
- `docs/ROADMAP.md` — estratégia de evolução do produto por versão, com objetivo, valor entregue, principais funcionalidades e justificativa da sequência escolhida.
- `docs/PADRAO_TECNOLOGICO_VALANDRO.md` — stack oficial Valandro (Supabase, FastAPI, Python, Render, Docker) e princípios que guiam as decisões técnicas e a migração progressiva.
- `.env.example` — referência de formato para configuração local, com instruções sobre o uso de aspas simples para preservar o hash bcrypt.

---

## [v1.1.0] — 2026-08-14 — Consolidação Operacional

### Added

- Aplicação completa do Design Language da Valandro.
- Nova tela de Login.
- Novo Dashboard de Fechamento.
- Nova tela de Unidade.
- Tema claro fixado para toda a aplicação.
- `README.md`.
- `docs/ROADMAP.md`.
- `docs/CHANGELOG.md`.
- `DESIGN_LANGUAGE` incorporado ao projeto.

### Changed

- Nova hierarquia visual.
- Nova experiência operacional.
- Workflow visual de aprovação.
- Organização do histórico.
- Consistência entre Login, Dashboard e Unidade.

### Infrastructure

- Consolidação da documentação técnica.
- Configuração oficial de tema.
- Estrutura definitiva da v1.1.0.

---

## [1.1.1] - 2026-08-27 — Homologação Operacional e Robustez da Plataforma

### Added

- Persistência automática de rascunhos por competência.
- Receita de Selos para a unidade Fiergs.
- Novos custos variáveis da unidade Viva Open.
- Infraestrutura de migrations SQLite.

### Changed

- Correção do cálculo da unidade IN 1183 conforme a memória de cálculo oficial.
- Correção da vigência histórica do percentual de repasse do Medcenter.
- Persistência dos dados ao sair e retornar para uma unidade.
- Seleção automática do conteúdo dos campos numéricos ao receber foco.
- Ajustes operacionais identificados durante a primeira homologação com a operadora.

### Infrastructure

- Criação do runner de migrations.
- Migration `0001_corrigir_percentual_medcenter`.
- Ajustes de empacotamento Docker para suportar scripts e migrations em produção.

---

## [1.1.2] - 2026-08-28 — Histórico e Consolidação dos Relatórios

### Added

- Restauração do histórico mensal legado (~5 anos, desde 2021) para alimentar o comparativo de 12 meses dos PDFs — antes disponível apenas no histórico anual.
- Histórico operacional independente para Pátio REAL e Pátio MAIOJAMA, na tela de unidade — antes inexistente para o Pátio.
- Memória de cálculo de Outros Serviços (Pátio) detalhada por etapa — Resultado, Repasse 50% e Rateio por contratante com o valor final, em vez de um único valor combinado.

### Changed

- Comparativo mensal do PDF corrigido para considerar a competência atual mesmo antes da aprovação (antes, "Gerar PDF" sem aprovação prévia podia mostrar 11 meses ou menos, mesmo havendo histórico suficiente para 12).
- Histórico operacional da unidade (tela e CSV exportado) reordenado: competência mais recente primeiro, mais antiga por último.
- Layout do Pátio corrigido para largura total — memória de cálculo de REAL e MAIOJAMA deixa de ficar restrita à largura de uma coluna estreita.
- Memória de Outros Serviços consistente entre tela e PDF, com a mesma estrutura de etapas nos dois.
- Nenhuma alteração de regra de cálculo, rateio ou aprovação além das correções já homologadas nesta versão.

### Infrastructure

- Estrutura própria de migrations (`migrations/`), com executor idempotente e registro de aplicação em `schema_migrations` — não substitui nem antecipa Alembic (reservado para a migração a Supabase em v2.0.0).
- `migrations/0002_bootstrap_historico_lancamentos.py` — bootstrap do histórico mensal em `lancamentos`, a partir de um arquivo de dados versionado (`migrations/data/historico_lancamentos.json`) extraído da planilha histórica original.
- `migrations/0003_corrigir_historico_wtower.py` — correção do histórico anual do W-Tower Caxias (`historico_anual`), cuja importação original usava a coluna de IPTU em vez do repasse real.
- `migrations/0004_backfill_maio_2026.py` — backfill pontual da competência 2026-05 para unidades que não tinham lançamento real nem foram cobertas pelo bootstrap inicial, sem sobrescrever nenhum lançamento real já existente.
- Scripts de extração (`scripts/extrair_historico_lancamentos.py`, `scripts/extrair_maio_2026.py`) — uso local e pontual, não fazem parte do runtime da aplicação.

---

## Próxima versão

Próxima versão planejada: v1.2.0 — Workflow.

Consulte [`docs/ROADMAP.md`](docs/ROADMAP.md) para detalhes.

---

## Convenções

### Added
Novas funcionalidades disponibilizadas ao usuário.

### Changed
Alterações de comportamento ou melhorias relevantes em funcionalidades existentes.

### Fixed
Correções de bugs ou inconsistências.

### Infrastructure
Mudanças técnicas relacionadas à arquitetura, deploy, banco de dados, autenticação ou infraestrutura da aplicação.

### Documentation
Atualizações na documentação oficial do projeto.
