"""Configuração da cidade padrão e cache de coordenadas."""
import json
from pathlib import Path

import clima

CACHE_PADRAO = Path(__file__).parent / "cidade_cache.json"


def resolver_coordenadas(cidade, cache_path=CACHE_PADRAO):
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())

    if cidade in cache:
        return cache[cidade]["lat"], cache[cidade]["lon"]

    lat, lon = clima.geocode_cidade(cidade)
    cache[cidade] = {"lat": lat, "lon": lon}
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    return lat, lon
