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

## 4. Implementação atual (v1.0)

Decisões de execução — podem mudar sem alterar os princípios das seções 1 a 3.

- **Tipografia:** Manrope (display/itálico de leitura), IBM Plex Sans (corpo), IBM Plex Mono (dado tabular).
- **Voz do dado:** `var(--font-mono)`, numérico tabular, `var(--text-primary)`.
- **Voz da leitura:** `var(--font-display)` itálico, peso 600, `var(--red-500)` — reservada à frase que interpreta um dado; nunca rótulo decorativo repetido.
- **Cor:** paleta e tokens do design system vigente (azul institucional, navy-900, cinzas, red-500/green-500/amber-500 restritos a status). Máximo 1–2 cores de fundo por peça.
- **Espaçamento:** escala de 4px do design system vigente.

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
