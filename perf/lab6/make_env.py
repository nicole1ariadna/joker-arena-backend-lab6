"""Laboratorio 6 · crea el archivo .env a partir de .env.example.

Reemplaza cada marcador <...> por una contraseña aleatoria. Si .env ya existe no lo toca.
Uso (desde la raíz del repo):  python perf/lab6/make_env.py
"""
import pathlib
import re
import secrets

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLACEHOLDER = re.compile(r"<[^<>\r\n]+>")

env = ROOT / ".env"
if env.exists():
    print(".env ya existe: no se modifica.")
else:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    filled = PLACEHOLDER.sub(lambda m: secrets.token_hex(12), text)
    env.write_text(filled, encoding="utf-8", newline="\n")
    print(f".env creado con {len(PLACEHOLDER.findall(text))} contraseñas aleatorias (solo para este despliegue local).")
