# Base de Dados de Feriados do Brasil

Projeto automatizado para raspagem, estruturação, deduplicação hierárquica e consolidação da base de dados de feriados no Brasil (nacionais, facultativos federais, estaduais e municipais), abrangendo todos os **5.570+ municípios** cadastrados no IBGE a partir da plataforma [feriadosapi.com](https://feriadosapi.com).

A saída é gerada em formato padrão aberto **JSON Lines (`.jsonl`)**, otimizada para ingestão direta em bancos de dados, data lakes, ferramentas analíticas (Pandas, Polars, DuckDB, Spark) e sistemas corporativos.

---

## Sumário
1. [Destaques da Arquitetura](#destaques-da-arquitetura)
2. [Pré-requisitos](#pré-requisitos)
3. [Instalação e Configuração](#instalação-e-configuração)
4. [Como Executar o Coletor (`main.py`)](#como-executar-o-coletor-mainpy)
   - [Execução Completa](#execução-completa)
   - [Opções e Parâmetros da CLI](#opções-e-parâmetros-da-cli)
   - [Exemplos Práticos de Uso](#exemplos-práticos-de-uso)
5. [Scripts de Validação e Auditoria](#scripts-de-validação-e-auditoria)
   - [Validação Estrutural e de Qualidade (`scripts/validate.py`)](#validação-estrutural-e-de-qualidade-scriptsvalidatepy)
   - [Auditoria Cruzada contra a Fonte Viva (`scripts/audit_scraping.py`)](#auditoria-cruzada-contra-a-fonte-viva-scriptsaudit_scrapingpy)
6. [Estrutura dos Dados de Saída (JSONL)](#estrutura-dos-dados-de-saída-jsonl)
7. [Organização do Projeto](#organização-do-projeto)
8. [Mecanismo de Resiliência e Checkpoint](#mecanismo-de-resiliência-e-checkpoint)
9. [Como Consumir a Base Gerada](#como-consumir-a-base-gerada)
10. [Perguntas Frequentes & Solução de Problemas](#perguntas-frequentes--solução-de-problemas)

---

## Destaques da Arquitetura

- **Hierarquia Deduplicada sem Redundância:**
  - **Nível Federal:** Feriados nacionais, pontos facultativos e datas comemorativas são coletados uma única vez (`uf`, `ibge` e `cidade` como `null`).
  - **Nível Estadual:** Feriados estaduais são associados estritamente à UF (`ibge` e `cidade` como `null`), totalizando 27 requisições.
  - **Nível Municipal:** Apenas feriados genuinamente municipais de cada localidade são gravados com os dados completos (`uf`, `ibge` e `cidade`). Feriados federais ou estaduais que o site repete na página da cidade são automaticamente filtrados para evitar multiplicação desnecessária de dados.
- **Checkpoint Atômico e Retomada Automática:**
  - O estado do progresso é salvo no disco de forma atômica (`.checkpoint_<ano>.json`).
  - Se a coleta for interrompida a qualquer instante (queda de conexão, encerramento do terminal ou `Ctrl+C`), basta executar novamente o comando: o coletor retoma exatamente do último município pendente, sem duplicar dados nem perder o que já foi salvo.
- **Rate Limiting e Resiliência Adaptativa:**
  - Rate limiter thread-safe configurado para respeitar as janelas de requisições da infraestrutura (Vercel).
  - Tratamento inteligente de erros `HTTP 429 (Too Many Requests)` e `5xx` com *exponential backoff* e leitura do cabeçalho `Retry-After`.
- **Extração de Alta Performance (RSC Chunks):**
  - O cliente extrai diretamente os arrays serializados dos chunks de *React Server Components* (Next.js) inseridos no HTML, tornando a extração centenas de vezes mais rápida e leve do que analisar a árvore DOM inteira com parsers pesados. Fallback automático para `application/ld+json`.
- **Descoberta Oficial dos Municípios:**
  - Integração com a API de Localidades do IBGE para obter a lista oficial completa dos 5.570 municípios do Brasil, com cache local em `.cache/municipios.json` e fallback para leitura de sitemaps XML.

---

## Pré-requisitos

- **Python 3.10 ou superior** (desenvolvido e testado em Python 3.12).
- Gerenciador de pacotes **pip**.
- Conexão com a internet ativa para realizar as consultas às páginas.

---

## Instalação e Configuração

### 1. Clonar ou Acessar a Pasta do Projeto

```bash
git clone https://github.com/LucasMatosOliveira/py_feriados.git
cd py_feriados
```
### 2. Criar um Ambiente Virtual (Recomendado)

No Linux / macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

No Windows (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

No Windows (Prompt de Comando - CMD):
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

### 3. Instalar o Pacote e Dependências

Instale as dependências diretamente:
```bash
pip install -r requirements.txt
```

Ou instale o projeto em modo editável/executável no seu ambiente para disponibilizar o comando diretamente no seu terminal (`PATH`):
```bash
pip install -e .
```

Com isso, o comando `py-feriados` (ou `feriados`) ficará acessível de qualquer lugar no seu terminal.
---

## Como Executar o Coletor

Você pode rodar via script Python direto ou através do comando executável instalado no seu `PATH`:

### Execução Completa

Para executar a coleta completa de feriados federais, estaduais e de todos os 5.570 municípios para o ano padrão (**2026**):

```bash
# Via CLI instalada no PATH:
py-feriados

# Ou diretamente via script:
python main.py
```
Durante a execução, você verá uma interface interativa no terminal:
- Identificação dos municípios via IBGE / cache local.
- Coleta instantânea do nível Federal.
- Coleta do nível Estadual para as 27 UFs.
- Barra de progresso com tempo decorrido, previsão de término e contagem em tempo real para os municípios.
- Tabela de resumo final com a distribuição das categorias de feriados e tamanho do arquivo gerado.

---

### Opções e Parâmetros da CLI

Execute `py-feriados --help` (ou `python main.py --help`) para ver todas as opções disponíveis:
| Argumento | Tipo | Padrão | Descrição |
| :--- | :---: | :---: | :--- |
| `--ano` | `int` | `2026` | Ano de referência do calendário a ser raspado. |
| `--uf` | `str` | `None` | Filtra a coleta para uma única Unidade Federativa (ex: `SP`, `RJ`, `MG`). |
| `--limit` | `int` | `None` | Limita o número de municípios a processar (ideal para testes rápidos). |
| `--output` | `str` | `None` | Caminho do arquivo `.jsonl` de saída (padrão: `feriados_brasil_<ano>.jsonl`). |
| `--workers` | `int` | `2` | Número de threads concorrentes para requisições municipais. |
| `--reset` | `flag` | `False` | Limpa o arquivo de saída anterior e o checkpoint, reiniciando do zero. |
| `--verbose`, `-v` | `flag` | `False` | Registra detalhes adicionais de debug no arquivo de log `scraper.log`. |

---

### Exemplos Práticos de Uso

#### 1. Teste rápido (coletar apenas 5 municípios):
```bash
python main.py --limit 5
```

#### 2. Coletar apenas municípios de um estado (ex: Rio de Janeiro):
```bash
python main.py --uf RJ
```

#### 3. Teste rápido em um estado específico (ex: São Paulo, apenas 3 cidades):
```bash
python main.py --uf SP --limit 3
```

#### 4. Coletar um ano diferente (ex: 2025):
```bash
python main.py --ano 2025
```

#### 5. Resetar e coletar do zero (apaga checkpoint anterior e arquivo de saída):
```bash
python main.py --reset
```

#### 6. Especificar um arquivo de saída customizado:
```bash
python main.py --uf MG --output feriados_minas_gerais.jsonl
```

---

## Scripts de Validação e Auditoria

O repositório inclui duas ferramentas prontas para atestar a qualidade e fidedignidade da base gerada:

### Validação Estrutural e de Qualidade (`scripts/validate.py`)

Inspeciona o arquivo `.jsonl` gerado e valida:
- Sintaxe JSON válida em cada linha.
- Presença de todos os campos obrigatórios (`uf`, `ibge`, `cidade`, `tipo`, `dia`, `dia_iso`, `nome`, `bancario`).
- Formatação correta das datas nos padrões `DD/MM/YYYY` e `YYYY-MM-DD`.
- **Invariantes de não-duplicação:** garante que feriados nacionais não contenham UF/IBGE preenchidos indevidamente, e que feriados estaduais contenham apenas UF.
- Cobertura de UFs e média de feriados municipais por cidade.
- Spot-checks automáticos em municípios conhecidos (ex: São Paulo - SP e Governador Valadares - MG).

**Como executar:**
```bash
python scripts/validate.py
```
*(Valida automaticamente `data/feriados_brasil_2026.jsonl` por padrão, ou informe o caminho do arquivo explicitamente)*.

---

### Auditoria Cruzada contra a Fonte Viva (`scripts/audit_scraping.py`)

Faz um confronto direto da base local contra o site oficial em produção (`feriadosapi.com`):
1. **Auditoria de Checkpoint:** Confirma se 100% dos 5.570+ municípios e 27 UFs foram concluídos no checkpoint.
2. **Auditoria de Logs:** Analisa `logs/scraper.log` verificando se ocorreram erros definitivos de rede ou servidor.
3. **Amostragem Aleatória ao Vivo:** Seleciona cidades aleatoriamente, faz a requisição em tempo real à página oficial do município e valida se a lista de feriados bate 100% com o arquivo raspado.

**Como executar:**
```bash
# Executa a auditoria comparando 15 cidades aleatórias contra a web:
python scripts/audit_scraping.py

# Especificar quantidade de amostras (ex: 25 cidades):
python scripts/audit_scraping.py --sample 25
```

---

## Estrutura dos Dados de Saída (JSONL)

Cada linha do arquivo `.jsonl` representa um evento ou feriado estruturado em formato JSON.

### Dicionário de Campos

| Campo | Tipo | Descrição | Exemplo |
| :--- | :---: | :--- | :--- |
| `uf` | `string` ou `null` | Sigla da Unidade Federativa (apenas para Estadual e Municipal). `null` para Nacional. | `"SP"` |
| `ibge` | `int` ou `null` | Código IBGE de 7 dígitos do município. Apenas presente em eventos Municipais. | `3550308` |
| `cidade` | `string` ou `null` | Nome oficial do município. Apenas presente em eventos Municipais. | `"São Paulo"` |
| `tipo` | `string` | Categoria do feriado: `"Nacional"`, `"Estadual"`, `"Municipal"`, `"Facultativo"` ou `"Comemorativa"`. | `"Municipal"` |
| `dia` | `string` | Data do evento no formato brasileiro (`DD/MM/YYYY`). | `"25/01/2026"` |
| `dia_iso` | `string` | Data do evento no formato ISO 8601 (`YYYY-MM-DD`). | `"2026-01-25"` |
| `nome` | `string` | Nome oficial ou denominação da data festiva / feriado. | `"Aniversário da Cidade de São Paulo"` |
| `bancario` | `boolean` | Indica se o feriado acarreta fechamento bancário oficial. | `true` |

---

### Exemplos Reais de Registros

#### 1. Feriado Nacional (Federal)
```json
{"uf": null, "ibge": null, "cidade": null, "tipo": "Nacional", "dia": "01/01/2026", "dia_iso": "2026-01-01", "nome": "Ano Novo", "bancario": true}
```

#### 2. Ponto Facultativo Federal
```json
{"uf": null, "ibge": null, "cidade": null, "tipo": "Facultativo", "dia": "17/02/2026", "dia_iso": "2026-02-17", "nome": "Carnaval", "bancario": true}
```

#### 3. Data Comemorativa Nacional
```json
{"uf": null, "ibge": null, "cidade": null, "tipo": "Comemorativa", "dia": "08/03/2026", "dia_iso": "2026-03-08", "nome": "Dia Internacional da Mulher", "bancario": false}
```

#### 4. Feriado Estadual
```json
{"uf": "SP", "ibge": null, "cidade": null, "tipo": "Estadual", "dia": "09/07/2026", "dia_iso": "2026-07-09", "nome": "Revolução Constitucionalista", "bancario": true}
```

#### 5. Feriado Municipal
```json
{"uf": "SP", "ibge": 3550308, "cidade": "São Paulo", "tipo": "Municipal", "dia": "25/01/2026", "dia_iso": "2026-01-25", "nome": "Aniversário da Cidade de São Paulo", "bancario": true}
```

---

## Organização do Projeto

```text
py_feriados/
├── .github/                   # Agentes e prompts para GitHub Copilot / SpecKit
├── .specify/                  # Configurações, memória e templates do SpecKit
├── .vscode/                   # Configurações do VS Code
├── .cache/                    # Cache local de municípios do IBGE (evita requisições repetidas)
│   └── municipios.json
├── data/                      # Base de dados consolidada e checkpoints de progresso
│   ├── feriados_brasil_2026.jsonl
│   └── .checkpoint_2026.json
├── examples/                  # Mini-projeto com exemplos práticos de consumo da base
│   ├── README.md              # Documentação e cenários de integração (Pandas, DuckDB, Python)
│   └── consulta_feriados.py   # Utilitário de consulta hierárquica e demo interativa
├── logs/                      # Logs de execução e auditoria de conexões de rede
│   └── scraper.log
├── scraper/                   # Pacote modular interno da aplicação
│   ├── __init__.py
│   ├── checkpoint.py          # Gerenciador de checkpoint atômico no disco
│   ├── client.py              # Cliente HTTP com throttling, retries e parser RSC/JSON-LD
│   ├── collector.py           # Orquestrador hierárquico multithread das 3 camadas
│   ├── config.py              # Configurações globais, URLs, timeouts e rate limiting
│   ├── discovery.py           # Módulo de descoberta de municípios (IBGE API / sitemaps)
│   └── models.py              # Dataclasses de dados tipados (Municipio, FeriadoRecord)
├── scripts/                   # Scripts auxiliares de validação e auditoria
│   ├── audit_scraping.py      # Auditoria comparativa ao vivo contra a fonte oficial
│   └── validate.py            # Validação estrutural de integridade e não-duplicação
├── .gitignore                 # Regras de exclusão do controle de versão
├── main.py                    # Ponto de entrada CLI para execução da coleta
├── README.md                  # Documento de referência completa do projeto
└── requirements.txt           # Dependências Python (requests, rich)
```

---

## Mecanismo de Resiliência e Checkpoint

Para raspar mais de 5.500 municípios de forma segura sem ser banido por rate limit e sem perder horas de trabalho se a internet oscilar:

1. **Escrita Atômica do Checkpoint:**
   O arquivo `.checkpoint_<ano>.json` registra quais UFs e municípios já foram processados. As gravações são feitas primeiro em um arquivo temporário (`.tmp`) e renomeadas atomicamente, prevenindo corrupção em caso de queda de energia ou terminação abrupta.
2. **Escrita Segura no Arquivo de Saída:**
   As linhas são anexadas (*append mode*) utilizando locks de sincronização de threads (`threading.Lock`), garantindo integridade mesmo com múltiplos workers concorrentes.
3. **Respeito ao Rate Limit:**
   Em `scraper/config.py`, o intervalo mínimo entre requisições (`min_request_interval = 0.45s`) e o número de workers simultâneos (`max_workers = 2`) garantem que o tráfego permaneça seguro e abaixo do limiar de bloqueio da Vercel. Caso o servidor retorne status 429, o cliente aguarda o tempo estipulado em `Retry-After` e retoma automaticamente.

---

## Como Consumir a Base Gerada

Para manter o `README.md` objetivo e fornecer um código testável e modular, o repositório inclui um mini-projeto prático no diretório [`examples/`](examples/):

- **Script Executável:** [`examples/consulta_feriados.py`](examples/consulta_feriados.py) implementa a classe `CalendarioFeriados` para reconstruir a hierarquia de feriados (Federal + Estadual + Municipal), consultar se datas específicas são dias úteis ou feriados bancários e listar próximos eventos.
- **Documentação de Integração:** [`examples/README.md`](examples/README.md) detalha padrões de uso com **Python puro**, **Pandas** e **DuckDB / SQL**.

**Para executar a demonstração interativa:**
```bash
python examples/consulta_feriados.py
```

---

## Perguntas Frequentes & Solução de Problemas

### Posso interromper a execução no meio do processo?
**Sim.** Basta apertar `Ctrl + C`. O progresso já salvo em disco no `.checkpoint_<ano>.json` e no arquivo `.jsonl` não será perdido. Ao rodar `python main.py` novamente, o script recomeçará exatamente de onde parou.

### O que fazer se eu quiser raspar tudo de novo do zero?
Basta passar a flag `--reset`:
```bash
python main.py --reset
```
Isso removerá o checkpoint anterior e o arquivo `.jsonl` gerado para o ano informado.

### Por que alguns municípios têm 0 feriados municipais?
Cerca de ~5% dos municípios brasileiros cadastrados no IBGE não possuem registros específicos de feriados municipais publicados na base de dados do portal de origem. A ferramenta preserva a fidelidade estrita com a fonte viva (conforme comprovado pelo script `scripts/audit_scraping.py`).

### Como alterar o ritmo da coleta ou o número de threads?
Você pode ajustar via linha de comando com `--workers <N>` (ex: `python main.py --workers 4`), ou configurar diretamente os parâmetros em `scraper/config.py`:
- `max_workers`: número de threads simultâneas.
- `min_request_interval`: intervalo mínimo em segundos entre chamadas.

---

## Licença

Este projeto é distribuído sob a licença [MIT](LICENSE) - sinta-se livre para utilizar, modificar e distribuir.
