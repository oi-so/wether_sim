from datetime import date

from weather_sim.observations.jma_amedas import parse_jma_amedas_10min_html
from weather_sim.observations.school_wsn import read_school_wsn


def test_school_wsn_reader_uses_positionally_known_cp932_columns() -> None:
    result = read_school_wsn(
        ["data/observations/school/WSNLOG260901000100.csv"],
        latitude=35.69247912845154, longitude=139.41296806119965,
    )
    first_temperature = result[result["variable"] == "temperature"].iloc[0]
    assert str(first_temperature["timestamp"]) == "2026-08-31 15:01:00+00:00"
    assert first_temperature["value"] == 23.8


def test_jma_amedas_parser() -> None:
    html = '''<table id="tablefix1"><tr class="mtx"><td>15:10</td><td>0.0</td><td>31.2</td><td>55</td><td>2.1</td><td>南</td><td>4.0</td><td>南南西</td><td>10</td></tr></table>'''
    result = parse_jma_amedas_10min_html(
        html, observation_date=date(2026, 9, 1), station_id="fuchu",
        latitude=35.6833, longitude=139.4833, elevation_m=59,
    )
    temperature = result[result["variable"] == "temperature"].iloc[0]
    assert temperature["value"] == 31.2
    assert str(temperature["timestamp"]) == "2026-09-01 06:10:00+00:00"
