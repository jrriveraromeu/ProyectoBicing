"""
etl_station_status.py
Descarga, transforma y carga snapshots de estado -> tabla STATION_STATUS.


Uso:
    python etl_station_status.py [--sql-only] [--out status.sql]
                                 [--csv-out status.csv] [--batch-size N]
"""

import argparse
import csv
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any

import config
from fetcher import fetch_json

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Helpers

# Convierte timestamp epoch a formato datetime compatible con MySQL (UTC)
def epoch_to_dt(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _esc(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


# Transformación

def transform(raw: dict) -> list[dict]:
    ts_global = raw.get("last_updated") or time.time()
    stations_raw = (
        raw.get("data", {}).get("stations")
        or raw.get("stations")
        or []
    )

    rows = []
    for s in stations_raw:
        types = s.get("num_bikes_available_types") or {}
        ts    = s.get("last_reported") or ts_global

        # is_operative: TRUE si la estación está instalada, dando y recibiendo bicis
        is_installed = bool(s.get("is_installed", 0))
        is_renting   = bool(s.get("is_renting",   0))
        is_returning = bool(s.get("is_returning",  0))
        is_operative = is_installed and is_renting and is_returning

        rows.append({
            "station_id":       s.get("station_id"),
            "recorded_at":      epoch_to_dt(ts),
            "bikes_available":  int(s.get("num_bikes_available",  0) or 0),
            "docks_available":  int(s.get("num_docks_available",  0) or 0),
            "mechanical_bikes": int(types.get("mechanical",       0) or 0),
            "electrical_bikes": int(types.get("ebike",            0) or 0),
            "is_operative":     int(is_operative),              # BOOLEAN → 0/1
        })

    log.info("Registros de estado transformados: %d", len(rows))
    return rows


# SQL (INSERT por lotes; ON DUPLICATE KEY UPDATE para "re-ejecuciones" seguras)

COLS = (
    "station_id, recorded_at, bikes_available, docks_available, "
    "mechanical_bikes, electrical_bikes, is_operative"
)

UPDATE_CLAUSE = (
    "bikes_available=VALUES(bikes_available), "
    "docks_available=VALUES(docks_available), "
    "mechanical_bikes=VALUES(mechanical_bikes), "
    "electrical_bikes=VALUES(electrical_bikes), "
    "is_operative=VALUES(is_operative)"
)


def to_sql(rows: list[dict], batch_size: int) -> str:
    lines = ["USE bicing;", ""]
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        vals = [
            f"({_esc(r['station_id'])}, {_esc(r['recorded_at'])}, "
            f"{_esc(r['bikes_available'])}, {_esc(r['docks_available'])}, "
            f"{_esc(r['mechanical_bikes'])}, {_esc(r['electrical_bikes'])}, "
            f"{_esc(r['is_operative'])})"
            for r in chunk
        ]
        lines.append(
            f"INSERT INTO STATION_STATUS ({COLS}) VALUES\n"
            + ",\n".join(vals)
            + f"\nON DUPLICATE KEY UPDATE {UPDATE_CLAUSE};"
        )
    return "\n".join(lines)


# CSV  (para LOAD DATA LOCAL INFILE)

CSV_FIELDS = [
    "station_id", "recorded_at", "bikes_available", "docks_available",
    "mechanical_bikes", "electrical_bikes", "is_operative",
]

LOAD_DATA_HINT = """
-- Carga masiva equivalente:
LOAD DATA LOCAL INFILE '{csv_path}'
INTO TABLE bicing.STATION_STATUS
FIELDS TERMINATED BY ','
OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\\n'
IGNORE 1 ROWS
(station_id, recorded_at, bikes_available, docks_available,
 mechanical_bikes, electrical_bikes, is_operative);
"""


def to_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    log.info("CSV → %s (%d filas)", path, len(rows))
    print(LOAD_DATA_HINT.format(csv_path=path))


# Carga MySQL

def load_to_mysql(rows: list[dict], batch_size: int) -> None:
    try:
        import mysql.connector
    except ImportError:
        log.error("Instala mysql-connector-python")
        sys.exit(1)

    sql = (
        f"INSERT INTO STATION_STATUS ({COLS}) VALUES (%s,%s,%s,%s,%s,%s,%s) "
        f"ON DUPLICATE KEY UPDATE {UPDATE_CLAUSE}"
    )
    params = [
        (r["station_id"], r["recorded_at"], r["bikes_available"],
         r["docks_available"], r["mechanical_bikes"],
         r["electrical_bikes"], r["is_operative"])
        for r in rows
    ]
    conn = mysql.connector.connect(**config.DB)
    cur  = conn.cursor()
    for i in range(0, len(params), batch_size):
        cur.executemany(sql, params[i:i + batch_size])
        conn.commit()
        log.info("  Lote %d–%d OK", i + 1, min(i + batch_size, len(params)))
    log.info("STATION_STATUS: %d registros procesados", len(params))
    cur.close()
    conn.close()


# Main

def main():
    parser = argparse.ArgumentParser(description="ETL → STATION_STATUS")
    parser.add_argument("--sql-only",   action="store_true")
    parser.add_argument("--out",        default="station_status.sql")
    parser.add_argument("--csv-out",    default=None)
    parser.add_argument("--batch-size", type=int, default=config.BATCH_SIZE)
    args = parser.parse_args()

    raw  = fetch_json(config.URL_STATUS, config.TOKEN)
    rows = transform(raw)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(to_sql(rows, args.batch_size))
    log.info("SQL → %s", args.out)

    if args.csv_out:
        to_csv(rows, args.csv_out)

    if not args.sql_only:
        load_to_mysql(rows, args.batch_size)


if __name__ == "__main__":
    main()