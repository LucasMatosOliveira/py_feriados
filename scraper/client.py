"""Cliente HTTP com rate limiting adaptativo, retry e extração de chunks RSC."""

import json
import logging
import re
import threading
import time
from typing import Any, Optional
import urllib.parse

import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from .config import Config

logger = logging.getLogger(__name__)


class RateLimiter:
    """Controlador de taxa thread-safe para respeitar os limites da Vercel."""

    def __init__(self, min_interval: float = 0.45):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_request_time = 0.0

    def wait(self) -> None:
        """Bloqueia até que o intervalo mínimo desde a última requisição tenha passado."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request_time = time.monotonic()

    def handle_response_headers(self, headers: dict[str, Any]) -> None:
        """Ajusta o ritmo caso o servidor reporte limite baixo de requisições restantes."""
        remaining = headers.get("x-ratelimit-remaining")
        if remaining is not None:
            try:
                rem_val = int(remaining)
                if rem_val <= 2:
                    logger.warning("Rate limit crítico (%d restantes). Desacelerando...", rem_val)
                    time.sleep(4.0)
                elif rem_val <= 5:
                    time.sleep(1.5)
            except (ValueError, TypeError):
                pass


def extract_rsc_prop_array(html: str, prop_name: str) -> list[dict[str, Any]]:
    """Extrai arrays serializados dentro de chunks RSC do Next.js (ex: holidays, commemorativeDates).
    
    Muito mais rápido e leve do que analisar o DOM HTML inteiro via BeautifulSoup.
    """
    # Procura por "prop_name":[ ou \"prop_name\":[
    needles = [f'"{prop_name}":[', f'\\"{prop_name}\\":[']
    idx = -1
    for needle in needles:
        idx = html.find(needle)
        if idx != -1:
            break

    if idx == -1:
        return []

    start = html.find("[", idx)
    if start == -1:
        return []

    # Procura o colchete de fechamento correspondente respeitando strings e escapes
    depth = 0
    in_quote = False
    escape = False
    end = -1
    html_len = len(html)

    for i in range(start, html_len):
        c = html[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_quote = not in_quote
            continue
        if not in_quote:
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

    if end == -1:
        return []

    raw_slice = html[start:end]
    # Limpa escapes de string do Javascript
    cleaned = raw_slice.replace(r'\"', '"').replace(r"\\", "\\")

    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except Exception as e:
        logger.debug("Falha no parse JSON de %s: %s", prop_name, e)

    return []


def extract_fallback_ldjson(html: str) -> list[dict[str, Any]]:
    """Fallback: extrai eventos da tag <script type=\"application/ld+json\"> ItemList."""
    scripts = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    events: list[dict[str, Any]] = []

    for s in scripts:
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict) and parsed.get("@type") == "ItemList":
                for item in parsed.get("itemListElement", []):
                    ev = item.get("item", {})
                    if ev.get("@type") == "Event":
                        desc = ev.get("description", "")
                        tipo = "MUNICIPAL"
                        if "National holiday" in desc:
                            tipo = "NACIONAL"
                        elif "State holiday" in desc:
                            tipo = "ESTADUAL"

                        # Extrai data YYYY-MM-DD -> DD/MM/YYYY
                        start_date = ev.get("startDate", "")
                        data_fmt = start_date
                        if "-" in start_date:
                            parts = start_date.split("-")
                            if len(parts) == 3:
                                data_fmt = f"{parts[2]}/{parts[1]}/{parts[0]}"

                        events.append({
                            "data": data_fmt,
                            "nome": ev.get("name", ""),
                            "tipo": tipo,
                            "descricao": desc,
                            "bancario": False,
                        })
        except Exception:
            continue

    return events


class FeriadosClient:
    """Cliente HTTP com conexão persistente, retry exponencial e throttling."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.rate_limiter = RateLimiter(min_interval=self.config.min_request_interval)
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        })

        # Configura retries com backoff no nível do urllib3
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get_html(self, url: str) -> str:
        """Executa um GET com controle de taxa e retry manual caso o status seja 429."""
        attempts = 0
        max_attempts = self.config.max_retries + 1

        while attempts < max_attempts:
            attempts += 1
            self.rate_limiter.wait()

            try:
                resp = self.session.get(url, timeout=self.config.request_timeout)
                self.rate_limiter.handle_response_headers(resp.headers)

                if resp.status_code == 200:
                    return resp.text
                
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    sleep_time = float(retry_after) if retry_after else (2.0 ** attempts) * 3.0
                    logger.warning("HTTP 429 em %s. Aguardando %.1fs antes da tentativa %d...", url, sleep_time, attempts)
                    time.sleep(sleep_time)
                    continue

                if resp.status_code == 404:
                    logger.debug("Página não encontrada (404): %s", url)
                    return ""

                resp.raise_for_status()

            except (requests.RequestException, Exception) as e:
                if attempts >= max_attempts:
                    logger.error("Falha definitiva ao requisitar %s: %s", url, e)
                    raise
                sleep_time = (2.0 ** attempts) * 1.5
                logger.warning("Erro de rede em %s (%s). Aguardando %.1fs...", url, e, sleep_time)
                time.sleep(sleep_time)

        return ""

    def fetch_national_page(self, ano: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Busca a página de feriados nacionais do ano."""
        url = f"{self.config.base_url}/calendario/{ano}"
        html = self.get_html(url)
        if not html:
            return [], []

        holidays = extract_rsc_prop_array(html, "holidays")
        commemorative = extract_rsc_prop_array(html, "commemorativeDates")

        if not holidays:
            holidays = extract_fallback_ldjson(html)

        return holidays, commemorative

    def fetch_state_page(self, ano: int, uf: str) -> list[dict[str, Any]]:
        """Busca a página de feriados estaduais do estado (UF)."""
        url = f"{self.config.base_url}/calendario/{ano}/{uf.upper()}"
        html = self.get_html(url)
        if not html:
            return []

        holidays = extract_rsc_prop_array(html, "holidays")
        if not holidays:
            holidays = extract_fallback_ldjson(html)

        # Filtra apenas o que é estadual
        return [h for h in holidays if h.get("tipo") == "ESTADUAL"]

    def fetch_city_page(self, ano: int, uf: str, ibge: int) -> list[dict[str, Any]]:
        """Busca a página do município e extrai os feriados municipais específicos."""
        url = f"{self.config.base_url}/calendario/{ano}/{uf.upper()}/{ibge}"
        html = self.get_html(url)
        if not html:
            return []

        holidays = extract_rsc_prop_array(html, "holidays")
        if not holidays:
            holidays = extract_fallback_ldjson(html)

        # Filtra apenas o que é estritamente municipal
        return [h for h in holidays if h.get("tipo") == "MUNICIPAL"]
