CREATE DATABASE IF NOT EXISTS bicing
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE bicing;

-- 1. Estaciones — atributos estáticos
CREATE TABLE IF NOT EXISTS STATIONS (
    station_id          INTEGER         NOT NULL,
    name                VARCHAR(100)    NOT NULL,
    latitude            DECIMAL(9,6)    NOT NULL,
    longitude           DECIMAL(9,6)    NOT NULL,
    altitude            DECIMAL(6,2)    DEFAULT NULL,           -- nullable
    capacity            INTEGER         NOT NULL,
    district_id         INTEGER         NOT NULL,
    district_name       VARCHAR(100)    NOT NULL,
    neighborhood_id     INTEGER         NOT NULL,
    neighborhood_name   VARCHAR(100)    NOT NULL,
    -- Columna geométrica derivada (no en el modelo lógico, útil para consultas)
    location            POINT           NOT NULL SRID 4326,
    PRIMARY KEY (station_id),
    SPATIAL INDEX idx_location (location)
) ENGINE=InnoDB;

-- 2. Estado temporal de estaciones (clave primaria compuesta)
CREATE TABLE IF NOT EXISTS STATION_STATUS (
    station_id          INTEGER         NOT NULL,
    recorded_at         DATETIME        NOT NULL,
    bikes_available     INTEGER         NOT NULL,
    docks_available     INTEGER         NOT NULL,
    mechanical_bikes    INTEGER         NOT NULL,
    electrical_bikes    INTEGER         NOT NULL,
    is_operative        BOOLEAN         NOT NULL,
    PRIMARY KEY (station_id, recorded_at),
    CONSTRAINT fk_status_station
        FOREIGN KEY (station_id) REFERENCES STATIONS(station_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    INDEX idx_recorded_at (recorded_at)
) ENGINE=InnoDB;

-- 3. Carrils bici — geometrías lineales
CREATE TABLE IF NOT EXISTS BIKE_LANES (
    lane_id             INTEGER         NOT NULL AUTO_INCREMENT,
    lane_type           VARCHAR(50)     DEFAULT NULL,           -- nullable
    lane_name           VARCHAR(100)    DEFAULT NULL,           -- nullable
    geometry            LINESTRING      NOT NULL SRID 4326,
    PRIMARY KEY (lane_id),
    SPATIAL INDEX idx_geometry (geometry)
) ENGINE=InnoDB;

-- 4. Grafo de distancias entre estaciones
CREATE TABLE IF NOT EXISTS STATION_EDGES (
    station_from        INTEGER         NOT NULL,
    station_to          INTEGER         NOT NULL,
    distance_m          DECIMAL(10,2)   NOT NULL,
    PRIMARY KEY (station_from, station_to),
    CONSTRAINT fk_edge_from
        FOREIGN KEY (station_from) REFERENCES STATIONS(station_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_edge_to
        FOREIGN KEY (station_to)   REFERENCES STATIONS(station_id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;