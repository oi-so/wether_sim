"""Parser for JMA's public ten-minute AMeDAS table."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

import pandas as pd

from weather_sim.errors import ObservationDataError

VARIABLES = (
    ("precipitation", "mm"), ("temperature", "degC"),
    ("relative_humidity", "%"), ("wind_speed", "m/s"),
    ("wind_direction_text", "text"), ("wind_gust", "m/s"),
    ("wind_gust_direction_text", "text"), ("sunshine_duration", "min"),
)


class _AmedasTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_cell = False
        self.row: list[str] | None = None
        self.cell_parts: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") == "tablefix1":
            self.in_table = True
        elif self.in_table and tag == "tr":
            self.row = []
        elif self.in_table and self.row is not None and tag == "td":
            self.in_cell = True
            self.cell_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.in_cell and self.row is not None:
            self.row.append("".join(self.cell_parts).strip())
            self.in_cell = False
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.in_table:
            self.in_table = False


def _number(text: str) -> tuple[float | None, str]:
    if not text or text in {"///", "--", "×"}:
        return None, "missing"
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None, "missing"
    quality = "estimated" if ")" in text or "]" in text else "valid"
    return float(match.group()), quality


def parse_jma_amedas_10min_html(
    html: str, *, observation_date: date, station_id: str,
    latitude: float, longitude: float, elevation_m: float,
    timezone_name: str = "Asia/Tokyo",
) -> pd.DataFrame:
    parser = _AmedasTableParser()
    parser.feed(html)
    records: list[dict[str, object]] = []
    for row in parser.rows:
        if len(row) != 9 or not re.fullmatch(r"\d{2}:\d{2}", row[0]):
            continue
        hour, minute = (int(value) for value in row[0].split(":"))
        local_date = observation_date
        if hour == 24:
            hour = 0
            local_date += timedelta(days=1)
        timestamp = pd.Timestamp(datetime.combine(local_date, datetime.min.time()).replace(hour=hour, minute=minute))
        timestamp = timestamp.tz_localize(timezone_name).tz_convert("UTC")
        for value_text, (variable, unit) in zip(row[1:], VARIABLES, strict=True):
            if unit == "text":
                value: object = value_text or None
                quality = "valid" if value else "missing"
            else:
                value, quality = _number(value_text)
            records.append({
                "timestamp": timestamp, "station_id": station_id,
                "latitude": latitude, "longitude": longitude, "elevation_m": elevation_m,
                "variable": variable, "value": value, "unit": unit,
                "quality": quality, "source": "jma_amedas",
            })
    if not records:
        raise ObservationDataError("no ten-minute observation rows found in JMA HTML")
    return pd.DataFrame.from_records(records)
