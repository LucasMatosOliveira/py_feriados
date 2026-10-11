# Mini-Projeto: Exemplo de Consumo da Base de Feriados

Este diretório contém uma implementação prática e reutilizável para consultar, filtrar e manipular a base de dados consolidada de feriados (`data/feriados_brasil_2026.jsonl`).

---

## Objetivo

A base de dados foi construída seguindo uma **hierarquia sem redundância**:
- **Nível Federal:** feriados nacionais e pontos facultativos registrados uma única vez (`uf: null`, `ibge: null`).
- **Nível Estadual:** feriados estaduais vinculados apenas à respectiva UF (`uf: "SP"`, `ibge: null`).
- **Nível Municipal:** feriados específicos de cada cidade vinculados ao código IBGE (`uf: "SP"`, `ibge: 3550308`).

Este mini-projeto demonstra como reconstruir essa hierarquia em tempo de execução de forma eficiente, permitindo responder perguntas como:
- *Uma determinada data é feriado em Campinas/SP?*
- *Haverá expediente bancário em Belo Horizonte/MG no dia X?*
- *Quais são todos os feriados aplicáveis ao município Y ao longo do ano?*

---

## Como Executar a Demonstração

Basta rodar o script interativo:

```bash
python examples/consulta_feriados.py
```

O script executará automaticamente consultas para múltiplos cenários (São Paulo, Belo Horizonte, checagens de datas e próximos feriados).

---

## Exemplos de Uso

### 1. Usando a classe `CalendarioFeriados` (Python Puro)

A classe [`CalendarioFeriados`](consulta_feriados.py) indexa a base em memória e permite buscas rápidas sem necessidade de bancos de dados externos:

```python
from datetime import date
from examples.consulta_feriados import CalendarioFeriados

# Inicializa carregando a base de dados JSONL
calendario = CalendarioFeriados()

# 1. Obter todos os feriados aplicáveis a São Paulo/SP (IBGE: 3550308)
feriados_sp = calendario.obter_feriados(uf="SP", ibge=3550308)
for ev in feriados_sp:
    print(f"{ev.dia_str} - {ev.nome} ({ev.tipo})")

# 2. Checagem pontual de data
eh_feriado = calendario.is_feriado(date(2026, 1, 25), uf="SP", ibge=3550308)
if eh_feriado:
    print(f"Feriado: {eh_feriado.nome}")
else:
    print("Dia útil!")

# 3. Filtrar apenas feriados bancários
bancarios_mg = calendario.obter_feriados(uf="MG", ibge=3106200, apenas_bancarios=True)
```

---

### 2. Com Pandas

Se você preferir trabalhar com DataFrames para análises estatísticas:

```python
import pandas as pd

df = pd.read_json("data/feriados_brasil_2026.jsonl", lines=True)

# Filtrar todos os feriados aplicáveis à cidade do Rio de Janeiro (IBGE 3304557)
rio_feriados = df[
    (df["tipo"].isin(["Nacional", "Facultativo"])) |
    ((df["tipo"] == "Estadual") & (df["uf"] == "RJ")) |
    ((df["tipo"] == "Municipal") & (df["ibge"] == 3304557))
]

print(rio_feriados[["dia", "nome", "tipo", "bancario"]])
```

---

### 3. Com DuckDB / SQL

Para consultas analíticas ultrarrápidas diretamente sobre o arquivo sem necessidade de ingestão prévia:

```sql
SELECT dia, nome, tipo, bancario
FROM read_json_auto('data/feriados_brasil_2026.jsonl')
WHERE 
    tipo IN ('Nacional', 'Facultativo')
    OR (tipo = 'Estadual' AND uf = 'RS')
    OR (tipo = 'Municipal' AND ibge = 4314902) -- Porto Alegre
ORDER BY dia_iso;
```
