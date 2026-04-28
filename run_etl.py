"""
run_etl.py — Orquestador del pipeline completo Bicing -> MySQL

Orden de carga (respeta FK):
  1. STATIONS            (sin dependencias)
  2. STATION_STATUS      (FK -> STATIONS)
  3. BIKE_LANES          (sin dependencias)
  4. STATION_EDGES       (FK -> STATIONS x2)

Uso:
    python run_etl.py [--sql-only] [--out-dir ./output]
                      [--mode knn] [--knn 5]
                      [--csv-status] [--local-geojson PATH]
"""

import argparse
import json
import logging
import os
import time

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

import config
from fetcher import fetch_json
import etl_station_information as etl_info
import etl_station_status      as etl_status
import etl_carril_bici         as etl_carrils
import etl_station_edges       as etl_edges

def _load_mysql_safely(label: str, loader, *args) -> bool:
    try:
        loader(*args)
        return True
    except Exception as exc:
        log.error("Carga MySQL omitida para %s: %s", label, exc)
        return False


def run(args):
    os.makedirs(args.out_dir, exist_ok=True)
    results = {}

    # ── 1. STATIONS ──────────────────────────────────────────────
    log.info("━━━ [1/4] STATIONS ━━━")
    t0   = time.time()
    raw  = fetch_json(config.URL_INFO, config.TOKEN)
    rows = etl_info.transform(raw)
    out  = os.path.join(args.out_dir, "01_stations.sql")
    with open(out, "w", encoding="utf-8") as f:
        f.write(etl_info.to_sql(rows))
    if not args.sql_only:
            _load_mysql_safely("station_information", etl_info.load_to_mysql, rows)
    results["STATIONS"] = {"rows": len(rows), "secs": round(time.time()-t0, 1)}
    log.info("  OK %d estaciones → %s", len(rows), out)

    # ── 2. STATION_STATUS ───────────────────────────────────────────
    log.info("━━━ [2/4] STATION_STATUS ━━━")
    t0   = time.time()
    raw  = fetch_json(config.URL_STATUS, config.TOKEN)
    rows = etl_status.transform(raw)
    out  = os.path.join(args.out_dir, "02_station_status.sql")
    with open(out, "w", encoding="utf-8") as f:
        f.write(etl_status.to_sql(rows, args.batch_size))
    if args.csv_status:
        etl_status.to_csv(rows, os.path.join(args.out_dir, "station_status.csv"))
    if not args.sql_only:
            _load_mysql_safely("station_status", etl_status.load_to_mysql, rows, args.batch_size)
    results["STATION_STATUS"] = {"rows": len(rows), "secs": round(time.time()-t0, 1)}
    log.info("  OK %d snapshots → %s", len(rows), out)

    # ── 3. BIKE_LANES ───────────────────────────────────────────────
    log.info("━━━ [3/4] BIKE_LANES ━━━")
    t0 = time.time()
    if args.local_geojson:
        with open(args.local_geojson, encoding="utf-8") as f:
            geojson = json.load(f)
    else:
        geojson = fetch_json(config.URL_GEOJSON, config.TOKEN)
    rows = etl_carrils.transform(geojson)
    out  = os.path.join(args.out_dir, "03_bike_lanes.sql")
    with open(out, "w", encoding="utf-8") as f:
        f.write(etl_carrils.to_sql(rows))
    if not args.sql_only:
            _load_mysql_safely("carril_bici", etl_carrils.load_to_mysql, rows)
    results["BIKE_LANES"] = {"rows": len(rows), "secs": round(time.time()-t0, 1)}
    log.info("  OK %d segmentos → %s", len(rows), out)

    # ── 4. STATION_EDGES ────────────────────────────────────────────
    log.info("━━━ [4/4] STATION_EDGES ━━━")
    t0 = time.time()
    # Reutilizar las estaciones ya descargadas 
    raw_info   = fetch_json(config.URL_INFO, config.TOKEN)
    stations   = etl_edges.stations_from_api.__wrapped__(raw_info) \
                 if hasattr(etl_edges.stations_from_api, "__wrapped__") \
                 else etl_edges.stations_from_api()

    if args.edges_mode == "knn":
        edge_rows = etl_edges.compute_knn(stations, args.knn)
    elif args.edges_mode == "radius":
        edge_rows = etl_edges.compute_radius(stations, args.radius_m)
    else:
        edge_rows = etl_edges.compute_full(stations)

    out = os.path.join(args.out_dir, "04_station_edges.sql")
    with open(out, "w", encoding="utf-8") as f:
        f.write(etl_edges.to_sql(edge_rows, args.batch_size))
    if not args.sql_only:
            _load_mysql_safely("station_edges", etl_edges.load_to_mysql, edge_rows, args.batch_size)
    results["STATION_EDGES"] = {"rows": len(edge_rows), "secs": round(time.time()-t0, 1)}
    log.info("  OK %d aristas → %s", len(edge_rows), out)

    # ── Resumen ─────────────────────────────────────────────────────
    log.info("━━━ Resumen ━━━")
    for tabla, r in results.items():
        log.info("  %-20s  %5d filas  %.1f s", tabla, r["rows"], r["secs"])
    log.info("Archivos SQL en: %s", args.out_dir)


def main():
    parser = argparse.ArgumentParser(description="Pipeline ETL Bicing → MySQL 8")
    parser.add_argument("--sql-only",      action="store_true")
    parser.add_argument("--out-dir",       default="./output")
    parser.add_argument("--batch-size",    type=int,   default=config.BATCH_SIZE)
    parser.add_argument("--csv-status",    action="store_true")
    parser.add_argument("--local-geojson", default=None)
    parser.add_argument("--edges-mode",    choices=["knn","radius","full"], default="knn")
    parser.add_argument("--knn",           type=int,   default=5)
    parser.add_argument("--radius-m",      type=float, default=500.0)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()