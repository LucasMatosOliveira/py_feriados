"""Modelos de dados tipados para municípios e eventos de feriado."""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class Municipio:
    ibge: int
    nome: str
    uf: str


@dataclass
class FeriadoRecord:
    uf: Optional[str]
    ibge: Optional[int]
    cidade: Optional[str]
    tipo: str  # "Nacional", "Estadual", "Municipal", "Facultativo", "Comemorativa"
    dia: str  # "DD/MM/YYYY"
    dia_iso: str  # "YYYY-MM-DD"
    nome: str
    bancario: bool = False
    descricao: Optional[str] = None

    @classmethod
    def from_raw(
        cls,
        raw: dict[str, Any],
        tipo_padronizado: str,
        uf: Optional[str] = None,
        ibge: Optional[int] = None,
        cidade: Optional[str] = None,
    ) -> "FeriadoRecord":
        """Cria um FeriadoRecord a partir do payload bruto da feriadosapi."""
        data_str = raw.get("data", "")
        dia_iso = ""
        dia_fmt = data_str
        
        # Converte DD/MM/YYYY para YYYY-MM-DD
        if "/" in data_str:
            try:
                dt = datetime.strptime(data_str, "%d/%m/%Y")
                dia_iso = dt.strftime("%Y-%m-%d")
                dia_fmt = dt.strftime("%d/%m/%Y")
            except ValueError:
                dia_iso = data_str
        elif "-" in data_str:
            try:
                dt = datetime.strptime(data_str, "%Y-%m-%d")
                dia_iso = dt.strftime("%Y-%m-%d")
                dia_fmt = dt.strftime("%d/%m/%Y")
            except ValueError:
                dia_iso = data_str

        return cls(
            uf=uf,
            ibge=ibge,
            cidade=cidade,
            tipo=tipo_padronizado,
            dia=dia_fmt,
            dia_iso=dia_iso,
            nome=raw.get("nome", "").strip(),
            bancario=bool(raw.get("bancario", False)),
            descricao=raw.get("descricao") or None,
        )

    def to_dict(self, include_descricao: bool = False) -> dict[str, Any]:
        """Serializa para dicionário compatível com o formato JSONL."""
        data = {
            "uf": self.uf,
            "ibge": self.ibge,
            "cidade": self.cidade,
            "tipo": self.tipo,
            "dia": self.dia,
            "dia_iso": self.dia_iso,
            "nome": self.nome,
            "bancario": self.bancario,
        }
        if include_descricao and self.descricao:
            data["descricao"] = self.descricao
        return data
