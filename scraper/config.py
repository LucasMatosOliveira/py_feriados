"""Configurações globais do scraper de feriados."""

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    base_url: str = "https://feriadosapi.com"
    ano_default: int = 2026
    
    # Headers
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    
    # Rate Limiting & Concorrência
    # Vercel limita a 30 reqs a cada ~10-15s por IP.
    # Usamos delay adaptativo e concorrência segura (2 workers simultâneos).
    max_workers: int = 2
    min_request_interval: float = 0.45  # ~2.2 req/s garantindo margem contra o rate limit
    request_timeout: float = 15.0
    max_retries: int = 4
    backoff_factor: float = 2.0
    
    # Arquivos padrão (ancorados na raiz do projeto)
    output_jsonl: str = str(PROJECT_ROOT / "data" / "feriados_brasil_{ano}.jsonl")
    checkpoint_file: str = str(PROJECT_ROOT / "data" / ".checkpoint_{ano}.json")
    cache_dir: str = str(PROJECT_ROOT / ".cache")
