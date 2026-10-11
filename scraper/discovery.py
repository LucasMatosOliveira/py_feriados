"""Módulo de descoberta e listagem dos 5.570 municípios do Brasil."""

import json
import logging
from pathlib import Path
from typing import Optional
import urllib.request
import xml.etree.ElementTree as ET

from .config import Config
from .models import Municipio

logger = logging.getLogger(__name__)

IBGE_API_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
SITEMAP_INDEX_URL = "https://feriadosapi.com/sitemap.xml"


def fetch_municipios_ibge(timeout: float = 15.0) -> list[Municipio]:
    """Busca a lista oficial dos 5.570 municípios diretamente da API do IBGE."""
    import requests
    resp = requests.get(
        IBGE_API_URL,
        headers={"User-Agent": Config.user_agent, "Accept": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()

    uf_map = {
        11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
        21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA",
        31: "MG", 32: "ES", 33: "RJ", 35: "SP",
        41: "PR", 42: "SC", 43: "RS",
        50: "MS", 51: "MT", 52: "GO", 53: "DF",
    }
    municipios: list[Municipio] = []
    for item in data:
        ibge_id = int(item["id"])
        nome = item["nome"]
        uf = None
        if item.get("microrregiao") and item["microrregiao"].get("mesorregiao") and item["microrregiao"]["mesorregiao"].get("UF"):
            uf = item["microrregiao"]["mesorregiao"]["UF"].get("sigla")
        if not uf and item.get("regiao-imediata") and item["regiao-imediata"].get("regiao-intermediaria") and item["regiao-imediata"]["regiao-intermediaria"].get("UF"):
            uf = item["regiao-imediata"]["regiao-intermediaria"]["UF"].get("sigla")
        if not uf:
            uf = uf_map.get(ibge_id // 100000)
        if uf:
            municipios.append(Municipio(ibge=ibge_id, nome=nome, uf=uf))

    return municipios

def fetch_municipios_from_sitemaps(timeout: float = 15.0) -> list[Municipio]:
    """Fallback: descobre municípios inspecionando os sitemaps da feriadosapi.com."""
    req = urllib.request.Request(
        SITEMAP_INDEX_URL,
        headers={"User-Agent": Config.user_agent},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        tree = ET.fromstring(resp.read())

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    municipios_map: dict[int, Municipio] = {}

    for sitemap in tree.findall("sm:sitemap", ns):
        loc = sitemap.find("sm:loc", ns)
        if loc is None or not loc.text:
            continue
        url = loc.text
        # ex: https://feriadosapi.com/sitemap/MG.xml
        if not url.endswith("main.xml"):
            try:
                sub_req = urllib.request.Request(
                    url,
                    headers={"User-Agent": Config.user_agent},
                )
                with urllib.request.urlopen(sub_req, timeout=timeout) as sub_resp:
                    sub_tree = ET.fromstring(sub_resp.read())
                for url_tag in sub_tree.findall("sm:url", ns):
                    loc_tag = url_tag.find("sm:loc", ns)
                    if loc_tag is not None and loc_tag.text:
                        parts = loc_tag.text.rstrip("/").split("/")
                        # Formato: .../calendario/2026/MG/3127701
                        if len(parts) >= 3 and parts[-1].isdigit():
                            ibge = int(parts[-1])
                            uf = parts[-2]
                            if ibge not in municipios_map:
                                municipios_map[ibge] = Municipio(ibge=ibge, nome=f"IBGE {ibge}", uf=uf)
            except Exception as e:
                logger.warning("Falha ao ler sitemap %s: %s", url, e)

    return list(municipios_map.values())


def get_municipios(
    uf_filter: Optional[str] = None,
    use_cache: bool = True,
    cache_path: Optional[Path] = None,
) -> list[Municipio]:
    """Retorna a lista ordenada de municípios do Brasil, com suporte a cache e filtro de UF."""
    if cache_path is None:
        cache_path = Path(Config.cache_dir) / "municipios.json"

    municipios: list[Municipio] = []

    if use_cache and cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
            municipios = [Municipio(**item) for item in raw_list]
            logger.info("Carregados %d municípios do cache local.", len(municipios))
        except Exception as e:
            logger.warning("Erro ao ler cache local de municípios (%s). Recarregando...", e)

    if not municipios:
        try:
            logger.info("Buscando municípios da API do IBGE...")
            municipios = fetch_municipios_ibge()
        except Exception as e:
            logger.warning("Erro ao obter do IBGE (%s). Tentando via sitemaps...", e)
            municipios = fetch_municipios_from_sitemaps()

        if municipios and use_cache:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump([{"ibge": m.ibge, "nome": m.nome, "uf": m.uf} for m in municipios], f, ensure_ascii=False)
            logger.info("Salvos %d municípios no cache local: %s", len(municipios), cache_path)

    # Ordenar por UF e Nome
    municipios.sort(key=lambda m: (m.uf, m.nome))

    if uf_filter:
        uf_clean = uf_filter.upper().strip()
        municipios = [m for m in municipios if m.uf == uf_clean]

    return municipios
