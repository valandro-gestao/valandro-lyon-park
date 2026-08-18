# Design Language — Valandro Gestão
### v1.0 — documento de referência oficial

> A linguagem visual da Valandro existe para deixar visível, em qualquer peça, que uma decisão boa nasce de evidência lida junto com o cliente — nunca entregue a ele já fechada.

Este documento consolida decisões já aprovadas. Não é espaço de exploração: designers, desenvolvedores, agentes de IA e futuros colaboradores devem tratá-lo como referência estável, revisada apenas pelo processo descrito na seção 7.

---

## 1. Princípios permanentes

Regras que devem seguir válidas mesmo que fonte, cor, tecnologia ou formato mudem no futuro.

- **Raciocínio antes de decoração.** Nenhum elemento visual existe sem justificar sua função no raciocínio da peça. Se um elemento só "fica bonito", ele não pertence ao sistema.
- **Método da Mesa.** Toda peça é construída sobre um ciclo de quatro passos, sempre nesta ordem: **Evidência** (o fato, sem interpretação) → **Leitura** (o que o fato revela) → **Recomendação** (até onde vai a responsabilidade da Valandro) → **Decisão** (pertence ao empresário; o que ele decide alimenta a evidência do ciclo seguinte). Nenhuma leitura existe sem evidência que a sustente; nenhuma recomendação existe sem leitura que a justifique. A disciplina é obrigatória; a exposição é flexível — na maior parte das peças, o ciclo vive só na estrutura do texto e do layout, nunca rotulado com os nomes dos quatro passos. O nome "Método da Mesa" e seus quatro passos só aparecem explícitos em material institucional e de treinamento — nunca em proposta, relatório, dashboard ou conteúdo voltado ao cliente.
- **Linguagem editorial.** Segunda pessoa, tom de parceria, nunca exclamação, nunca gíria. Todo número vem acompanhado do que significa — nunca aparece isolado. Toda recomendação carrega o motivo dentro da própria frase, nunca como item de checklist solto. Toda conclusão abre a próxima conversa — nunca fecha com uma tagline institucional solta. Todo título afirma algo, como faria um consultor falando; nunca rotula uma seção como faria um produto de software.
- **Duas vozes.** Todo dado (evidência) e toda interpretação (leitura) são visualmente distinguíveis por voz, não por rótulo ou caixa colorida — uma voz para o fato, outra para a leitura sobre ele. A execução atual dessa voz está na seção 4; o princípio sobrevive a qualquer troca de fonte ou cor.

---

## 2. Regras consolidadas

Elementos já validados em projetos reais e considerados parte estável da linguagem.

- **Terminal sempre arredondado** — nenhuma linha do sistema (régua, sublinhado, traço de gráfico) termina em ponta reta.
- **Traço monolinear único** — uma só espessura de linha por peça; hierarquia resolvida por espaço e cor, nunca por variação de peso de linha.
- **Marca de confirmação** — check gestual assimétrico, derivado do símbolo da marca, usado exclusivamente para marcar dado conferido/reconciliado.
- **Grade de base tipográfica única** — toda tabela ou coluna numérica segue alinhamento rígido de linha de base.
- **Convenções contábeis substituem cards.** Subtotal = traço simples; total fechado = traço duplo. Correção de número é mostrada, nunca escondida: valor antigo riscado ao lado do valor corrigido.
- **Cards com sombra/caixa só onde há função real de produto** (ex.: dashboard operacional) — nunca em proposta, relatório ou conteúdo editorial.

## 2.1 Elementos em validação

Ideias já desenhadas e testadas uma vez, mas que ainda não cumpriram o critério de validação da seção 7. Podem ser usadas com atenção, mas não são cobradas como padrão obrigatório.

- **Círculo como único contêiner permitido** (nunca card com canto arredondado — só círculo verdadeiro para marcadores, índices e pontos de status).
- **Proporção curto/longo** (todo par evidência+leitura seguindo a proporção formal do símbolo da marca — marca curta ao lado de linha longa).
- **Envelope de contenção vertical** (nenhum elemento gráfico ultrapassa a altura do conteúdo ao lado dele).

---

## 3. O que a marca deve fazer o cliente sentir

Não é sobre layout. É o teste por trás de qualquer decisão visual futura.

- **Raciocínio, antes de estética.** O cliente deve sentir que alguém pensou nos números dele, não que alguém desenhou uma peça bonita.
- **Parceria, antes de autoridade.** A Valandro mostra o caminho até uma conclusão; não impõe a conclusão como verdade fechada.
- **Rigor, antes de espetáculo.** Nenhuma peça deve impressionar por volume visual — deve convencer por precisão.
- **Continuidade, antes de entrega única.** Cada peça deve parecer parte de um acompanhamento em curso, nunca um documento isolado e definitivo.
- **A decisão continua sendo do cliente.** Nenhuma peça deve terminar como se a Valandro tivesse decidido por ele.

---

## 4. Implementação atual (v1.1)

Decisões de execução — podem mudar sem alterar os princípios das seções 1 a 3.

### 4.1 Tipografia

**Alvo (não implementado ainda):** Manrope (display/itálico de leitura), IBM Plex Sans (corpo), IBM Plex Mono (dado tabular).

**Implementação atual:** stack de sistema (`-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`) para todos os papéis tipográficos.

**Motivo:** carregamento de fontes via CDN externo foi descartado explicitamente — não há dependência de rede além da aplicação em si. A estratégia de auto-hospedagem das fontes para o portfólio Valandro ainda não foi definida. Quando for definida, a troca é feita apenas nos tokens CSS (`--vd-font-display` e `--vd-font-body`) sem alteração de estrutura.

### 4.2 Tokens CSS oficiais (aplicação Streamlit)

Os tokens abaixo são a referência canônica para toda tela do Lyon Park. Qualquer nova tela deve declará-los em `:root` e usá-los via variável — nunca com valores literais.

```css
:root {
  /* Marca e ações primárias */
  --vd-navy:      #1B3A6B;   /* Cor principal — botões primários, foco, seleção */
  --vd-navy-mid:  #2E6DA4;   /* Estado hover de elementos navy */

  /* Texto */
  --vd-ink:       #1F2937;   /* Texto principal */
  --vd-muted:     #6B7280;   /* Labels, texto secundário */
  --vd-faint:     #9CA3AF;   /* Texto terciário, contexto discreto */

  /* Estrutura */
  --vd-border:    #E2E5EA;   /* Bordas de inputs e divisores */

  /* Status operacional */
  --vd-green:     #059669;   /* Aprovado */
  --vd-amber:     #B45309;   /* Em andamento / atenção */
  --vd-red:       #DC2626;   /* Erro / pendente / leitura */
  --vd-red-bg:    #FDECEA;   /* Fundo de alertas de erro */

  /* Tipografia (stack de sistema — ver 4.1) */
  --vd-font-display: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --vd-font-body:    -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
```

### 4.3 Tema Streamlit

O tema claro é fixo — sem alternância dark/light. Configurado em `.streamlit/config.toml`:

```toml
[theme]
base = "light"
primaryColor = "#1B3A6B"           # --vd-navy
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F5F6F8"
textColor = "#1F2937"              # --vd-ink
font = "sans serif"
```

**Motivo:** o Design Language foi desenvolvido para tema claro. Sem configuração fixa, o Streamlit segue a preferência de dark mode do sistema operacional do usuário, quebrando a identidade visual em metade dos ambientes.

### 4.4 Hierarquia de identidade de marca

- **Valandro** é a marca primária em todas as telas — aparece com logo em destaque no Login e discretamente no Dashboard.
- **Lyon Park** aparece como contexto operacional/cliente, nunca como marca principal.
- O sistema **não é white-label**: a autoria Valandro deve ser visível.

**Aplicação no Login:** logo Valandro centralizado, campo de contexto `"Lyon Park · Fechamento mensal"` em tipografia menor e cor faint.

**Aplicação no Dashboard:** logo Valandro pequeno no canto superior esquerdo (`height: 28px`), sem texto de marca — presença discreta mas consistente.

### 4.5 Layout e espaçamento

- **Container principal:** `max-width: 1180px` — otimizado para notebooks de ~14". Evita dispersão em monitores largos sem reduzir informação em telas menores.
- **Sidebar:** removida completamente via CSS (`display: none`). A navegação é feita pelo próprio conteúdo da tela, não por menu lateral.
- **Escala de espaçamento:** 4px como unidade base.

### 4.6 Voz do dado e voz da leitura

- **Voz do dado:** `var(--vd-font-body)`, numérico tabular, `var(--vd-ink)`.
- **Voz da leitura:** `var(--vd-font-display)` itálico, peso 600, `var(--vd-red)` — reservada à frase que interpreta um dado; nunca rótulo decorativo repetido.

---

## 5. O que foi descartado

- Kicker mono-uppercase repetido no topo de cada seção.
- Linha/barra azul decorativa sem função.
- Grid de cards brancos com sombra como padrão default para qualquer bloco de conteúdo.
- Bloco navy com gradiente diagonal como abertura universal repetida sem variação.
- Qualquer estética de livro-razão antigo, papel envelhecido ou nostalgia cartorial — a referência a convenções contábeis deve parecer papel de trabalho contemporâneo, nunca arquivo histórico.
- Interface de produto (abas, dropdowns, botões de ação) em peças que não são software real.

---

## 6. Onde cada regra se aplica

- **Proposta, Relatório, Conteúdo/Carrossel:** linguagem editorial, duas vozes, elementos consolidados (seção 2) e convenções contábeis — sem componentes de interface.
- **Dashboard** (única peça que é produto real): pode usar componentes funcionais de interface onde há função genuína — mas a leitura deve estar sempre ao lado do dado que explica, nunca isolada em badge ou tag decorativa.

---

## 7. Evolução da Design Language

Uma nova regra só entra oficialmente nas seções 1 ou 2 quando, cumulativamente:

- tiver sido aplicada em pelo menos dois projetos reais;
- melhorar comprovadamente a compreensão do cliente;
- funcionar em mais de um tipo de artefato (software, relatório, proposta, conteúdo etc.);
- não depender de uma tecnologia, fonte ou ferramenta específica.

Até cumprir os quatro critérios, uma ideia permanece na seção 2.1 (elementos em validação) ou fora do documento. Este processo existe para impedir que ideias promissoras se tornem regra permanente sem uso real que as sustente.
