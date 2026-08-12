# Banco de Dados — Lyon Park Fechamento

## Conceitos

### `data/seed.db`
Banco SQLite versionado no repositório. Contém os dados históricos necessários para a operação:
- `historico_anual` — séries históricas de anos anteriores (usadas no comparativo 12 meses dos PDFs)
- `saldos_acumulados` — prejuízos acumulados de unidades que iniciam com saldo negativo
- `lancamentos` — fechamentos aprovados do período de homologação
- `parametros_vigentes` — parâmetros operacionais configurados via engine

Esse arquivo **não é aberto pela aplicação**. Ele serve apenas como origem da cópia inicial do banco operacional, descrita abaixo.

### Banco operacional (`DATA_DIR/db.sqlite`)
Banco criado automaticamente na primeira inicialização a partir do `seed.db`. É aqui que todos os dados operacionais são gravados: novos lançamentos, aprovações, re-aberturas, atualizações de saldo e histórico.

O caminho é resolvido dinamicamente via `DATA_DIR`:

| Ambiente | `DATA_DIR` | Caminho do banco |
|---|---|---|
| Produção (Render) | `/mnt/data` | `/mnt/data/db.sqlite` |
| Desenvolvimento local | *(não definido)* | `./data/db.sqlite` |

O banco operacional **nunca é versionado** — está em `.gitignore`.

### `DATA_DIR`
Variável de ambiente que define onde os dados operacionais são armazenados. Configurada no `render.yaml` e injetada pelo Render no processo em produção. Localmente, pode ser omitida (usa `./data`) ou apontada para um diretório temporário para testes de isolamento.

---

## Comportamento por cenário

### Primeiro deploy (banco não existe em `/mnt/data`)

```
init_db() é chamado na autenticação
  └─ seed_db_if_missing()
       ├─ DB_PATH não existe → copia seed.db para /mnt/data/db.sqlite
       └─ Log: "Banco operacional não encontrado. Inicializando a partir do seed."
  └─ Tabelas criadas via CREATE TABLE IF NOT EXISTS (compatível com banco copiado)
```

O banco nasce com todos os dados históricos. Nenhuma ação manual necessária.

### Redeploys subsequentes (banco já existe)

```
init_db() é chamado na autenticação
  └─ seed_db_if_missing()
       └─ DB_PATH existe → retorna imediatamente, sem nenhuma ação
       └─ Log: "Banco operacional encontrado. Utilizando banco existente."
```

**O banco operacional jamais é sobrescrito por um redeploy**, mesmo que o `seed.db` dentro da imagem tenha sido atualizado.

### Desenvolvimento local (sem DATA_DIR)

`DATA_DIR` resolve para `./data`. Se `./data/db.sqlite` não existir, o seed é copiado automaticamente. O fluxo é idêntico ao de produção.

---

## Atualizar o seed

Quando for necessário incluir novos dados históricos ou parâmetros no seed (por exemplo, após um novo contrato ser configurado):

```bash
# 1. Gerar o seed a partir do banco operacional local atualizado
cp data/db.sqlite data/seed.db
sqlite3 data/seed.db "VACUUM;"

# 2. Versionar
git add data/seed.db
git commit -m "chore: atualiza seed.db com novos parâmetros/histórico"
```

O novo seed só será aplicado em **instâncias novas** (onde não existe banco operacional). Instâncias existentes em produção não são afetadas.

---

## Estrutura de diretórios em produção

```
/mnt/data/                  ← DATA_DIR (Persistent Disk do Render)
├── db.sqlite               ← banco operacional (copiado do seed na primeira vez)
└── runs/
    └── {YYYY-MM}/
        ├── status.json
        ├── input/
        │   ├── faturamento/
        │   └── eventos/
        ├── processed/
        │   ├── faturamento.json
        │   └── eventos_{uid}.json
        └── reports/
            ├── {uid}.pdf
            └── versions/
                └── {uid}_v{n}_{timestamp}.pdf
```

```
/app/                       ← imagem Docker (efêmero, recriado a cada deploy)
└── data/
    ├── seed.db             ← banco inicial (somente leitura, nunca modificado)
    └── units.yaml          ← configuração estrutural das unidades
```
