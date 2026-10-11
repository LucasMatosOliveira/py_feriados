"""Gerenciador de checkpoint atômico para garantir retomada e idempotência."""

import json
import logging
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Gerencia o progresso da coleta de feriados com escrita atômica."""

    def __init__(self, checkpoint_path: Path):
        self.path = checkpoint_path
        self.federal_done: bool = False
        self.states_done: Set[str] = set()
        self.cities_done: Set[int] = set()
        self._load()

    def _load(self) -> None:
        """Carrega o estado a partir do arquivo JSON de checkpoint, se existir."""
        if not self.path.exists():
            return

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.federal_done = bool(data.get("federal_done", False))
            self.states_done = set(data.get("states_done", []))
            self.cities_done = set(data.get("cities_done", []))
            logger.info(
                "Checkpoint carregado: federal=%s, %d UFs, %d cidades concluídas.",
                self.federal_done,
                len(self.states_done),
                len(self.cities_done),
            )
        except Exception as e:
            logger.warning("Falha ao ler checkpoint (%s). Começando do zero.", e)

    def save(self) -> None:
        """Grava o estado no disco usando gravação atômica (temp + rename)."""
        temp_path = self.path.with_suffix(".tmp")
        payload = {
            "federal_done": self.federal_done,
            "states_done": sorted(list(self.states_done)),
            "cities_done": sorted(list(self.cities_done)),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            temp_path.replace(self.path)
        except Exception as e:
            logger.error("Erro ao salvar checkpoint em %s: %s", self.path, e)

    def mark_federal_done(self) -> None:
        self.federal_done = True
        self.save()

    def mark_state_done(self, uf: str) -> None:
        self.states_done.add(uf.upper())
        self.save()

    def mark_city_done(self, ibge: int) -> None:
        self.cities_done.add(ibge)
        # Salva em lote para evitar I/O excessivo
        if len(self.cities_done) % 10 == 0:
            self.save()

    def is_federal_done(self) -> bool:
        return self.federal_done

    def is_state_done(self, uf: str) -> bool:
        return uf.upper() in self.states_done

    def is_city_done(self, ibge: int) -> bool:
        return ibge in self.cities_done

    def reset(self) -> None:
        """Limpa o progresso."""
        self.federal_done = False
        self.states_done.clear()
        self.cities_done.clear()
        if self.path.exists():
            self.path.unlink()
