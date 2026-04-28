"""
etl_station_information.py
Descarga, transforma y carga la información estática de estaciones -> tabla STATIONS.

Uso:
    python etl_station_information.py [--sql-only] [--out stations.sql]
"""

import argparse
import logging
import sys
from typing import Any

import config
from fetcher import fetch_json

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# Transformación

def transform(raw: dict) -> list[dict]:
    stations_raw = (
        raw.get("data", {}).get("stations")
        or raw.get("stations")
        or []
    )
    if not stations_raw:
        log.warning("No se encontró el array de estaciones en la respuesta")

    rows = []
    skipped = 0
    for s in stations_raw:
        loc_block = s.get("location") or {}

        latitude  = s.get("lat")
        longitude = s.get("lon")
        if latitude is None or longitude is None:
            log.warning("Estación sin coordenadas ignorada: %s", s.get("station_id"))
            skipped += 1
            continue

        latitude  = float(latitude)
        longitude = float(longitude)

        # district_id / neighborhood_id son NOT NULL en el modelo
        district_id       = s.get("district_code")     or loc_block.get("district_code")     or 0
        district_name     = s.get("district_name")     or loc_block.get("district_name")     or ""
        neighborhood_id   = s.get("neighborhood_code") or loc_block.get("neighborhood_code") or 0
        neighborhood_name = s.get("neighborhood_name") or loc_block.get("neighborhood_name") or ""

        # capacity NOT NULL
        capacity = s.get("capacity")
        if capacity is None:
            log.warning("Estación %s sin capacity; se usará 0", s.get("station_id"))
            capacity = 0

        rows.append({
            "station_id":        s.get("station_id"),
            "name":              (s.get("name") or "")[:100],
            "latitude":          latitude,
            "longitude":         longitude,
            "altitude":          s.get("altitude"),              # nullable
            "capacity":          int(capacity),
            "district_id":       int(district_id),
            "district_name":     str(district_name)[:100],
            "neighborhood_id":   int(neighborhood_id),
            "neighborhood_name": str(neighborhood_name)[:100],
            "_wkt":              f"POINT({longitude} {latitude})",
        })

    log.info("Estaciones transformadas: %d  |  ignoradas: %d", len(rows), skipped)
    return rows


# SQL

def _esc(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


COLS = (
    "station_id, name, latitude, longitude, altitude, capacity, "
    "district_id, district_name, neighborhood_id, neighborhood_name, location"
)

UPDATE_CLAUSE = (
    "name=VALUES(name), latitude=VALUES(latitude), longitude=VALUES(longitude), "
    "altitude=VALUES(altitude), capacity=VALUES(capacity), "
    "district_id=VALUES(district_id), district_name=VALUES(district_name), "
    "neighborhood_id=VALUES(neighborhood_id), neighborhood_name=VALUES(neighborhood_name), "
    "location=VALUES(location)"
)


def to_sql(rows: list[dict]) -> str:
    lines = ["USE bicing;", ""]
    for r in rows:
        lines.append(
            f"INSERT INTO STATIONS ({COLS}) VALUES ("
            f"{_esc(r['station_id'])}, {_esc(r['name'])}, "
            f"{_esc(r['latitude'])}, {_esc(r['longitude'])}, "
            f"{_esc(r['altitude'])}, {_esc(r['capacity'])}, "
            f"{_esc(r['district_id'])}, {_esc(r['district_name'])}, "
            f"{_esc(r['neighborhood_id'])}, {_esc(r['neighborhood_name'])}, "
            f"ST_GeomFromText({_esc(r['_wkt'])}, 4326)"
            f") ON DUPLICATE KEY UPDATE {UPDATE_CLAUSE};"
        )
    return "\n".join(lines)



# Carga MySQL

def load_to_mysql(rows: list[dict]) -> None:
    try:
        import mysql.connector
    except ImportError:
        log.error("Instala mysql-connector-python")
        sys.exit(1)

    sql = (
        f"INSERT INTO STATIONS ({COLS}) VALUES "
        "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, ST_GeomFromText(%s,4326)) "
        f"ON DUPLICATE KEY UPDATE {UPDATE_CLAUSE}"
    )
    params = [
        (r["station_id"], r["name"], r["latitude"], r["longitude"],
         r["altitude"], r["capacity"],
         r["district_id"], r["district_name"],
         r["neighborhood_id"], r["neighborhood_name"],
         r["_wkt"])
        for r in rows
    ]
    conn = mysql.connector.connect(**config.DB)
    cur  = conn.cursor()
    cur.executemany(sql, params)
    conn.commit()
    log.info("STATIONS: %d filas insertadas/actualizadas", cur.rowcount)
    cur.close()
    conn.close()


# Main

def main():
    parser = argparse.ArgumentParser(description="ETL → STATIONS")
    parser.add_argument("--sql-only", action="store_true")
    parser.add_argument("--out", default="stations.sql")
    args = parser.parse_args()

    raw  = fetch_json(config.URL_INFO, config.TOKEN)
    rows = transform(raw)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(to_sql(rows))
    log.info("SQL → %s", args.out)

    if not args.sql_only:
        load_to_mysql(rows)


if __name__ == "__main__":
    main()