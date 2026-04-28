"""
fetcher.py — Descarga de recursos con cabecera Authorization
Compatible con la autenticación por token del Open Data Barcelona.
"""
 
import logging
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
 
log = logging.getLogger(__name__)
 
 
def fetch_json(url: str, token: str) -> dict:
    """
    Descarga un recurso JSON usando la cabecera Authorization.
    Equivalente al ejemplo oficial:
        request.add_header('Authorization', token)
    """
    log.info("GET %s", url)
    req = Request(url)
    req.add_header("Authorization", token)
    req.add_header("Accept", "application/json")
 
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw)
    except HTTPError as e:
        log.error("HTTP %s al acceder a %s — %s", e.code, url, e.reason)
        if e.code == 401:
            log.error("  → Token inválido o caducado. Revisa config.TOKEN")
        elif e.code == 403:
            log.error("  → Sin permiso. Verifica que el token tenga acceso al recurso")
        raise
    except URLError as e:
        log.error("Error de red al acceder a %s — %s", url, e.reason)
        raise