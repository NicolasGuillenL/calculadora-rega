import json
from unittest.mock import patch

import config


def test_resolver_coordenadas_usa_cache_quando_disponivel(tmp_path):
    cache_path = tmp_path / "cidade_cache.json"
    cache_path.write_text(json.dumps({"Sao Paulo, SP": {"lat": -23.55, "lon": -46.63}}))

    with patch("config.clima.geocode_cidade") as mock_geocode:
        lat, lon = config.resolver_coordenadas("Sao Paulo, SP", cache_path=cache_path)

    assert (lat, lon) == (-23.55, -46.63)
    mock_geocode.assert_not_called()


def test_resolver_coordenadas_busca_e_grava_cache_quando_ausente(tmp_path):
    cache_path = tmp_path / "cidade_cache.json"

    with patch("config.clima.geocode_cidade", return_value=(-22.9, -43.2)) as mock_geocode:
        lat, lon = config.resolver_coordenadas("Rio de Janeiro, RJ", cache_path=cache_path)

    assert (lat, lon) == (-22.9, -43.2)
    mock_geocode.assert_called_once_with("Rio de Janeiro, RJ")

    cache_salvo = json.loads(cache_path.read_text())
    assert cache_salvo["Rio de Janeiro, RJ"] == {"lat": -22.9, "lon": -43.2}
