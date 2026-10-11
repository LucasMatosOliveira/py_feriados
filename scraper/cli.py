#!/usr/bin/env python3
"""CLI principal para execução do scraper de feriados."""

import argparse
import logging
import os
from pathlib import Path
import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from scraper.checkpoint import CheckpointManager
from scraper.client import FeriadosClient
from scraper.collector import HolidayCollector, TODAS_UFS
from scraper.config import Config
from scraper.discovery import get_municipios

console = Console()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(log_dir / "scraper.log", encoding="utf-8")],
    )


def print_banner(ano: int, ufs: list[str], total_cidades: int, output_file: str) -> None:
    text = (
        f"[bold cyan]Ano:[/] {ano} | "
        f"[bold cyan]UFs:[/] {len(ufs)} | "
        f"[bold cyan]Cidades:[/] {total_cidades:,} | "
        f"[bold cyan]Saída:[/] {output_file}"
    )
    console.print(Panel(text, title="[bold green]Scraper de Feriados Brasil - feriadosapi.com[/]", expand=False))


def generate_summary(output_path: Path) -> None:
    """Lê o arquivo JSONL final e exibe estatísticas resumidas."""
    import json
    if not output_path.exists():
        console.print("[red]Arquivo de saída não encontrado![/]")
        return

    counts: dict[str, int] = {}
    total_lines = 0

    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            total_lines += 1
            try:
                item = json.loads(line)
                tipo = item.get("tipo", "Desconhecido")
                counts[tipo] = counts.get(tipo, 0) + 1
            except Exception:
                pass

    size_mb = output_path.stat().st_size / (1024 * 1024)

    table = Table(title="Resumo da Coleta de Feriados", show_header=True, header_style="bold magenta")
    table.add_column("Categoria (Tipo)", style="cyan")
    table.add_column("Quantidade de Eventos", justify="right", style="green")

    for tipo, count in sorted(counts.items()):
        table.add_row(tipo, f"{count:,}")

    table.add_section()
    table.add_row("[bold]Total Geral de Linhas[/]", f"[bold]{total_lines:,}[/]")
    table.add_row("[bold]Tamanho do Arquivo[/]", f"[bold]{size_mb:.2f} MB[/]")

    console.print()
    console.print(table)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Coleta e consolida feriados nacionais, estaduais e municipais de feriadosapi.com em JSONL."
    )
    parser.add_argument("--ano", type=int, default=2026, help="Ano do calendário (padrão: 2026)")
    parser.add_argument("--uf", type=str, default=None, help="Filtrar por UF específica (ex: AC, SP, MG)")
    parser.add_argument("--limit", type=int, default=None, help="Limitar número de municípios (para testes)")
    parser.add_argument("--output", type=str, default=None, help="Caminho do arquivo .jsonl de saída")
    parser.add_argument("--workers", type=int, default=Config.max_workers, help="Concorrência de requisições")
    parser.add_argument("--reset", action="store_true", help="Reinicia a coleta do zero, limpando o checkpoint")
    parser.add_argument("--verbose", "-v", action="store_true", help="Habilita logs detalhados no arquivo scraper.log")

    args = parser.parse_args()

    setup_logging(args.verbose)

    ano: int = args.ano
    uf_filtro: str | None = args.uf.upper() if args.uf else None
    limit: int | None = args.limit

    if args.output:
        out_file = Path(args.output)
    else:
        out_file = Path("data") / f"feriados_brasil_{ano}.jsonl"

    checkpoint_file = Path("data") / f".checkpoint_{ano}.json"

    if args.reset:
        console.print("[yellow]Modo --reset ativo: limpando checkpoint e arquivo de saída...[/]")
        if checkpoint_file.exists():
            checkpoint_file.unlink()
        if out_file.exists():
            out_file.unlink()

    # 1. Carregar municípios
    with console.status("[bold green]Carregando lista oficial de municípios (IBGE)...[/]"):
        municipios = get_municipios()

    if uf_filtro:
        if uf_filtro not in TODAS_UFS:
            console.print(f"[bold red]Erro:[/] UF inválida '{uf_filtro}'. Opções válidas: {', '.join(TODAS_UFS)}")
            return 1
        municipios = [m for m in municipios if m.uf == uf_filtro]
        ufs_alvo = [uf_filtro]
    else:
        ufs_alvo = TODAS_UFS

    if limit is not None:
        municipios = municipios[:limit]

    print_banner(ano, ufs_alvo, len(municipios), str(out_file))

    checkpoint = CheckpointManager(checkpoint_file)
    client = FeriadosClient()
    collector = HolidayCollector(
        client=client,
        checkpoint=checkpoint,
        output_file=out_file,
        ano=ano,
        max_workers=args.workers,
    )

    start_time = time.monotonic()

    # 2. Camada Federal
    with console.status("[bold green]Coletando feriados Federais, Facultativos e Comemorativas...[/]"):
        fed_count = collector.collect_federal()
        if fed_count > 0:
            console.print(f"[green]✓[/] Feriados Federais coletados: [bold]{fed_count}[/] novos eventos gravados.")
        else:
            console.print("[dim]• Feriados Federais já gravados anteriormente.[/]")

    # 3. Camada Estadual
    with console.status(f"[bold green]Coletando feriados Estaduais ({len(ufs_alvo)} UFs)...[/]"):
        est_count = collector.collect_states(ufs=ufs_alvo)
        if est_count > 0:
            console.print(f"[green]✓[/] Feriados Estaduais coletados: [bold]{est_count}[/] novos eventos gravados.")
        else:
            console.print("[dim]• Feriados Estaduais já gravados anteriormente.[/]")

    # 4. Camada Municipal
    ja_concluidos = sum(1 for m in municipios if collector.checkpoint.is_city_done(m.ibge))
    a_fazer = len(municipios) - ja_concluidos

    if a_fazer > 0:
        console.print(f"\n[bold yellow]Iniciando coleta de {a_fazer:,} municípios ({ja_concluidos:,} já no checkpoint)...[/]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Coletando municípios...", total=len(municipios), completed=ja_concluidos)

            def on_progress(mun, count):
                progress.update(
                    task,
                    advance=1,
                    description=f"[cyan]{mun.uf} - {mun.nome[:22]} ([green]+{count}[/])",
                )

            collector.collect_cities(municipios, progress_callback=on_progress)
    else:
        console.print("[dim]• Todos os municípios já haviam sido concluídos no checkpoint.[/]")

    elapsed = time.monotonic() - start_time
    console.print(f"\n[bold green]✓ Coleta finalizada com sucesso em {elapsed:.1f}s![/]")

    generate_summary(out_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
