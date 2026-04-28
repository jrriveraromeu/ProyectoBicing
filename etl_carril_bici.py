"""
Descarga, transforma y carga el GeoJSON de carrils bici -> tabla BIKE_LANES.

Uso:
    python etl_carril_bici.py [--sql-only] [--out bike_lanes.sql]
                              [--local path/al/archivo.geojson]
"""

import argparse
import json
import logging
import sys
from typing import Any

import config
from fetcher import fetch_json

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# WKT helpers

def _linestring_wkt(coords: list) -> str:
    return "LINESTRING(" + ", ".join(f"{c[0]} {c[1]}" for c in coords) + ")"


def _esc(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


# Transformación

def transform(geojson: dict) -> list[dict]:
    """
    Mapeo de campos GeoJSON -> BIKE_LANES:
      TIPUS      -> lane_type   VARCHAR(50)   nullable
      NOM_CARRER -> lane_name   VARCHAR(100)  nullable
      geometry   -> geometry    LINESTRING    NOT NULL
    lane_id lo asigna MySQL (AUTO_INCREMENT).
    """
    rows = []
    skipped = 0

    for feat in geojson.get("features", []):
        props  = feat.get("properties") or {}
        geom   = feat.get("geometry")   or {}
        g_type = geom.get("type", "")
        coords = geom.get("coordinates") or []

        lane_type = props.get("TIPUS")      or props.get("tipus")
        lane_name = props.get("NOM_CARRER") or props.get("nom_carrer")

        # Truncar a los VARCHAR definidos
        if lane_type: lane_type = lane_type[:50]
        if lane_name: lane_name = lane_name[:100]

        base = {"lane_type": lane_type, "lane_name": lane_name}

        if g_type == "LineString":
            rows.append({**base, "_wkt": _linestring_wkt(coords)})

        elif g_type == "MultiLineString":
            for seg in coords:
                rows.append({**base, "_wkt": _linestring_wkt(seg)})

        else:
            skipped += 1
            log.debug("Geometría ignorada: %s", g_type)

    log.info("Segmentos transformados: %d  |  ignorados: %d", len(rows), skipped)
    return rows


# SQL

COLS = "lane_type, lane_name, geometry"


def to_sql(rows: list[dict]) -> str:
    lines = ["USE bicing;", ""]
    for r in rows:
        lines.append(
            f"INSERT INTO BIKE_LANES ({COLS}) VALUES ("
            f"{_esc(r['lane_type'])}, {_esc(r['lane_name'])}, "
            f"ST_GeomFromText({_esc(r['_wkt'])}, 4326));"
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
        f"INSERT INTO BIKE_LANES ({COLS}) VALUES "
        "(%s, %s, ST_GeomFromText(%s, 4326))"
    )
    params = [(r["lane_type"], r["lane_name"], r["_wkt"]) for r in rows]

    conn = mysql.connector.connect(**config.DB)
    cur  = conn.cursor()
    cur.executemany(sql, params)
    conn.commit()
    log.info("BIKE_LANES: %d segmentos insertados", cur.rowcount)
    cur.close()
    conn.close()


# Main

def main():
    parser = argparse.ArgumentParser(description="ETL → BIKE_LANES")
    parser.add_argument("--sql-only", action="store_true")
    parser.add_argument("--out",      default="bike_lanes.sql")
    parser.add_argument("--local",    default=None)
    args = parser.parse_args()

    if args.local:
        with open(args.local, encoding="utf-8") as f:
            geojson = json.load(f)
    else:
        geojson = fetch_json(config.URL_GEOJSON, config.TOKEN)

    rows = transform(geojson)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(to_sql(rows))
    log.info("SQL → %s", args.out)

    if not args.sql_only:
        load_to_mysql(rows)


if __name__ == "__main__":
    main()