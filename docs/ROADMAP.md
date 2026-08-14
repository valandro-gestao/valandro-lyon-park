# ROADMAP — Lyon Park Fechamento Mensal

**Produto:** Gerador de Relatórios Lyon Park  
**Versão atual:** 1.0.0  
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

---

## Linha do tempo

```
ago/2026   v1.0.0  Produção
           v1.1.0  Operação Assistida
           v1.2.0  Workflow
           v1.3.0  Parametrização
           v1.4.0  Analytics
           v1.5.0  Automações Operacionais
2027+      v2.0.0  Migração Supabase (MAJOR)
           v2.1.0  Perfis e Auditoria
           v2.2.0  API REST
           v2.3.0  Integrações
           v3.0.0  Testes e CI/CD
```

---

## v1.0.0 — Produção
**Lançamento:** 15/08/2026

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

## v1.1.0 — Operação Assistida

### Problema que resolve
As primeiras competências reais em produção são as mais arriscadas. A operadora aprende o sistema, o sistema encontra seus primeiros edge cases reais, e a Valandro precisa conseguir diagnosticar problemas rapidamente. Hoje o sistema faz o trabalho, mas não auxilia a operadora a ter confiança de que está fazendo certo.

### Valor entregue
A operadora consegue detectar erros antes de aprovar — não depois. Um número inesperado é sinalizado antes de virar PDF. A Valandro consegue diagnosticar o que aconteceu em produção sem precisar acessar o servidor manualmente.

### Principais funcionalidades

**Comparativo automático com o mês anterior**  
Antes de aprovar, a operadora vê lado a lado o resultado atual e o do mês anterior para a mesma unidade. Variações grandes ficam visíveis antes de qualquer aprovação.

**Alerta de parâmetro fora do padrão**  
Se um valor editável difere significativamente do último aprovado (ex: ponto de equilíbrio alterado em mais de 20%), o sistema exibe um aviso antes de calcular. Evita aprovações por erro de digitação.

**Variação percentual no bloco de histórico do PDF**  
O bloco de comparativo mensal do relatório passa a exibir a variação `%` mês a mês. Hoje o bloco existe, mas não indica se o resultado melhorou ou piorou.

**Log estruturado das ações operacionais**  
Importação de planilha, cálculo, aprovação, reabertura e geração de PDF passam a gerar entradas de log visíveis no painel do Render. Diagnóstico remoto de problemas passa a ser possível sem acesso ao servidor.

**Correções pós-launch**  
Bugs e ajustes de UX identificados nos primeiros fechamentos reais. Esta é a única versão que tem espaço aberto para correções não previstas — porque não é possível saber o que vai aparecer antes de a operadora usar o sistema de verdade.

### Por que está aqui
A primeira versão é funcionalmente completa, mas não é ainda confortável. Esta versão existe para fazer a operação ficar confortável antes de evoluir o produto. Seguindo o princípio 1.2 do padrão Valandro: a arquitetura — e o roadmap — servem ao negócio, não o contrário.

---

## v1.2.0 — Workflow

### Problema que resolve
O workflow de aprovação atual é funcional mas pouco rastreável. Quando um relatório é reaberto não fica registrado o motivo. Quando um resultado muda após uma reabertura não é fácil comparar o que mudou. Isso gera insegurança — especialmente quando o contratante questiona um valor.

### Valor entregue
Cada decisão tomada no processo de fechamento passa a ter um registro rastreável: quem aprovou, quando, com quais parâmetros, e por que reabriu. O PDF passa a ser auto-explicativo — o contratante recebe não apenas o resultado, mas a memória do cálculo que o produziu.

### Principais funcionalidades

**Motivo obrigatório ao reabrir**  
Hoje a reabertura é imediata. A partir desta versão, o operador registra o motivo antes de reabrir um relatório aprovado. O motivo é salvo no histórico e exibido na linha do tempo da unidade.

**Comparativo de versões ao recalcular**  
Ao recalcular após reabertura, o sistema exibe as diferenças numéricas entre a versão aprovada e o novo cálculo antes de aprovar novamente. A operadora decide com visibilidade, não com fé.

**Memória de cálculo no PDF**  
O relatório passa a incluir, em seção dedicada, todos os parâmetros utilizados no cálculo: faturamento, ponto de equilíbrio, custos, alíquotas, resultado, aluguel. Se o contratante questionar um número, a memória está no documento.

**Registro de aprovações com timestamp e usuário**  
Cada aprovação passa a registrar data, hora e responsável no banco. Base técnica para a trilha de auditoria completa que vem em versões futuras.

### Por que está antes de Parametrização
O workflow é usado todo mês pela operadora. A parametrização é usada ocasionalmente pela equipe da Valandro. O impacto do workflow na rotina operacional é muito maior — e ele resolve o problema de rastreabilidade que já aparece no primeiro mês de uso real.

---

## v1.3.0 — Parametrização

### Problema que resolve
Hoje, qualquer ajuste de parâmetro operacional (ponto de equilíbrio, percentual de aluguel, custos mensais) exige que a equipe da Valandro acesse o banco de dados diretamente ou edite o YAML. Isso cria dependência técnica para operações que deveriam ser rotineiras — especialmente quando um contrato é renegociado.

### Valor entregue
A equipe da Valandro passa a ajustar parâmetros operacionais diretamente pela UI, sem acesso ao banco ou ao código. Alterações ficam registradas com data e responsável. O histórico completo de cada parâmetro fica acessível — é possível saber exatamente qual era o ponto de equilíbrio da A. Schneider em março de 2025.

### Principais funcionalidades

**Tela de parametrização por unidade**  
Lista todos os parâmetros vigentes de uma unidade com o componente de edição adequado ao tipo: campo monetário para `ponto_equilibrio`, percentual para `aliquota_imposto`, tabela editável para `faixas`. Construída sobre os metadados `tipo_dado` e `descricao` já armazenados no banco — sem nenhum mapeamento adicional de código.

**Histórico de vigências por parâmetro**  
Para cada parâmetro, visualização da linha do tempo: quais valores foram usados, em qual período, e quem alterou. Permite auditar qualquer divergência com o contratante.

**Exportação do histórico de parâmetros**  
Download CSV/Excel com o histórico completo de parâmetros de uma unidade. Útil para conferência contratual e auditoria externa.

### Por que está aqui
Esta versão usa infraestrutura que já existe — o banco armazena `tipo_dado` e `descricao` desde v1.0.0. O custo de implementação é baixo e a dependência atual da equipe de desenvolvimento para ajustes operacionais é um gargalo real. Mas o impacto na rotina mensal da operadora é menor do que o workflow, por isso vem depois.

---

## v1.4.0 — Analytics

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

## v1.5.0 — Automações Operacionais

### Problema que resolve
Mesmo com o sistema funcionando bem, ainda existem etapas manuais no início e no fim de cada fechamento: alguém precisa baixar a planilha de faturamento, importar manualmente, e depois enviar cada PDF ao contratante correspondente. São tarefas repetitivas, previsíveis e sem valor agregado — exatamente o tipo de trabalho que deve ser eliminado.

### Valor entregue
A operadora passa a receber o fechamento pronto — ou quase pronto — sem precisar executar etapas mecânicas. A planilha é capturada automaticamente. Os PDFs são enviados sem intervenção manual. O trabalho humano fica concentrado onde realmente importa: revisar, ajustar parâmetros quando necessário e aprovar.

### Principais funcionalidades

**Captura automática da planilha de faturamento**  
Integração com a fonte de dados onde a planilha de faturamento é disponibilizada mensalmente (email, Google Drive, SharePoint ou equivalente). O sistema detecta o arquivo, valida o formato e importa sem intervenção manual.

**Geração automática dos PDFs ao fechar o mês**  
Ao início de cada competência, o sistema gera automaticamente os PDFs de todas as unidades com os parâmetros vigentes. A operadora recebe o fechamento pré-calculado e faz apenas as correções necessárias antes de aprovar.

**Envio automático dos relatórios aprovados**  
Ao aprovar um relatório, o PDF é enviado automaticamente ao contratante correspondente por email. Elimina a etapa manual de download, composição de email e envio.

**Agendamento mensal do fechamento**  
Cron job que dispara automaticamente o início do processo de fechamento na data configurada de cada competência. A operadora recebe uma notificação de que o fechamento está disponível para revisão.

### Por que está antes da migração Supabase
Estas funcionalidades entregam valor direto e imediato à operadora — reduzem horas de trabalho manual todo mês. A migração para Supabase entrega valor à plataforma Valandro, não à operadora diretamente. Seguindo a ordem de prioridade correta: primeiro o usuário, depois a arquitetura.

### Nota técnica
Algumas automações desta versão podem exigir recursos adicionais no Render (cron jobs, workers em background) ou integrações externas (Gmail API, Google Drive API). A escolha técnica de cada automação é feita no momento da implementação, avaliando a fonte real dos dados da Lyon Park.

---

## v2.0.0 — Migração para Supabase
**Esta é a única versão MAJOR prevista.**

### Problema que resolve
A v1.0.0 foi lançada com SQLite e Render Persistent Disk para cumprir o prazo de 15/08/2026 — uma decisão deliberada e correta. Com a operação estabilizada e as principais funcionalidades de produto entregues, é o momento de adequar a infraestrutura ao padrão Valandro: banco gerenciado, storage gerenciado e autenticação centralizada.

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
- Leitura automática de faturamentos via API de sistema externo (se disponível)

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
As Memórias de Cálculo aprovadas pelos contratantes já existem. É possível — e desejável — criar testes unitários das calculadoras ainda durante a linha 1.x, à medida que bugs sejam encontrados nos primeiros fechamentos reais. Esses testes não esperam a v3.0.0 para existir: eles são criados progressivamente e incorporados à suíte completa nesta versão. O que a v3.0.0 formaliza é a cobertura ampla, o CI/CD e a proteção automática da branch principal.

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

---

## Princípios que guiam este roadmap

**1. Usuário antes de arquitetura.**  
Funcionalidades que entregam valor direto à operadora têm prioridade sobre evoluções de plataforma. É por isso que Analytics e Automações (v1.4 e v1.5) vêm antes da migração Supabase (v2.0).

**2. A operação de fechamento mensal nunca para.**  
Nenhuma versão — incluindo a MAJOR — pode deixar as 23 unidades sem fechamento. Migrações acontecem com rollback documentado e validação prévia em produção.

**3. MINOR não quebra nada.**  
A operadora não precisa saber que houve uma nova versão para continuar fechando normalmente. Funcionalidades novas são aditivas.

**4. Calculadoras são intocáveis sem evidência.**  
Qualquer alteração em uma calculadora é validada manualmente contra a Memória de Cálculo aprovada antes de ir para produção. A partir da v3.0.0, essa validação é automatizada.

**5. O roadmap serve ao negócio, não o contrário.**  
Seguindo o princípio 1.2 do padrão Valandro: se um prazo real ou uma necessidade operacional entrar em conflito com a sequência prevista, o roadmap é ajustado — não a operação.

---

*Última atualização: 12/08/2026*
