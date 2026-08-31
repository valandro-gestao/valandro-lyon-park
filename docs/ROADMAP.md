# ROADMAP — Lyon Park Fechamento Mensal

**Produto:** Gerador de Relatórios Lyon Park  
**Versão atual:** 1.1.2  
**Padrão de versões:** [Semantic Versioning 2.0.0](https://semver.org)  
**Referência arquitetural:** [PADRAO_TECNOLOGICO_VALANDRO.md](./PADRAO_TECNOLOGICO_VALANDRO.md)

---

## Como ler este documento

Este documento descreve a estratégia de evolução do Lyon Park como **produto**, não como lista de tarefas técnicas. Para cada versão estão registrados: o problema que ela resolve, o valor que entrega à operadora, as funcionalidades principais e o motivo pelo qual foi colocada nessa posição da sequência.

**Convenção de versões:**
- **MAJOR** (`X.0.0`) — mudança de plataforma que exige migração de dados ou janela de manutenção. Não altera regras de negócio.
- **MINOR** (`1.X.0`) — funcionalidade nova que não quebra a operação existente. A operadora continua fechando normalmente após qualquer MINOR.
- **PATCH** (`1.0.X`) — correção de bug, ajuste de UX ou atualização de dependência sem impacto funcional.

**Princípio central:** nenhuma versão pode interromper o fechamento mensal das 23 unidades. Qualquer entrega que ameace isso está mal escalonada e deve ser redimensionada.

**Ordem de prioridade deste roadmap:** operação real → autonomia da operadora → automação do trabalho manual → evolução arquitetural. Ver [Princípios que guiam este roadmap](#princípios-que-guiam-este-roadmap).

---

## Linha do tempo

```
ago/2026   v1.0.0  Produção                           — concluída em 12/08/2026
           v1.1.0  Consolidação Operacional           — concluída em 14/08/2026
           v1.1.1  Homologação e Robustez             — concluída em 27/08/2026
           v1.1.2  Histórico e Consolidação           — concluída em 28/08/2026
           v1.2.0  Autonomia Operacional               — próxima versão
set/2026   ·       Marco: fechamento de ago/2026 100% pela ferramenta
           v1.3.0  Automação de Entradas e Fechamento
           v1.4.0  Workflow
           v1.5.0  Analytics
2027+      v2.0.0  Migração Supabase (MAJOR)
           v2.1.0  Perfis e Auditoria
           v2.2.0  API REST
           v2.3.0  Integrações
           v3.0.0  Testes e CI/CD
```

---

## v1.0.0 — Produção
**Lançamento:** 15/08/2026
**Status:** Concluída.

### Problema que resolve
A Lyon Park precisava de um sistema para fechar mensalmente 23 unidades com contratos distintos — cada uma com sua própria fórmula de cálculo, parâmetros e formato de relatório — e gerar os PDFs de prestação de contas para envio aos contratantes. Antes deste sistema, esse trabalho era feito manualmente em planilhas.

### Valor entregue
A operadora passa a ter um processo unificado, auditável e reproduzível para o fechamento mensal. Os cálculos são feitos automaticamente a partir da planilha de faturamento importada. Os PDFs são gerados com layout padronizado. O histórico de parâmetros e resultados fica preservado no banco.

### O que está em produção

**Motor de cálculo — 9 calculadoras cobrindo 23 unidades:**
- `PERCENTUAL_SIMPLES` — Vasco da Gama
- `COM_ALIQUOTA` — Anitta Mall, FK Moinhos, FK Rosário, Park Tower, Praia de Belas
- `COM_ALIQUOTA_CUMUL` — A. Schneider, Dom Pedro, ILP, In 1183, MW Tristeza, Viva Trindade, W Tower Caxias
- `COM_FAIXAS` — Ekos, Fiergs, Monza, NL 2800, OKA
- `COM_ALIQUOTA_SPLIT` — Axis
- `RESULTADO_SPLIT` — Medcenter, Viva Open Mall
- `COM_ALIQUOTA_REPASSE_DUPLO` — Terreno OKA
- `PATIO_OPERACAO` — Pátio Pellegrin (Real + Maiojama)
- `PATIO_MANUTENCAO` — Pátio Manutenção

**Workflow completo:** importação de planilha → edição de parâmetros → cálculo → geração de PDF → revisão → aprovação → reabertura. Versionamento automático de PDFs por competência.

**Memória operacional:** parâmetros aprovados em um mês tornam-se padrão no mês seguinte. A operadora só precisa alterar o que realmente mudou.

**Infraestrutura:** Streamlit + SQLite + Docker + Render Persistent Disk. Autenticação com senha + hash bcrypt. Seed automático do banco na primeira inicialização.

### Fora do escopo desta versão
Perfis de usuário, tela de parametrização, Supabase, API REST, testes automatizados, CI/CD, dashboards de gestão.

---

## v1.1.0 — Consolidação Operacional
**Lançamento:** 14/08/2026
**Status:** Concluída.

### Problema que resolve
A v1.0.0 era funcionalmente completa, mas a interface herdou os padrões visuais padrão do Streamlit sem identidade. Qualquer novo desenvolvimento produziria telas inconsistentes entre si. Antes de evoluir funcionalmente o produto, era necessário estabelecer a linguagem visual como referência estável.

### Valor entregue
O sistema passa a ter identidade visual consistente em todas as telas — Login, Dashboard e Unidade falam a mesma língua visual. A Valandro aparece como fabricante do produto; Lyon Park como contexto operacional. O Design Language está documentado e é a referência para todo desenvolvimento futuro.

### O que foi entregue

**Tela de Login redesenhada**  
Layout centralizado com logo Valandro como marca primária, campo de contexto "Lyon Park · Fechamento mensal", formulário de credenciais com tokens CSS próprios. Nenhuma dependência de CDN externo.

**Dashboard de Fechamento redesenhado**  
Hierarquia visual clara: marca discreta no topo, competência em destaque, resumo operacional consolidado, ações em linha com o contexto, lista de unidades agrupada por status. Layout contido em `max-width: 1180px` (otimizado para notebook 14").

**Tela de Unidade padronizada**  
Cabeçalho com mesma identidade do Dashboard. Parâmetros à esquerda, resultado à direita. Workflow visual de aprovação com chips de status coloridos.

**Tema claro fixo**  
`.streamlit/config.toml` com `base = "light"` e tokens de cor alinhados ao Design Language. Elimina variação de aparência entre sistemas operacionais com preferência dark mode.

**Design Language documentado e incorporado ao repositório**  
`docs/03_DESIGN_LANGUAGE.md` com princípios permanentes, regras consolidadas, tokens CSS oficiais, decisão de tipografia e hierarquia de identidade de marca.

### Fora do escopo desta versão
Comparativo com mês anterior, alertas de parâmetro, logs operacionais estruturados, correções de bugs de cálculo. Esses itens passam para versões seguintes.

### Por que esta versão veio antes das melhorias operacionais
Estabelecer o Design Language primeiro evita que cada nova funcionalidade crie seus próprios padrões visuais ad hoc. Com a linguagem estabelecida, toda tela futura tem uma referência clara — e o custo de manter consistência visual cai progressivamente.

---

## v1.1.1 — Homologação Operacional e Robustez da Plataforma
**Lançamento:** 27/08/2026
**Status:** Concluída.

### Problema que resolve
A primeira rodada de homologação real com a operadora expôs problemas que só aparecem em uso operacional de verdade: dados digitados se perdiam ao sair de uma unidade antes de aprovar, um cálculo de repasse divergia do contrato real (In 1183), a vigência histórica de um percentual estava incorreta desde o início (Medcenter), e a operadora perdia tempo apagando o valor de campos numéricos antes de digitar um novo. Nenhum desses problemas é arquitetural, mas todos afetam a confiança da operadora no sistema.

### Valor entregue
A operadora deixa de perder trabalho digitado ao navegar entre unidades. Duas unidades passam a calcular exatamente o que o contrato determina. A base para corrigir dados históricos com segurança — migrations versionadas e idempotentes — passa a existir no projeto, preparando o terreno para a v1.1.2.

### O que foi entregue

**Persistência automática de rascunhos por competência**  
Qualquer campo alterado numa unidade é salvo automaticamente, por competência, antes da aprovação. Sair da unidade ou perder a sessão não apaga mais o trabalho em andamento. Aprovar continua sendo uma ação separada — salvar estado não é aprovar.

**Correção do cálculo do In 1183**  
Investigação contra a Memória de Cálculo oficial e a planilha histórica real (5 anos) identificou que a unidade estava configurada com um mecanismo de prejuízo acumulado que o contrato nunca previu, além de um valor informativo (R$1.353, "Aquisição de Equipamentos") sendo somado indevidamente ao repasse. Corrigida para `COM_ALIQUOTA`, sem compensação de prejuízo — conforme o contrato.

**Correção da vigência histórica do Medcenter**  
O percentual de repasse ao contratante estava seedado como 85% desde 2020, quando o valor contratual correto era 75% até junho/2026. Corrigido via vigência por competência (`parametros_vigentes`), preservando os relatórios já aprovados.

**Receita de Selos (Fiergs) e novos custos variáveis (Viva Open)**  
Fiergs passa a somar a Receita de Selos ao faturamento antes do cálculo, com a composição explícita na memória de cálculo. Viva Open passa a ter os custos variáveis Segurança, Internet, Sistemas VOIP e Perto — rubricas já rastreadas pela operadora fora do sistema.

**Seleção automática do conteúdo dos campos numéricos**  
O primeiro clique em qualquer campo numérico da aplicação seleciona todo o conteúdo, permitindo sobrescrever diretamente em vez de apagar dígito por dígito.

**Infraestrutura de migrations SQLite**  
Estrutura própria (`migrations/`) com executor idempotente e registro de aplicação — base técnica reaproveitada por todas as correções de dado histórico da v1.1.2.

### Fora do escopo desta versão
Tela de cadastro de unidades, tela de parametrização administrativa, vigência de parâmetros configurável pela operadora. Esses itens ficam para v1.2.0 — Autonomia Operacional.

---

## v1.1.2 — Histórico e Consolidação dos Relatórios
**Lançamento:** 28/08/2026
**Status:** Concluída.

### Problema que resolve
O comparativo de 12 meses do PDF só existia, na prática, para os poucos meses fechados pela própria ferramenta desde o lançamento — o histórico anterior ao Lyon Reports nunca tinha sido restaurado nesse nível de detalhe, e por isso o relatório mostrava "histórico insuficiente" mesmo quando a unidade tinha anos de dados reais na planilha original. Separadamente, o comparativo também faltava um mês mesmo quando havia histórico suficiente, sempre que o PDF era gerado antes da aprovação. O Pátio não tinha histórico visível na tela, e a memória de cálculo de Outros Serviços escondia duas incidências (repasse e rateio) num único número.

### Valor entregue
O comparativo mensal do PDF passa a mostrar até 12 competências reais para praticamente todas as unidades, incluindo a competência sendo fechada no momento — não apenas o que foi fechado pela ferramenta desde agosto/2026. O Pátio ganha histórico operacional independente por contratante, como qualquer outra unidade. A memória de Outros Serviços fica auditável, com cada etapa do cálculo visível — na tela e no PDF, de forma consistente.

### O que foi entregue

**Bootstrap do histórico mensal legado**  
Aproximadamente 5 anos de dados mensais (faturamento, resultado, repasse), extraídos da planilha histórica original e restaurados via migrations — nunca por uma funcionalidade de importação exposta ao usuário. Cobre praticamente todas as unidades ativas, com exceção de Medcenter e Viva Open Mall (a planilha original não tem dados mensais para elas depois de dez/2025).

**Histórico mensal de até 12 meses nos PDFs**  
Consequência direta do bootstrap: o comparativo mensal do relatório passa a exibir a janela completa sempre que houver histórico suficiente, sem precisar esperar meses de uso real da ferramenta para se preencher.

**Correção do comparativo para a competência atual**  
O comparativo agora inclui a competência sendo processada mesmo antes da aprovação (quando o lançamento ainda não foi salvo no banco) — sem nunca substituir um valor já aprovado e salvo.

**Histórico operacional do Pátio REAL e MAIOJAMA**  
A tela de unidade do Pátio passa a mostrar "Competências anteriores" de forma independente para cada contratante, como qualquer outra unidade — antes essa seção nem aparecia.

**Ordem do histórico do mês mais recente para o mais antigo**  
Tanto na tela quanto no CSV exportado, a competência mais recente passa a ser a primeira coluna.

**Correção do histórico anual do W-Tower Caxias**  
A importação original usava a coluna de IPTU em vez da coluna de repasse real — o valor de aluguel do histórico anual estava incorreto desde o primeiro seed. Corrigido via migration dedicada, sem misturar com o bootstrap mensal.

**Backfill de maio/2026**  
Corrigida uma suposição do processo de bootstrap que presumia, incorretamente, que toda unidade já tinha maio/2026 gerado pela própria ferramenta. Uma migration separada preenche apenas as unidades que realmente ficaram sem essa competência, sem tocar em nenhum lançamento real já existente.

**Refinamentos da memória de cálculo do Pátio**  
Layout de REAL e MAIOJAMA corrigido para largura total, e a memória de Outros Serviços passa a mostrar cada etapa (Resultado → Repasse 50% → Rateio por contratante com o valor final), igual na tela e no PDF.

### Fora do escopo desta versão
Qualquer alteração de regra de cálculo, rateio ou aprovação além das correções já homologadas nesta versão e na v1.1.1.

---

## v1.2.0 — Autonomia Operacional

### Problema que resolve
Hoje, qualquer alteração contratual — um percentual de repasse renegociado, uma nova unidade, uma rubrica de custo nova — exige que a equipe de desenvolvimento edite YAML ou banco diretamente. A v1.1.1 já corrigiu dois casos reais desse tipo (In 1183, Medcenter) através de migrations pontuais; isso resolveu o sintoma, mas não o problema estrutural: a operadora depende de desenvolvimento para qualquer ajuste operacional de rotina, mesmo os mais simples.

### Valor entregue
A equipe da Valandro — e, no médio prazo, a própria gestão da Lyon Park — passa a cadastrar unidades novas, ativar/desativar unidades, e ajustar parâmetros contratuais (percentuais, alíquotas, ponto de equilíbrio, rubricas de custo) diretamente pela interface, com histórico completo de quem alterou o quê e quando. Uma alteração contratual deixa de exigir uma migration ou um deploy.

### Principais funcionalidades

**Tela de cadastro de unidades**  
Cadastro de novas unidades e ativação/desativação das existentes, sem editar `data/units.yaml` diretamente. Seleção do modelo de cálculo a partir dos tipos já existentes (`COM_ALIQUOTA`, `COM_ALIQUOTA_CUMUL`, `COM_FAIXAS` etc.) — criar um novo *tipo* de calculadora continua sendo trabalho de desenvolvimento, fora do escopo desta funcionalidade.

**Tela de parâmetros por unidade**  
Lista todos os parâmetros vigentes de uma unidade com o componente de edição adequado ao tipo — construída sobre os metadados `tipo_dado` e `descricao` já armazenados em `parametros_vigentes` desde a v1.0.0, sem mapeamento adicional de código.

**Vigência de parâmetros por competência**  
Toda alteração feita pela tela abre uma nova vigência a partir da competência escolhida, preservando o histórico anterior — o mesmo mecanismo que hoje só é acionado manualmente via migration (como foi feito para o Medcenter na v1.1.1) passa a estar disponível para qualquer parâmetro, sem exigir intervenção de desenvolvimento.

**Alteração de percentuais de repasse, alíquotas e ponto de equilíbrio**  
Os três ajustes contratuais mais recorrentes passam a ser rotina operacional, não mais exceção tratada por migration pontual.

**Rubricas de custo parametrizáveis**  
Inclusão e manutenção de novos custos mensais ou variáveis por unidade pela própria tela. **O campo de despesa solicitado para a Fiergs durante a homologação (v1.1.1) fica reservado para esta capacidade** — não deve virar uma nova exceção hardcoded no código; deve ser o primeiro caso real de uso desta tela.

**Histórico e auditoria das alterações de parâmetros**  
Para cada parâmetro, visualização de quais valores foram usados, em qual período, e quem alterou — reaproveitando a trilha de auditoria que a tabela `parametros_vigentes` já mantém desde a v1.0.0.

### Por que esta é a próxima versão
Depois de duas versões de correções pontuais de homologação (v1.1.1) e de restauração de histórico (v1.1.2), o padrão que mais se repete é a dependência de desenvolvimento para mudanças que são, na essência, operacionais — não técnicas. Resolver isso antes de investir em automações (v1.3.0) ou em arquitetura (v2.0.0) segue a ordem de prioridade deste roadmap: operação real, depois autonomia da operadora, depois automação, depois evolução arquitetural.

---

## Marco operacional — Fechamento de agosto/2026

> **Fechamento completo da competência agosto/2026 utilizando exclusivamente a ferramenta** — importação, cálculo, revisão, aprovação, geração dos PDFs e histórico, do início ao fim, sem etapa manual paralela.

Este marco não é uma versão — é a validação operacional definitiva do fluxo completo entregue entre a v1.0.0 e a v1.1.2. Enquanto ele não acontece, qualquer automação do fluxo de entrada (v1.3.0) seria prematura: automatizar uma etapa que ainda não foi validada manualmente de ponta a ponta esconde problemas em vez de eliminá-los. Por isso a v1.3.0 — Automação de Entradas e Fechamento é sequenciada explicitamente depois deste marco, não antes.

---

## v1.3.0 — Automação de Entradas e Fechamento

> **Pré-requisito:** só entra em desenvolvimento depois do marco operacional de agosto/2026 (fechamento completo de uma competência real, ponta a ponta, só com a ferramenta).

### Problema que resolve
Mesmo com o sistema funcionando bem e a operadora com autonomia sobre os parâmetros (v1.2.0), ainda existem etapas manuais no início de cada fechamento: alguém digita o faturamento de cada unidade a partir de uma planilha ou sistema externo, e depois cada PDF aprovado precisa ser entregue manualmente ao contratante correspondente. São tarefas repetitivas, previsíveis e sujeitas a erro de digitação — exatamente o tipo de trabalho que deve ser eliminado primeiro, antes de qualquer investimento em arquitetura.

### Valor entregue
A operadora deixa de digitar faturamento manualmente para as unidades cuja fonte de dados permite integração direta. O fechamento chega mais próximo de pronto, com o trabalho humano concentrado em revisar e aprovar — não em transcrever números.

### Principais funcionalidades, em ordem de prioridade

**Integração com a API Aucon para faturamento**  
Prioridade máxima desta versão: eliminar a digitação manual de faturamento nas unidades cuja fonte é o sistema Aucon, substituindo a importação de planilha por leitura direta via API.

**Eliminação da digitação manual de faturamento**  
Extensão do mesmo princípio às demais unidades, na medida em que cada fonte de dados permitir — não depende de uma única integração para começar a entregar valor.

**Automação das demais entradas, quando possível**  
Eventos, mídias e demais planilhas hoje importadas manualmente entram no mesmo princípio, avaliadas caso a caso conforme a fonte real de dados disponível.

**Geração automática de relatórios**  
Ao fechar a competência com as entradas já automatizadas, os PDFs de todas as unidades são gerados automaticamente com os parâmetros vigentes — a operadora recebe o fechamento pré-calculado.

**Notificações e entregas automáticas**  
Ao aprovar um relatório, o PDF é enviado automaticamente ao contratante correspondente. Elimina a etapa manual de download e envio.

### Por que antes de Workflow, Analytics e da migração Supabase
Estas funcionalidades eliminam trabalho manual repetitivo da operadora todo mês — valor direto e imediato. Workflow e Analytics agregam rastreabilidade e visibilidade gerencial, mas não eliminam trabalho manual existente. A migração Supabase entrega valor à plataforma Valandro, não à operadora diretamente. A ordem de prioridade deste roadmap — operação real, autonomia, automação, arquitetura — coloca esta versão à frente das três.

### Nota técnica
A integração com a API Aucon e as demais automações podem exigir recursos adicionais no Render (cron jobs, workers em background). A escolha técnica de cada automação é feita no momento da implementação, avaliando a fonte real dos dados de cada unidade.

---

## v1.4.0 — Workflow

### Problema que resolve
O workflow de aprovação atual é funcional mas pouco rastreável. Quando um relatório é reaberto não fica registrado o motivo. Quando um resultado muda após uma reabertura não é fácil comparar o que mudou. Isso gera insegurança — especialmente quando o contratante questiona um valor.

### Valor entregue
Cada decisão tomada no processo de fechamento passa a ter um registro rastreável: quem aprovou, quando, com quais parâmetros, e por que reabriu.

### Principais funcionalidades

**Motivo obrigatório ao reabrir**  
Hoje a reabertura é imediata. A partir desta versão, o operador registra o motivo antes de reabrir um relatório aprovado. O motivo é salvo no histórico e exibido na linha do tempo da unidade.

**Comparativo de versões ao recalcular**  
Ao recalcular após reabertura, o sistema exibe as diferenças numéricas entre a versão aprovada e o novo cálculo antes de aprovar novamente. A operadora decide com visibilidade, não com fé.

**Registro de aprovações com timestamp e usuário**  
Cada aprovação passa a registrar data, hora e responsável no banco. Base técnica para a trilha de auditoria completa que vem em v2.1.0.

### Já parcialmente entregue
A memória de cálculo no PDF — que originalmente fazia parte do escopo desta versão — já foi entregue nas versões v1.1.1 e v1.1.2: o relatório mostra faturamento, ponto de equilíbrio, custos, alíquotas, resultado e repasse em etapas explícitas, incluindo casos antes combinados numa única linha (In 1183, Outros Serviços do Pátio). O que resta aqui é o rastreamento do *processo* de aprovação, não a memória do cálculo em si.

### Por que está aqui
Esta versão organiza a rastreabilidade do processo de aprovação — um ganho de confiança operacional importante, mas que pressupõe a autonomia de parametrização (v1.2.0) e a automação de entradas (v1.3.0) já entregues.

---

## v1.5.0 — Analytics

### Problema que resolve
Hoje o sistema processa o fechamento, mas não responde perguntas sobre a operação. Qual unidade demora mais para fechar? Quantos dias em média vão da importação da planilha até a aprovação do último relatório? Quais unidades foram reabertas mais vezes? Quais têm saldo acumulado crescendo? Essas informações estão no banco, mas ninguém as vê.

### Valor entregue
O sistema passa a ser também uma ferramenta de gestão da operação — não apenas de execução. A Valandro e a gestão da Lyon Park passam a ter visibilidade sobre o processo de fechamento como um todo, não unidade por unidade. Decisões sobre onde focar atenção deixam de depender de percepção e passam a ter dados.

### Principais funcionalidades

**Painel de status da competência**  
Visão consolidada de todas as 23 unidades em uma competência: quantas estão aprovadas, em andamento, pendentes. Progresso geral do fechamento mensal em tempo real.

**Indicadores de tempo de fechamento**  
Por unidade e por competência: tempo médio entre importação e aprovação, número de recalculações antes da aprovação, número de reabertura por unidade. Identifica gargalos e unidades que sistematicamente demandam mais esforço.

**Evolução de saldos acumulados**  
Gráfico de tendência do prejuízo acumulado para as unidades com saldo negativo (hoje: Dom Pedro, MW Tristeza, Viva Trindade). Permite antecipar quando um saldo vai zerar ou quando vai se agravar.

**Histórico operacional consolidado**  
Série histórica de faturamento, resultado e aluguel de todas as unidades em uma única visão. Substitui a consulta manual ao banco para análises gerenciais.

**Gráfico de evolução anual no PDF**  
O relatório de cada unidade passa a incluir representação visual da evolução anual de faturamento e aluguel, além dos valores tabulares já existentes.

### Por que está aqui
Os dados para esta versão já existem no banco desde v1.0.0. O custo técnico é baixo. O valor gerencial é alto — e aumenta com o tempo, porque cada mês fechado enriquece as séries históricas. Esta versão transforma o sistema de uma ferramenta operacional em uma ferramenta de gestão.

---

## v2.0.0 — Migração para Supabase
**Esta é a única versão MAJOR prevista.**

### Problema que resolve
A v1.0.0 foi lançada com SQLite e Render Persistent Disk para cumprir o prazo de 15/08/2026 — uma decisão deliberada e correta. Com a operação estabilizada, a operadora com autonomia sobre parâmetros e as entradas manuais mais repetitivas automatizadas, é o momento de adequar a infraestrutura ao padrão Valandro: banco gerenciado, storage gerenciado e autenticação centralizada.

### Valor entregue
A operação passa a rodar sobre infraestrutura mais robusta, escalável e alinhada com o restante do portfólio Valandro. O backup do banco passa a ser gerenciado pelo Supabase. O armazenamento de PDFs e planilhas passa a ter redundância e acesso controlado. A autenticação passa a suportar múltiplos usuários com perfis distintos.

### Por que é MAJOR
Troca simultânea de três contratos de infraestrutura — banco, storage e autenticação — cada um exigindo migração de dados e validação em produção antes do corte. O comportamento do produto para a operadora não muda, mas o risco operacional da migração justifica o incremento de versão maior.

### Entregas

**Fase alpha — PostgreSQL**  
Projeto Supabase dedicado ao Lyon Park. Migrations Alembic para criar o schema. Migração do banco SQLite de produção para PostgreSQL com validação de integridade antes do corte. Nenhuma mudança visível para a operadora.

**Fase beta — Storage**  
PDFs e planilhas importadas migram para Supabase Storage. `run_manager.py` e parsers adaptados. A estrutura de diretórios por competência é preservada, apenas o destino muda.

**Release — Supabase Auth**  
Login via Supabase Auth substitui `streamlit-authenticator`. Suporte a múltiplos usuários. Campo `alterado_por` no banco passa a usar o `user_id` real.

**Pós-release:**  
Remoção do Render Persistent Disk, atualização do `render.yaml`, renomeação do repositório para `valandro-lyonpark`.

> **Garantia operacional:** o banco SQLite de produção é lido e migrado com os dados reais antes de qualquer corte. Existe procedimento documentado de rollback para SQLite em caso de falha. A operação de fechamento mensal não é interrompida durante nenhuma fase da migração.

---

## v2.1.0 — Perfis e Auditoria

### Problema que resolve
Hoje existe um único usuário com acesso total ao sistema. Com a operação crescendo e potencialmente envolvendo mais pessoas — quem calcula, quem revisa, quem aprova podem ser pessoas diferentes — é necessário controlar o que cada perfil pode fazer e registrar quem fez o quê.

### Valor entregue
A gestão da Lyon Park passa a ter controle granular de acesso: a operadora calcula e gera PDFs, o revisor aprova ou reabre, o administrador ajusta parâmetros. Cada ação fica vinculada a uma pessoa real — não apenas ao sistema.

### Principais funcionalidades

**Perfis de acesso:**
- `operador` — importa planilha, edita parâmetros, calcula, gera PDF
- `revisor` — aprova ou reabre relatórios, sem acesso à edição de parâmetros
- `admin` — acesso completo, incluindo parametrização e auditoria

**Controle por unidade:** possibilidade de restringir quais unidades cada usuário pode visualizar ou operar.

**Trilha de auditoria completa:** cada ação vinculada ao `user_id` real do Supabase. O campo `alterado_por` deixa de receber strings fixas como `"aprovacao"` e passa a registrar o identificador do usuário responsável.

---

## v2.2.0 — API REST

### Problema que resolve
Hoje toda interação com o sistema é via interface gráfica. Isso impossibilita automações externas, integrações com outros sistemas do portfólio Valandro e uso programático das funcionalidades de cálculo.

### Valor entregue
O motor de cálculo do Lyon Park passa a ser acessível programaticamente. Outros sistemas Valandro podem solicitar cálculos, consultar status e baixar PDFs sem intervenção humana. É o pré-requisito técnico para o Lyon Park participar de um futuro Centro de Comando Valandro.

### Principais endpoints
- `POST /competencias/{mes_ref}/calcular/{uid}` — dispara cálculo para uma unidade
- `GET /competencias/{mes_ref}/status` — retorna status de todas as unidades
- `POST /competencias/{mes_ref}/aprovar/{uid}` — aprova um relatório
- `GET /relatorios/{mes_ref}/{uid}/pdf` — download do PDF

### Por que separada das Integrações
A API é infraestrutura — expõe capacidades. As integrações são produto — consomem essas capacidades para resolver problemas específicos. Separá-las permite que a API seja validada e documentada antes de construir integrações sobre ela.

---

## v2.3.0 — Integrações

### Problema que resolve
Com a API disponível, é possível conectar o Lyon Park a sistemas externos: enviar dados para plataformas de gestão financeira, receber faturamentos de fontes externas via API, integrar com ferramentas da Valandro. Esta versão constrói as integrações específicas que fazem sentido no momento.

### Valor entregue
O Lyon Park deixa de ser um sistema isolado e passa a ser parte do ecossistema de ferramentas da Valandro. Os dados de fechamento ficam disponíveis para consumo por outros sistemas sem exportação manual.

### Integrações candidatas
O escopo exato desta versão é definido com base nas necessidades reais identificadas durante a operação das versões anteriores. Candidatos atuais:
- Integração com o Gerador de DRE Valandro (compartilhamento de resultados de fechamento)
- Webhook para notificações externas (Slack, email) ao aprovar um relatório
- Leitura automática de faturamentos via API de sistema externo (se disponível, além da integração Aucon já entregue em v1.3.0)

---

## v3.0.0 — Testes e CI/CD

### Problema que resolve
As calculadoras são o núcleo do sistema — qualquer erro de cálculo tem impacto financeiro direto e legal para a Lyon Park e seus contratantes. Hoje uma alteração em uma calculadora é validada manualmente antes de ir para produção. Isso funciona enquanto a equipe de desenvolvimento conhece profundamente cada contrato, mas não escala conforme o portfólio cresce.

### Valor entregue
Qualquer alteração em uma calculadora é verificada automaticamente contra as Memórias de Cálculo aprovadas pelos contratantes antes de ir para produção. Um erro de cálculo que passaria despercebido manualmente é capturado no CI. A equipe de desenvolvimento pode evoluir o sistema com confiança.

### Principais entregas

**Testes unitários por calculadora**  
Fixtures baseadas nas Memórias de Cálculo aprovadas: entradas conhecidas, saídas verificadas numericamente. Cobre os 9 tipos de calculadora e seus casos especiais (faixas progressivas, saldo acumulado, correção IPCA, pátio com splits).

**Testes de integração do workflow**  
Fluxo completo automatizado: importar planilha → calcular → aprovar → verificar banco. Rodado em banco de teste isolado.

**Pipeline CI/CD no GitHub Actions**  
`push` → testes. `merge na main` → testes + deploy automático no Render. Branch `main` protegida contra merge sem CI verde.

**Estrutura de repositório conforme padrão Valandro**  
Repositório renomeado para `valandro-lyonpark`. Branches de feature (`feature/*`) e release (`release/*`). Documentação de contribuição.

### Nota sobre antecipação de testes
As Memórias de Cálculo aprovadas pelos contratantes já existem. É possível — e desejável — criar testes unitários das calculadoras ainda durante a linha 1.x, à medida que bugs sejam encontrados nos primeiros fechamentos reais (como já aconteceu na v1.1.1, com o In 1183, validado diretamente contra a Memória de Cálculo e a planilha histórica). Esses testes não esperam a v3.0.0 para existir: eles são criados progressivamente e incorporados à suíte completa nesta versão. O que a v3.0.0 formaliza é a cobertura ampla, o CI/CD e a proteção automática da branch principal.

---

## Backlog sem versão definida

Itens identificados, com valor claro, mas sem priorização formal ainda. Serão incorporados ao roadmap à medida que a operação real revele a ordem correta.

| Item | Problema que resolve | Impacto estimado |
|---|---|---|
| Versão compacta do PDF para envio por email | PDFs atuais são pesados para envio direto | Médio |
| Suporte a IPCA automático (MW Tristeza) | Hoje a correção anual exige intervenção manual | Médio |
| Novos contratos com calculadoras existentes | Adicionar unidade hoje exige apenas YAML — formalizar o processo | Alto / custo zero |
| Novos tipos de calculadora | Contratos com modelos fora dos 9 existentes | Alto / custo de desenvolvimento |
| Backup automático antes de cada competência | Proteção contra corrupção de dados no início do fechamento | Segurança |
| Exportação consolidada multi-unidade | Visão agregada do fechamento para relatório gerencial | Médio |

### Refinamento visual (backlog, sem prioridade maior que v1.2.0)

Ajustes visuais pontuais identificados em uso real ou em reunião de validação — não representam mudança arquitetural nem de regra de cálculo, por isso não ocupam uma versão própria.

| Item | Problema que resolve | Impacto estimado |
|---|---|---|
| Revisão final do layout dos PDFs após feedback do proprietário da Lyon Park | Ajuste de leitura/apresentação do relatório entregue ao contratante | Baixo |
| Possível remoção ou revisão das colunas de variação percentual do comparativo | Feedback direto sobre a leitura do bloco de comparativo mensal | Baixo |
| Outros ajustes visuais identificados na reunião de validação | A consolidar conforme a reunião definir escopo | A definir |

---

## Princípios que guiam este roadmap

**1. Usuário antes de arquitetura.**  
Funcionalidades que entregam valor direto à operadora têm prioridade sobre evoluções de plataforma. É por isso que Autonomia Operacional, Automação de Entradas e Analytics (v1.2, v1.3 e v1.5) vêm antes da migração Supabase (v2.0).

**2. A operação de fechamento mensal nunca para.**  
Nenhuma versão — incluindo a MAJOR — pode deixar as 23 unidades sem fechamento. Migrações acontecem com rollback documentado e validação prévia em produção.

**3. MINOR não quebra nada.**  
A operadora não precisa saber que houve uma nova versão para continuar fechando normalmente. Funcionalidades novas são aditivas.

**4. Calculadoras são intocáveis sem evidência.**  
Qualquer alteração em uma calculadora é validada manualmente contra a Memória de Cálculo aprovada antes de ir para produção — como foi feito para o In 1183 na v1.1.1. A partir da v3.0.0, essa validação é automatizada.

**5. O roadmap serve ao negócio, não o contrário.**  
Seguindo o princípio 1.2 do padrão Valandro: se um prazo real ou uma necessidade operacional entrar em conflito com a sequência prevista, o roadmap é ajustado — não a operação.

**6. Automação só depois de validação manual completa.**  
Nenhum fluxo é automatizado antes de ter rodado de ponta a ponta, manualmente, pela ferramenta, pelo menos uma vez em produção real (ver [Marco operacional — Fechamento de agosto/2026](#marco-operacional--fechamento-de-agosto2026)). Automatizar um processo ainda não validado esconde problemas em vez de eliminá-los.

---

*Última atualização: 28/08/2026*
