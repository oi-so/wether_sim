"""Prepare the supplied school logs and downloaded Fuchu AMeDAS table."""

from datetime import date
from pathlib import Path

import pandas as pd

from weather_sim.observations import parse_jma_amedas_10min_html, read_school_wsn

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    school = read_school_wsn(
        sorted((ROOT / "data/observations/school").glob("WSNLOG26090*.csv")),
        latitude=35.69247912845154,
        longitude=139.41296806119965,
        elevation_m=None,
    )
    amedas_path = ROOT / "data/observations/amedas/fuchu_20260901_10min.html"
    amedas = parse_jma_amedas_10min_html(
        amedas_path.read_text(encoding="utf-8"),
        observation_date=date(2026, 9, 1), station_id="amedas_fuchu",
        latitude=35 + 41.0 / 60, longitude=139 + 29.0 / 60, elevation_m=59,
    )
    combined = pd.concat([school, amedas], ignore_index=True)
    output = ROOT / "data/observations/case_20260901.csv"
    combined.to_csv(output, index=False)
    print(f"wrote {len(combined)} rows to {output}")


if __name__ == "__main__":
    main()
