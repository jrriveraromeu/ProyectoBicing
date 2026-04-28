-- variables globales (se pueden ajustar) 
SET @sigma  = 300.0;   -- escala gaussiana en metros
SET @alpha  = 0.20;    -- peso de ocupación actual
SET @beta   = 0.45;    -- peso de vecindad espacial
SET @t_star = (SELECT MAX(recorded_at) FROM STATION_STATUS);

-- Modelo de difusión

WITH

-- Operación 1: dos snapshots por estación (actual y anterior)
ranked_status AS (
    SELECT
        ss.station_id,
        ss.recorded_at,
        ss.bikes_available,
        ROW_NUMBER() OVER (
            PARTITION BY ss.station_id
            ORDER BY ss.recorded_at DESC
        ) AS rn
    FROM STATION_STATUS ss
),
current_occupancy AS (
    SELECT
        rs.station_id,
        rs.bikes_available / s.capacity AS occupancy
    FROM ranked_status rs
    JOIN STATIONS s USING (station_id)
    WHERE rs.rn = 1
      AND s.capacity > 0
),
previous_occupancy AS (
    SELECT
        rs.station_id,
        rs.bikes_available / s.capacity AS occupancy_prev
    FROM ranked_status rs
    JOIN STATIONS s USING (station_id)
    WHERE rs.rn = 2
      AND s.capacity > 0
),

-- Operación 2: pesos gaussianos sobre aristas en ambos sentidos
sym_edges AS (
    SELECT station_from, station_to, distance_m
    FROM STATION_EDGES
    UNION ALL
    SELECT station_to AS station_from, station_from AS station_to, distance_m
    FROM STATION_EDGES
),
gaussian_weights AS (
    SELECT
        station_from,
        station_to,
        EXP(-(distance_m * distance_m) / (2 * @sigma * @sigma))  AS w
    FROM sym_edges
),

-- Operación 3: normalización por filas -> matriz de transición T
row_totals AS (
    SELECT station_from, SUM(w) AS total_w
    FROM gaussian_weights
    GROUP BY station_from
),
transition AS (
    SELECT
        gw.station_from,
        gw.station_to,
        gw.w / rt.total_w  AS t_ij
    FROM gaussian_weights gw
    JOIN row_totals rt ON rt.station_from = gw.station_from
),

-- Operación 4a: influencia de la vecindad (T · x(t))
neighbor_influence AS (
    SELECT
        t.station_from  AS station_id,
        SUM(t.t_ij * co.occupancy) AS nb_occupancy
    FROM transition t
    JOIN current_occupancy co ON co.station_id = t.station_to
    GROUP BY t.station_from
),

-- Operación 4b: tendencia temporal por estación (x(t) - x(t-1))
temporal_signal AS (
    SELECT
        co.station_id,
        co.occupancy,
        po.occupancy_prev,
        (co.occupancy - COALESCE(po.occupancy_prev, co.occupancy)) AS temporal_delta
    FROM current_occupancy co
    LEFT JOIN previous_occupancy po USING (station_id)
),

-- Operación 4c: predicción espacial-temporal
-- x(t+1) = α·x(t) + β·T·x(t) + (1-α-β)·(x(t) + (x(t)-x(t-1)))
prediction AS (
    SELECT
        ts.station_id,
        ROUND(
            LEAST(
                1.0,
                GREATEST(
                    0.0,
                    @alpha * ts.occupancy
                    + @beta * COALESCE(ni.nb_occupancy, ts.occupancy)
                    + (1 - @alpha - @beta) * (ts.occupancy + ts.temporal_delta)
                )
            ),
            4
        ) AS predicted_occupancy
    FROM temporal_signal ts
    LEFT JOIN neighbor_influence ni ON ni.station_id = ts.station_id
)

-- Resultado final con contexto de estación
SELECT
    p.station_id,
    s.name,
    s.district_name,
    s.altitude,
    ROUND(co.occupancy, 4)                        AS current_occupancy,
    p.predicted_occupancy,
    ROUND(p.predicted_occupancy - co.occupancy, 4) AS delta,
    CASE
        WHEN p.predicted_occupancy > co.occupancy + 0.01 THEN 'SUBE'
        WHEN p.predicted_occupancy < co.occupancy - 0.01 THEN 'BAJA'
        ELSE 'ESTABLE'
    END                                            AS tendencia
FROM prediction p
JOIN current_occupancy co USING (station_id)
JOIN STATIONS s           USING (station_id)
ORDER BY p.station_id; -- para que salgan ordenadas por id