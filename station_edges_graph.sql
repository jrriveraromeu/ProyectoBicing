USE bicing;
TRUNCATE TABLE STATION_EDGES;

INSERT INTO STATION_EDGES (station_from, station_to, distance_m)
WITH

-- Operación 1: pares candidatos por vecindad espacial
station_pairs AS (
    SELECT
        a.station_id  AS station_from,
        b.station_id  AS station_to,
        ROUND(ST_Distance(a.location, b.location) * 111320 * COS(RADIANS(41.4)), 2)  AS dist_direct_m,
        COALESCE(b.altitude, 0) - COALESCE(a.altitude, 0) AS altitude_diff_m
    FROM  STATIONS a
    JOIN  STATIONS b ON a.station_id < b.station_id
    WHERE ST_Distance(a.location, b.location)
          * 111320 * COS(RADIANS(41.4)) <= 500
),

-- Operación 2: semijoin con BIKE_LANES (afinidad ciclista)
lane_affinity AS (
    SELECT DISTINCT sp.station_from, sp.station_to
    FROM station_pairs sp
    JOIN BIKE_LANES bl
      ON ST_Distance(
             (SELECT location FROM STATIONS WHERE station_id = sp.station_from),
             bl.geometry
         ) * 111320 * COS(RADIANS(41.4)) <= 150
     AND ST_Distance(
             (SELECT location FROM STATIONS WHERE station_id = sp.station_to),
             bl.geometry
         ) * 111320 * COS(RADIANS(41.4)) <= 150
),

-- Operación 3: peso compuesto (distancia × factor ciclista + penalización desnivel)
weighted_edges AS (
    SELECT
        sp.station_from,
        sp.station_to,
        ROUND(
            sp.dist_direct_m
            * CASE WHEN la.station_from IS NOT NULL THEN 1.0 ELSE 1.5 END
            + GREATEST(sp.altitude_diff_m, 0) * 0.1 , 2) AS distance_m
    FROM      station_pairs    sp
    LEFT JOIN lane_affinity    la
           ON la.station_from = sp.station_from
          AND la.station_to   = sp.station_to
)

SELECT station_from, station_to, distance_m
FROM   weighted_edges
ORDER  BY station_from, distance_m;