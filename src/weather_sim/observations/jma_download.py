"""Download date-matched JMA AMeDAS verification observations."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from weather_sim.config.models import ExperimentConfig
from weather_sim.errors import ObservationDataError
from weather_sim.network import open_trusted_url
from weather_sim.observations.jma_amedas import parse_jma_amedas_10min_html

JMA_TEN_MINUTE_URL = "https://www.data.jma.go.jp/stats/etrn/view/10min_a1.php"


def download_fuchu_amedas(config: ExperimentConfig, data_root: Path, output_path: Path) -> Path:
    """Download Fuchu daily tables covering the requested analysis period."""
    zone = ZoneInfo(config.time.timezone_name)
    first_day = config.time.target_start.astimezone(zone).date()
    last_day = config.time.target_end.astimezone(zone).date()
    frames: list[pd.DataFrame] = []
    day = first_day
    while day <= last_day:
        parameters = urllib.parse.urlencode(
            {
                "prec_no": "44",
                "block_no": "1133",
                "year": day.year,
                "month": day.month,
                "day": day.day,
                "view": "",
            }
        )
        url = f"{JMA_TEN_MINUTE_URL}?{parameters}"
        html_path = data_root / f"fuchu_{day:%Y%m%d}_10min.html"
        if html_path.is_file() and html_path.stat().st_size:
            html = html_path.read_text(encoding="utf-8")
        else:
            request = urllib.request.Request(url, headers={"User-Agent": "weather-sim/0.1"})
            try:
                with open_trusted_url(request, timeout=60) as response:
                    html = response.read().decode("utf-8")
            except (OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
                raise ObservationDataError(f"could not download Fuchu AMeDAS for {day}: {exc}") from exc
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html, encoding="utf-8")
        frames.append(
            parse_jma_amedas_10min_html(
                html,
                observation_date=day,
                station_id="amedas_fuchu",
                latitude=35 + 41.0 / 60,
                longitude=139 + 29.0 / 60,
                elevation_m=59,
                timezone_name=config.time.timezone_name,
            )
        )
        day += timedelta(days=1)

    observations = pd.concat(frames, ignore_index=True)
    start = pd.Timestamp(config.time.target_start_utc)
    end = pd.Timestamp(config.time.target_end_utc)
    observations = observations.loc[
        (observations["timestamp"] >= start) & (observations["timestamp"] <= end)
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    observations.to_csv(output_path, index=False)
    return output_path
