# Token de acceso (Open Data Barcelona)
import os
 
TOKEN = os.environ.get("BICING_TOKEN", "")
 
URL_INFO = (
    "https://opendata-ajuntament.barcelona.cat"
    "/data/dataset/bd2462df-6e1e-4e37-8205-a4b8e7313b84"
    "/resource/f60e9291-5aaa-417d-9b91-612a9de800aa"
    "/download/Informacio_Estacions_Bicing.json"
)
 
URL_STATUS = (
    "https://opendata-ajuntament.barcelona.cat"
    "/data/dataset/6aa3416d-ce1a-494d-861b-7bd07f069600"
    "/resource/1b215493-9e63-4a12-8980-2d7e0fa19f85"
    "/download/Estat_Estacions_Bicing.json"
)
 
URL_GEOJSON = (
    "https://opendata-ajuntament.barcelona.cat"
    "/resources/bcn/CarrilsBici/CARRIL_BICI.geojson"
)
 

DB = {
    "host":     os.environ.get("DB_HOST", "localhost"),
    "port":     int(os.environ.get("DB_PORT", 3306)),
    "user":     os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASS", ""),
    "database": os.environ.get("DB_NAME", "bicing"),
}

BATCH_SIZE = 500          # filas por INSERT en station_status