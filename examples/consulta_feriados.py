"""Mini-projeto de exemplo: Consumo e consulta da base de feriados (JSONL).

Demonstra como carregar, indexar e consultar feriados respeitando a hierarquia:
Federal -> Estadual -> Municipal, além de verificar se uma data é feriado bancário.
"""

from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
import sys
from typing import Dict, List, Optional

# Garante que a raiz do projeto seja encontrada
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSONL = REPO_ROOT / "data" / "feriados_brasil_2026.jsonl"


@dataclass(frozen=True)
class EventoFeriado:
    data: date
    dia_str: str
    nome: str
    tipo: str
    bancario: bool
    uf: Optional[str] = None
    ibge: Optional[int] = None
    cidade: Optional[str] = None


class CalendarioFeriados:
    """Classe utilitária para consumo eficiente da base consolidada de feriados."""

    def __init__(self, jsonl_path: Path = DEFAULT_JSONL):
        self.jsonl_path = Path(jsonl_path)
        self.federais: List[EventoFeriado] = []
        self.estaduais: Dict[str, List[EventoFeriado]] = {}
        self.municipais: Dict[int, List[EventoFeriado]] = {}
        self._carregar_base()

    def _carregar_base(self) -> None:
        """Lê o arquivo JSONL e indexa os feriados em memória para consultas O(1)."""
        if not self.jsonl_path.exists():
            raise FileNotFoundError(
                f"Base de feriados não encontrada em: {self.jsonl_path}\n"
                "Execute o scraper primeiro através de: python main.py"
            )

        with open(self.jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                dt_iso = item.get("dia_iso")
                if not dt_iso:
                    continue

                try:
                    dt = datetime.strptime(dt_iso, "%Y-%m-%d").date()
                except ValueError:
                    continue

                evento = EventoFeriado(
                    data=dt,
                    dia_str=item["dia"],
                    nome=item["nome"],
                    tipo=item["tipo"],
                    bancario=bool(item.get("bancario", False)),
                    uf=item.get("uf"),
                    ibge=item.get("ibge"),
                    cidade=item.get("cidade"),
                )

                if evento.tipo in ("Nacional", "Facultativo", "Comemorativa"):
                    self.federais.append(evento)
                elif evento.tipo == "Estadual" and evento.uf:
                    self.estaduais.setdefault(evento.uf.upper(), []).append(evento)
                elif evento.tipo == "Municipal" and evento.ibge:
                    self.municipais.setdefault(evento.ibge, []).append(evento)

    def obter_feriados(
        self,
        uf: Optional[str] = None,
        ibge: Optional[int] = None,
        apenas_bancarios: bool = False,
        incluir_facultativos: bool = True,
        incluir_comemorativas: bool = False,
    ) -> List[EventoFeriado]:
        """Retorna todos os feriados aplicáveis a uma localidade (Federais + Estaduais + Municipais)."""
        resultado: List[EventoFeriado] = []

        # 1. Federais (aplicam-se a todo o território nacional)
        for ev in self.federais:
            if ev.tipo == "Facultativo" and not incluir_facultativos:
                continue
            if ev.tipo == "Comemorativa" and not incluir_comemorativas:
                continue
            resultado.append(ev)

        # 2. Estaduais (apenas da UF consultada)
        if uf:
            uf_clean = uf.upper().strip()
            resultado.extend(self.estaduais.get(uf_clean, []))

        # 3. Municipais (apenas do município consultado via IBGE)
        if ibge:
            resultado.extend(self.municipais.get(ibge, []))

        if apenas_bancarios:
            resultado = [ev for ev in resultado if ev.bancario]

        resultado.sort(key=lambda ev: (ev.data, ev.nome))
        return resultado

    def is_feriado(
        self,
        data_consulta: date,
        uf: Optional[str] = None,
        ibge: Optional[int] = None,
        apenas_bancarios: bool = False,
    ) -> Optional[EventoFeriado]:
        """Verifica se uma data específica é feriado na localidade informada.
        
        Retorna o primeiro EventoFeriado correspondente ou None.
        """
        feriados = self.obter_feriados(uf=uf, ibge=ibge, apenas_bancarios=apenas_bancarios)
        for ev in feriados:
            if ev.data == data_consulta:
                return ev
        return None

    def proximos_feriados(
        self,
        data_inicio: date,
        limite: int = 5,
        uf: Optional[str] = None,
        ibge: Optional[int] = None,
        apenas_bancarios: bool = False,
    ) -> List[EventoFeriado]:
        """Retorna os próximos N feriados a partir de uma data de corte."""
        feriados = self.obter_feriados(uf=uf, ibge=ibge, apenas_bancarios=apenas_bancarios)
        futuros = [ev for ev in feriados if ev.data >= data_inicio]
        return futuros[:limite]


def demonstracao() -> None:
    """Executa demonstração interativa de consultas usando a classe CalendarioFeriados."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        use_rich = True
        console = Console()
    except ImportError:
        use_rich = False
        console = None

    print("\n" + "=" * 70)
    print("  MINI-PROJETO: EXEMPLO DE CONSUMO DA BASE DE FERIADOS BRASIL")
    print("=" * 70 + "\n")

    calendario = CalendarioFeriados()

    # --- Cenário 1: Calendário consolidado de São Paulo (SP) ---
    cidade_sp = "São Paulo (SP)"
    ibge_sp = 3550308
    uf_sp = "SP"

    feriados_sp = calendario.obter_feriados(
        uf=uf_sp,
        ibge=ibge_sp,
        incluir_facultativos=True,
        incluir_comemorativas=False,
    )

    if use_rich:
        table = Table(
            title=f"Feriados Aplicáveis a {cidade_sp} em 2026 (Nacional + Estadual SP + Municipal)",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Data", style="cyan", width=12)
        table.add_column("Nome do Feriado", style="bold white")
        table.add_column("Esfera / Tipo", style="green", width=14)
        table.add_column("Bancário?", justify="center", width=10)

        for ev in feriados_sp:
            bancario_badge = "[bold green]Sim[/]" if ev.bancario else "[dim]Não[/]"
            table.add_row(ev.dia_str, ev.nome, ev.tipo, bancario_badge)

        console.print(table)
    else:
        print(f"Feriados aplicáveis a {cidade_sp} em 2026:")
        for ev in feriados_sp:
            banc = "Sim" if ev.bancario else "Não"
            print(f"  {ev.dia_str} | {ev.nome:<35} | {ev.tipo:<12} | Bancário: {banc}")

    # --- Cenário 2: Checagem pontual de datas ---
    datas_teste = [
        (date(2026, 1, 25), "Aniversário de São Paulo"),
        (date(2026, 2, 17), "Terça-feira de Carnaval"),
        (date(2026, 7, 9), "Revolução Constitucionalista"),
        (date(2026, 8, 12), "Dia Útil Comum (Quarta-feira)"),
    ]

    print("\n" + "-" * 70)
    print("  CONSULTA PONTUAL: 'A data é feriado em São Paulo/SP?'")
    print("-" * 70)

    for dt, rotulo in datas_teste:
        evento = calendario.is_feriado(dt, uf=uf_sp, ibge=ibge_sp)
        dt_str = dt.strftime("%d/%m/%Y")
        if evento:
            banc = "com fechamento bancário" if evento.bancario else "sem fechamento bancário"
            print(f"  [✓] {dt_str} ({rotulo}): FERIADO! -> {evento.nome} ({evento.tipo}, {banc})")
        else:
            print(f"  [ ] {dt_str} ({rotulo}): DIA NORMAL / ÚTIL.")

    # --- Cenário 3: Próximos feriados a partir de Maio/2026 em Belo Horizonte (MG) ---
    print("\n" + "-" * 70)
    print("  PRÓXIMOS FERIADOS: Belo Horizonte (MG) a partir de 01/05/2026")
    print("-" * 70)

    proximos_bh = calendario.proximos_feriados(
        data_inicio=date(2026, 5, 1),
        limite=6,
        uf="MG",
        ibge=3106200,
    )

    for ev in proximos_bh:
        print(f"  • {ev.dia_str} - {ev.nome} ({ev.tipo})")

    print("\n" + "=" * 70)
    print("  Demonstração concluída com sucesso!")
    print("  Consulte 'examples/README.md' para mais detalhes de integração.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    demonstracao()
