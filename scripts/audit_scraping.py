"""Script de auditoria de integridade do scraping contra a fonte viva (feriadosapi.com)."""

import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import random
import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path para importar o pacote scraper
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.progress import track
from rich.table import Table

from scraper.client import FeriadosClient
from scraper.discovery import get_municipios

console = Console()


def audit_scraping(
    jsonl_path: Path,
    checkpoint_path: Path,
    log_path: Path,
    sample_size: int = 20,
) -> bool:
    console.print(Panel("[bold green]Auditoria de Qualidade do Scraping[/]\nComparação direta contra a fonte viva em feriadosapi.com", expand=False))

    all_passed = True

    # 1. Checagem do Checkpoint
    console.print("\n[bold cyan]1. Auditoria do Checkpoint e Total de Municípios[/]")
    if not checkpoint_path.exists():
        console.print(f"[red]✗ Checkpoint {checkpoint_path} não encontrado![/]")
        all_passed = False
    else:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            ck_data = json.load(f)
        cities_done = set(ck_data.get("cities_done", []))
        states_done = set(ck_data.get("states_done", []))
        fed_done = ck_data.get("federal_done", False)

        all_municipios = get_municipios()
        total_esperado = len(all_municipios)

        faltantes = [m for m in all_municipios if m.ibge not in cities_done]

        if len(cities_done) == total_esperado:
            console.print(f"  [green]✓[/] Checkpoint registrou 100% dos municípios ({total_esperado:,}/{total_esperado:,}).")
        else:
            console.print(f"  [yellow]![/] Municípios processados no checkpoint: {len(cities_done):,} de {total_esperado:,} ({len(faltantes)} pendentes).")
            if len(faltantes) > 0:
                all_passed = False

        if len(states_done) == 27:
            console.print("  [green]✓[/] Todas as 27 UFs foram concluídas no checkpoint.")
        else:
            console.print(f"  [red]✗ UFs concluídas: {len(states_done)}/27.[/]")
            all_passed = False

        if fed_done:
            console.print("  [green]✓[/] Nível Federal concluído no checkpoint.")
        else:
            console.print("  [red]✗ Nível Federal NÃO concluído no checkpoint.[/]")
            all_passed = False

    # 2. Auditoria do Log de Erros
    console.print("\n[bold cyan]2. Auditoria de Logs de Rede (scraper.log)[/]")
    if not log_path.exists():
        console.print("  [dim]• Nenhum arquivo scraper.log gerado (sem erros de rede registrados).[/]")
    else:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            log_content = f.read()

        http_429_count = log_content.count("HTTP 429")
        http_5xx_count = sum(log_content.count(f"HTTP {code}") for code in [500, 502, 503, 504])
        errors_count = log_content.count("[ERROR]")

        console.print(f"  • Bloqueios temporários (HTTP 429 recuperados pelo retry): {http_429_count}")
        console.print(f"  • Erros de servidor (HTTP 5xx): {http_5xx_count}")
        console.print(f"  • Falhas definitivas ([ERROR]): {errors_count}")

        if errors_count == 0:
            console.print("  [green]✓[/] Zero falhas definitivas no log de scraping.")
        else:
            console.print(f"  [red]✗ O log contém {errors_count} falhas definitivas que exigem atenção![/]")
            all_passed = False

    # 3. Análise de Cidades com 0 Feriados Municipais no JSONL
    console.print("\n[bold cyan]3. Análise de Cidades com Zero Feriados Municipais[/]")
    cidades_no_jsonl: dict[int, list[str]] = {}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            if item.get("tipo") == "Municipal":
                ibge = item.get("ibge")
                if ibge:
                    cidades_no_jsonl.setdefault(ibge, []).append(item.get("nome", ""))

    cidades_zeradas = [m for m in all_municipios if m.ibge not in cidades_no_jsonl]
    console.print(f"  • Cidades onde a API não retornou nenhum feriado municipal: {len(cidades_zeradas):,} de {len(all_municipios):,} ({len(cidades_zeradas)/len(all_municipios)*100:.1f}%)")

    # 4. Auditoria Cruzada Contra a Fonte Viva (Amostragem Aleatória)
    console.print(f"\n[bold cyan]4. Teste de Amostragem Cruzada ao Vivo ({sample_size} municípios aleatórios)[/]")
    console.print("  [dim]Consultando a página ao vivo em feriadosapi.com para comparar resultado idêntico...[/]")

    client = FeriadosClient()
    # Pega uma amostra que inclui cidades com feriados e cidades zeradas
    amostra = random.sample(all_municipios, min(sample_size, len(all_municipios)))

    diff_table = Table(title="Confronto: Arquivo Raspado vs. Site ao Vivo", show_header=True)
    diff_table.add_column("UF", style="cyan", width=4)
    diff_table.add_column("Cidade", style="bold", width=24)
    diff_table.add_column("IBGE", style="dim", width=9)
    diff_table.add_column("Raspado", justify="center", width=8)
    diff_table.add_column("Ao Vivo", justify="center", width=8)
    diff_table.add_column("Status", justify="center", width=14)
    diff_table.add_column("Detalhe / Diferença", style="yellow")

    matches = 0
    mismatches = 0

    for mun in track(amostra, description="Validando contra site ao vivo..."):
        # Feriados no arquivo raspado
        nomes_raspados = sorted(cidades_no_jsonl.get(mun.ibge, []))

        # Busca fresca ao vivo no site
        try:
            live_items = client.fetch_city_page(2026, mun.uf, mun.ibge)
            nomes_ao_vivo = sorted([x.get("nome", "").strip() for x in live_items if x.get("tipo") == "MUNICIPAL"])

            is_match = nomes_raspados == nomes_ao_vivo
            if is_match:
                matches += 1
                status = "[green]MATCH (100%)[/]"
                detalhe = "[dim green]Idêntico[/]"
            else:
                mismatches += 1
                all_passed = False
                adicionados = set(nomes_ao_vivo) - set(nomes_raspados)
                removidos = set(nomes_raspados) - set(nomes_ao_vivo)

                if len(nomes_raspados) == len(nomes_ao_vivo):
                    status = "[yellow]NOME ALTERADO[/]"
                    detalhe = f"Site renomeou: {list(removidos)[0]!r} -> {list(adicionados)[0]!r}"
                else:
                    status = "[red]DIVERGÊNCIA[/]"
                    partes = []
                    if adicionados:
                        partes.append(f"+{len(adicionados)} no site: {list(adicionados)}")
                    if removidos:
                        partes.append(f"-{len(removidos)} no site: {list(removidos)}")
                    detalhe = "; ".join(partes)

            diff_table.add_row(
                mun.uf,
                mun.nome[:23],
                str(mun.ibge),
                str(len(nomes_raspados)),
                str(len(nomes_ao_vivo)),
                status,
                detalhe,
            )
        except Exception as e:
            mismatches += 1
            diff_table.add_row(mun.uf, mun.nome[:23], str(mun.ibge), str(len(nomes_raspados)), "ERRO", f"[red]{e}[/]", "Falha de conexão")
            all_passed = False

    console.print(diff_table)

    if mismatches == 0:
        console.print(f"\n[bold green]✓ Amostragem perfeita: {matches}/{matches} cidades bateram 100% com o site oficial![/]")
    else:
        console.print(f"\n[bold yellow]! Foram encontradas {mismatches} divergências ou renomeações recentes na fonte viva.[/]")

    return all_passed


def main():
    repo_root = Path(__file__).resolve().parent.parent
    default_jsonl = repo_root / "data" / "feriados_brasil_2026.jsonl"
    if not default_jsonl.exists():
        fallback_jsonl = repo_root / "feriados_brasil_2026.jsonl"
        if fallback_jsonl.exists():
            default_jsonl = fallback_jsonl

    default_ck = repo_root / "data" / ".checkpoint_2026.json"
    if not default_ck.exists():
        fallback_ck = repo_root / ".checkpoint_2026.json"
        if fallback_ck.exists():
            default_ck = fallback_ck

    default_log = repo_root / "logs" / "scraper.log"
    if not default_log.exists():
        fallback_log = repo_root / "scraper.log"
        if fallback_log.exists():
            default_log = fallback_log

    parser = argparse.ArgumentParser(description="Audita se o scraping foi feito de forma fidedigna à fonte.")
    parser.add_argument("file", nargs="?", default=str(default_jsonl), help="Arquivo .jsonl raspado")
    parser.add_argument("--checkpoint", default=str(default_ck), help="Arquivo de checkpoint")
    parser.add_argument("--log", default=str(default_log), help="Arquivo de log")
    parser.add_argument("--sample", type=int, default=15, help="Quantidade de cidades aleatórias para comparar ao vivo")

    args = parser.parse_args()
    success = audit_scraping(
        jsonl_path=Path(args.file),
        checkpoint_path=Path(args.checkpoint),
        log_path=Path(args.log),
        sample_size=args.sample,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
