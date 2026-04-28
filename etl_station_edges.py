"""
Calcula y carga las distancias entre pares de estaciones -> tabla STATION_EDGES.

La tabla STATION_EDGES no tiene fuente directa, por lo tanto, se deriva de STATIONS calculando
la distancia geodésica (Haversine) entre cada par de estaciones. 

Estrategias disponibles (--mode):
  knn     K vecinos más cercanos por estación (default, K=5)
  radius  Todas las parejas dentro de un radio en metros (--radius-m)
  full    Producto cartesiano completo (solo viable para datasets pequeños)

Uso:
    python etl_station_edges.py [--sql-only] [--out edges.sql]
                                [--mode knn] [--knn 5]
                                [--mode radius] [--radius-m 500]
    
    # Leer coordenadas desde MySQL (recomendado tras cargar STATIONS):
    python etl_station_edges.py --from-db

    # Leer desde el JSON de la API (sin necesidad de MySQL):
    python etl_station_edges.py --sql-only
"""

import argparse
import logging
import math
import sys
from typing import Any

import config
from fetcher import fetch_json

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

EARTH_RADIUS_M = 6_371_000.0


# Distancia Haversine (metros)

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a  = math.sin(dφ/2)**2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ/2)**2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# Obtención de coordenadas

def stations_from_api() -> list[dict]:
    # Lee las estaciones directamente de la API (sin necesidad de MySQL).
    raw = fetch_json(config.URL_INFO, config.TOKEN)
    stations_raw = (
        raw.get("data", {}).get("stations")
        or raw.get("stations")
        or []
    )
    result = []
    for s in stations_raw:
        sid = s.get("station_id")
        lat = s.get("lat")
        lon = s.get("lon")
        if sid and lat is not None and lon is not None:
            result.append({"station_id": sid, "latitude": float(lat), "longitude": float(lon)})
    log.info("Estaciones leídas de la API: %d", len(result))
    return result


def stations_from_db() -> list[dict]:
    # Lee latitude/longitude de la tabla STATIONS ya cargada en MySQL.
    try:
        import mysql.connector
    except ImportError:
        log.error("Instala mysql-connector-python")
        sys.exit(1)
    conn = mysql.connector.connect(**config.DB)
    cur  = conn.cursor(dictionary=True)
    cur.execute("SELECT station_id, latitude, longitude FROM STATIONS")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    log.info("Estaciones leídas de STATIONS (DB): %d", len(rows))
    return rows



# Cálculo de aristas

def compute_knn(stations: list[dict], k: int) -> list[dict]:
    # K vecinos más cercanos (sin incluir la propia estación).
    edges = {}
    n = len(stations)
    for i in range(n):
        a = stations[i]
        dists = []
        for j in range(n):
            if i == j:
                continue
            b = stations[j]
            d = haversine(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
            dists.append((d, b["station_id"]))
        dists.sort()
        for d, sid_to in dists[:k]:
            key = (min(a["station_id"], sid_to), max(a["station_id"], sid_to))
            edges[key] = round(d, 2)
    result = [{"station_from": f, "station_to": t, "distance_m": d}
              for (f, t), d in edges.items()]
    log.info("Aristas KNN (k=%d): %d", k, len(result))
    return result


def compute_radius(stations: list[dict], radius_m: float) -> list[dict]:
    # Todas las parejas dentro del radio dado.
    edges = {}
    n = len(stations)
    for i in range(n):
        a = stations[i]
        for j in range(i + 1, n):
            b = stations[j]
            d = haversine(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
            if d <= radius_m:
                key = (a["station_id"], b["station_id"])
                edges[key] = round(d, 2)
    result = [{"station_from": f, "station_to": t, "distance_m": d}
              for (f, t), d in edges.items()]
    log.info("Aristas radio (≤%.0f m): %d", radius_m, len(result))
    return result


def compute_full(stations: list[dict]) -> list[dict]:
    # Producto cartesiano completo (solo para datasets pequeños!!) 
    edges = []
    n = len(stations)
    for i in range(n):
        a = stations[i]
        for j in range(i + 1, n):
            b = stations[j]
            d = haversine(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
            edges.append({"station_from": a["station_id"],
                          "station_to":   b["station_id"],
                          "distance_m":   round(d, 2)})
    log.info("Aristas completas: %d", len(edges))
    return edges


# SQL

COLS = "station_from, station_to, distance_m"


def _esc(v: Any) -> str:
    if isinstance(v, (int, float)):
        return str(v)
    return "NULL"


def to_sql(edges: list[dict], batch_size: int = 500) -> str:
    lines = ["USE bicing;", ""]
    for i in range(0, len(edges), batch_size):
        chunk = edges[i:i + batch_size]
        # usamos _esc porque nos ayuda en las transformaciones a SQL. 
        # comprueba si es un número (int/float) y lo devuelve como string sin comillas, o devuelve "NULL" para otros casos.
        vals  = [
            f"({_esc(e['station_from'])}, {_esc(e['station_to'])}, {_esc(e['distance_m'])})"
            for e in chunk
        ]
        lines.append(
            f"INSERT INTO STATION_EDGES ({COLS}) VALUES\n"
            + ",\n".join(vals)
            + "\nON DUPLICATE KEY UPDATE distance_m=VALUES(distance_m);"
        )
    return "\n".join(lines)


# Carga MySQL

def load_to_mysql(edges: list[dict], batch_size: int = 500) -> None:
    try:
        import mysql.connector
    except ImportError:
        log.error("Instala mysql-connector-python")
        sys.exit(1)

    sql = (
        f"INSERT INTO STATION_EDGES ({COLS}) VALUES (%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE distance_m=VALUES(distance_m)"
    )
    params = [(e["station_from"], e["station_to"], e["distance_m"]) for e in edges]

    conn = mysql.connector.connect(**config.DB)
    cur  = conn.cursor()
    for i in range(0, len(params), batch_size):
        cur.executemany(sql, params[i:i + batch_size])
        conn.commit()
    log.info("STATION_EDGES: %d aristas insertadas/actualizadas", len(params))
    cur.close()
    conn.close()


# Main

def main():
    parser = argparse.ArgumentParser(description="ETL → STATION_EDGES")
    parser.add_argument("--sql-only",  action="store_true")
    parser.add_argument("--from-db",   action="store_true",
                        help="Leer coordenadas de MySQL en lugar de la API")
    parser.add_argument("--out",       default="station_edges.sql")
    parser.add_argument("--mode",      choices=["knn", "radius", "full"], default="knn")
    parser.add_argument("--knn",       type=int,   default=5,
                        help="Número de vecinos más cercanos (modo knn)")
    parser.add_argument("--radius-m",  type=float, default=500.0,
                        help="Radio máximo en metros (modo radius)")
    parser.add_argument("--batch-size",type=int,   default=500)
    args = parser.parse_args()

    stations = stations_from_db() if args.from_db else stations_from_api()

    if args.mode == "knn":
        edges = compute_knn(stations, args.knn)
    elif args.mode == "radius":
        edges = compute_radius(stations, args.radius_m)
    else:
        if len(stations) > 300:
            log.warning("Modo 'full' con %d estaciones genera %d aristas",
                        len(stations), len(stations)*(len(stations)-1)//2)
        edges = compute_full(stations)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(to_sql(edges, args.batch_size))
    log.info("SQL → %s", args.out)

    if not args.sql_only:
        load_to_mysql(edges, args.batch_size)


if __name__ == "__main__":
    main()