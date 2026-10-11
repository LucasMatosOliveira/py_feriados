"""Script de validação e auditoria de qualidade do arquivo JSONL de feriados."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def validate_file(jsonl_path: Path) -> bool:
    if not jsonl_path.exists():
        console.print(f"[red]Arquivo não encontrado: {jsonl_path}[/]")
        return False

    console.print(Panel(f"[bold cyan]Auditoria de Qualidade:[/] {jsonl_path}", expand=False))

    errors = 0
    total_lines = 0

    # Contadores
    tipo_counts: dict[str, int] = {}
    cidades_com_feriado: set[int] = set()
    ufs_presentes: set[str] = set()
    feriados_por_cidade: dict[int, int] = {}

    # Eventos de amostra para spot-check
    spot_gv = []
    spot_sp = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            total_lines += 1
            line = line.strip()
            if not line:
                continue

            try:
                item = json.loads(line)
            except Exception as e:
                console.print(f"[red]Linha {line_num}: JSON inválido ({e})[/]")
                errors += 1
                continue

            # 1. Campos obrigatórios
            required_keys = ["uf", "ibge", "cidade", "tipo", "dia", "dia_iso", "nome", "bancario"]
            missing = [k for k in required_keys if k not in item]
            if missing:
                console.print(f"[red]Linha {line_num}: Chaves ausentes {missing}[/]")
                errors += 1

            tipo = item.get("tipo")
            tipo_counts[tipo] = tipo_counts.get(tipo, 0) + 1

            # 2. Formato de datas
            dia = item.get("dia", "")
            dia_iso = item.get("dia_iso", "")
            try:
                datetime.strptime(dia, "%d/%m/%Y")
            except Exception:
                console.print(f"[yellow]Linha {line_num}: Formato 'dia' inválido ({dia})[/]")
                errors += 1

            try:
                datetime.strptime(dia_iso, "%Y-%m-%d")
            except Exception:
                console.print(f"[yellow]Linha {line_num}: Formato 'dia_iso' inválido ({dia_iso})[/]")
                errors += 1

            # 3. Invariantes de Não-Duplicação
            uf = item.get("uf")
            ibge = item.get("ibge")
            cidade = item.get("cidade")

            if tipo in ("Nacional", "Facultativo", "Comemorativa"):
                if uf is not None or ibge is not None or cidade is not None:
                    console.print(f"[red]Linha {line_num}: Evento {tipo} deveria ter uf/ibge/cidade nulos, mas tem: {uf}, {ibge}, {cidade}[/]")
                    errors += 1

            elif tipo == "Estadual":
                if uf is None or ibge is not None or cidade is not None:
                    console.print(f"[red]Linha {line_num}: Evento Estadual deveria ter apenas UF, mas tem: uf={uf}, ibge={ibge}, cidade={cidade}[/]")
                    errors += 1
                if uf:
                    ufs_presentes.add(uf)

            elif tipo == "Municipal":
                if uf is None or ibge is None or cidade is None:
                    console.print(f"[red]Linha {line_num}: Evento Municipal incompleto: uf={uf}, ibge={ibge}, cidade={cidade}[/]")
                    errors += 1
                if ibge:
                    cidades_com_feriado.add(ibge)
                    feriados_por_cidade[ibge] = feriados_por_cidade.get(ibge, 0) + 1
                if uf:
                    ufs_presentes.add(uf)

            # Coleta para spot-check
            if ibge == 3127701:
                spot_gv.append(item.get("nome"))
            elif ibge == 3550308:
                spot_sp.append(item.get("nome"))

    # Tabela de Resultados
    table = Table(title="Estatísticas da Base de Feriados", show_header=True, header_style="bold magenta")
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor", justify="right", style="green")

    table.add_row("Total de Linhas", f"{total_lines:,}")
    table.add_row("Tamanho em Disco", f"{jsonl_path.stat().st_size / (1024 * 1024):.2f} MB")
    table.add_row("Total de Erros Encontrados", f"{errors}")
    table.add_section()

    for tipo, count in sorted(tipo_counts.items()):
        table.add_row(f"Eventos: {tipo}", f"{count:,}")

    table.add_section()
    table.add_row("Municípios com Feriados Municipais", f"{len(cidades_com_feriado):,}")
    table.add_row("UFs Encontradas", f"{len(ufs_presentes)} / 27")

    if feriados_por_cidade:
        max_mu = max(feriados_por_cidade.values())
        avg_mu = sum(feriados_por_cidade.values()) / len(feriados_por_cidade)
        table.add_row("Média de Feriados Municipais / Cidade", f"{avg_mu:.2f}")
        table.add_row("Máximo de Feriados Municipais em 1 Cidade", f"{max_mu}")

    console.print()
    console.print(table)

    # Spot-Checks
    console.print("\n[bold cyan]Spot-Checks de Cidades Conhecidas:[reset]")
    if spot_gv:
        console.print(f"  [green]✓[/] Governador Valadares (MG): {spot_gv}")
    else:
        console.print("  [dim]• Governador Valadares ainda não presente no arquivo.[/]")

    if spot_sp:
        console.print(f"  [green]✓[/] São Paulo (SP): {spot_sp}")
    else:
        console.print("  [dim]• São Paulo ainda não presente no arquivo.[/]")

    # Sanidade de bounds
    if any(c > 10 for c in feriados_por_cidade.values()):
        console.print("[yellow]Aviso: Há cidades com mais de 10 feriados municipais. Verifique se feriados federais foram duplicados como municipais.[/]")

    success = errors == 0
    if success:
        console.print("\n[bold green]✓ Todos os testes de integridade e não-duplicação passaram com sucesso![/]")
    else:
        console.print(f"\n[bold red]✗ Foram encontrados {errors} problemas na base.[/]")

    return success


def main():
    repo_root = Path(__file__).resolve().parent.parent
    default_jsonl = repo_root / "data" / "feriados_brasil_2026.jsonl"
    if not default_jsonl.exists():
        fallback = repo_root / "feriados_brasil_2026.jsonl"
        if fallback.exists():
            default_jsonl = fallback

    parser = argparse.ArgumentParser(description="Audita e valida a integridade do JSONL de feriados.")
    parser.add_argument("file", nargs="?", default=str(default_jsonl), help="Caminho do arquivo .jsonl")
    args = parser.parse_args()

    success = validate_file(Path(args.file))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
