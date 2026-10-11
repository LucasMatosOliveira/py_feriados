"""Orquestrador de coleta hierárquica e deduplicada de feriados."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from pathlib import Path
import threading
from typing import Callable, Optional

from .checkpoint import CheckpointManager
from .client import FeriadosClient
from .config import Config
from .models import FeriadoRecord, Municipio

logger = logging.getLogger(__name__)

# As 27 Unidades Federativas do Brasil
TODAS_UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
    "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
    "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
]


class HolidayCollector:
    """Orquestrador da coleta em 3 níveis hierárquicos: Federal -> Estadual -> Municipal."""

    def __init__(
        self,
        ano: int = Config.ano_default,
        config: Optional[Config] = None,
        output_path: Optional[Path] = None,
        checkpoint_path: Optional[Path] = None,
    ):
        self.ano = ano
        self.config = config or Config()
        
        out_name = self.config.output_jsonl.format(ano=self.ano)
        self.output_path = output_path or Path(out_name)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        ck_name = self.config.checkpoint_file.format(ano=self.ano)
        self.checkpoint = CheckpointManager(checkpoint_path or Path(ck_name))
        
        self.client = FeriadosClient(self.config)
        self._file_lock = threading.Lock()

    def _append_record(self, record: FeriadoRecord) -> None:
        """Escreve um registro FeriadoRecord no JSONL de forma thread-safe."""
        line = json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
        with self._file_lock:
            with open(self.output_path, "a", encoding="utf-8") as f:
                f.write(line)

    def _append_records(self, records: list[FeriadoRecord]) -> None:
        """Escreve uma lista de FeriadoRecord no JSONL de forma thread-safe."""
        if not records:
            return
        lines = [json.dumps(r.to_dict(), ensure_ascii=False) + "\n" for r in records]
        with self._file_lock:
            with open(self.output_path, "a", encoding="utf-8") as f:
                f.writelines(lines)

    def collect_federal(self) -> int:
        """Coleta o nível Federal: feriados nacionais, facultativos federais e comemorativas (1 requisição)."""
        if self.checkpoint.is_federal_done():
            logger.info("Feriados federais do ano %d já coletados (checkpoint). Pulando...", self.ano)
            return 0

        logger.info("Coletando feriados federais, facultativos e datas comemorativas de %d...", self.ano)
        holidays, commemorative = self.client.fetch_national_page(self.ano)

        records: list[FeriadoRecord] = []
        for h in holidays:
            raw_tipo = h.get("tipo", "").upper()
            if raw_tipo == "NACIONAL":
                tipo = "Nacional"
            elif raw_tipo == "FACULTATIVO":
                tipo = "Facultativo"
            else:
                tipo = "Nacional"

            records.append(
                FeriadoRecord.from_raw(
                    raw=h,
                    tipo_padronizado=tipo,
                    uf=None,
                    ibge=None,
                    cidade=None,
                )
            )

        for c in commemorative:
            records.append(
                FeriadoRecord.from_raw(
                    raw=c,
                    tipo_padronizado="Comemorativa",
                    uf=None,
                    ibge=None,
                    cidade=None,
                )
            )

        self._append_records(records)
        self.checkpoint.mark_federal_done()
        logger.info("Gravados %d eventos federais em %s.", len(records), self.output_path)
        return len(records)

    def collect_states(self, ufs: Optional[list[str]] = None) -> int:
        """Coleta o nível Estadual: feriados específicos de cada UF (máx. 27 requisições)."""
        target_ufs = [u.upper() for u in (ufs or TODAS_UFS)]
        total_records = 0

        for uf in target_ufs:
            if self.checkpoint.is_state_done(uf):
                logger.debug("UF %s já concluída (checkpoint).", uf)
                continue

            logger.info("Buscando feriados estaduais de %s...", uf)
            raw_state_holidays = self.client.fetch_state_page(self.ano, uf)

            records = [
                FeriadoRecord.from_raw(
                    raw=h,
                    tipo_padronizado="Estadual",
                    uf=uf,
                    ibge=None,
                    cidade=None,
                )
                for h in raw_state_holidays
            ]

            if records:
                self._append_records(records)
                total_records += len(records)

            self.checkpoint.mark_state_done(uf)

        logger.info("Concluída coleta estadual. Novos registros gravados: %d.", total_records)
        return total_records

    def _process_single_city(self, mun: Municipio) -> tuple[int, int]:
        """Processa um município individual: extrai estritamente seus feriados municipais."""
        raw_items = self.client.fetch_city_page(self.ano, mun.uf, mun.ibge)
        records = [
            FeriadoRecord.from_raw(
                raw=item,
                tipo_padronizado="Municipal",
                uf=mun.uf,
                ibge=mun.ibge,
                cidade=mun.nome,
            )
            for item in raw_items
        ]
        if records:
            self._append_records(records)
        self.checkpoint.mark_city_done(mun.ibge)
        return mun.ibge, len(records)

    def collect_cities(
        self,
        municipios: list[Municipio],
        progress_callback: Optional[Callable[[Municipio, int], None]] = None,
    ) -> int:
        """Coleta o nível Municipal para a lista informada de municípios com concorrência controlada."""
        pending = [m for m in municipios if not self.checkpoint.is_city_done(m.ibge)]
        logger.info(
            "Municípios a processar: %d (já concluídos anteriormente: %d).",
            len(pending),
            len(municipios) - len(pending),
        )

        if not pending:
            return 0

        total_records = 0
        workers = min(self.config.max_workers, len(pending))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_mun = {
                executor.submit(self._process_single_city, mun): mun
                for mun in pending
            }

            for future in as_completed(future_to_mun):
                mun = future_to_mun[future]
                try:
                    ibge, count = future.result()
                    total_records += count
                    if progress_callback:
                        progress_callback(mun, count)
                except Exception as e:
                    logger.error("Erro ao coletar município %s (%s): %s", mun.nome, mun.uf, e)

        # Salva o estado final do checkpoint
        self.checkpoint.save()
        return total_records
