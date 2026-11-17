"""Laboratorio 6 · carga datos de prueba en el ranking.

Publica eventos `auth.player.registered` y `game.match.ended` en el exchange
`jokerarena.events` (API HTTP de administración de RabbitMQ, puerto 15672), igual que lo
harían auth-identity-ms y game-engine-ms. leaderboard-stats-ms los proyecta en Neo4j.

Uso (desde la raíz del repo, con el sistema levantado):  python perf/lab6/seed_leaderboard.py
"""
import base64
import json
import pathlib
import random
import urllib.request
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLAYERS, MATCHES = 200, 600


def env() -> dict:
    out = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


E = env()
URL = f"http://localhost:{E.get('RABBITMQ_MGMT_PORT', '15672')}/api/exchanges/%2F/jokerarena.events/publish"
AUTH = base64.b64encode(f"{E.get('RABBITMQ_USER', 'jokerarena')}:{E['RABBITMQ_PASSWORD']}".encode()).decode()


def publish(routing_key: str, payload: dict) -> None:
    envelope = {
        "event_id": str(uuid.uuid4()), "type": routing_key, "version": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat(), "producer": "lab6-seed", "payload": payload,
    }
    body = json.dumps({
        "properties": {"content_type": "application/json", "delivery_mode": 2},
        "routing_key": routing_key, "payload": json.dumps(envelope), "payload_encoding": "string",
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Authorization": f"Basic {AUTH}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as res:
        if not json.load(res).get("routed"):
            raise SystemExit(f"El evento {routing_key} no llegó a ninguna cola.")


def main() -> None:
    rnd = random.Random(6)
    players = [(str(uuid.uuid4()), f"Jugador{i:03d}") for i in range(1, PLAYERS + 1)]
    for pid, alias in players:
        publish("auth.player.registered", {"player_id": pid, "alias": alias})
    for i in range(MATCHES):
        target = rnd.choice([22000, 26000, 33000])
        if i % 3 == 0:  # partida contra el bot
            pid, alias = rnd.choice(players)
            won = rnd.random() < 0.55
            results = [
                {"player_id": pid, "alias": alias, "score": rnd.randint(target, target + 9000) if won else rnd.randint(3000, target - 1), "won": won, "is_bot": False},
                {"player_id": "bot", "alias": "Bot", "score": rnd.randint(3000, target - 1), "won": not won, "is_bot": True},
            ]
        else:  # dos jugadores
            (a, aa), (b, ba) = rnd.sample(players, 2)
            results = [
                {"player_id": a, "alias": aa, "score": rnd.randint(target, target + 9000), "won": True, "is_bot": False},
                {"player_id": b, "alias": ba, "score": rnd.randint(3000, target - 1), "won": False, "is_bot": False},
            ]
        publish("game.match.ended", {
            "match_id": str(uuid.uuid4()), "room_code": f"JKR-{rnd.randint(0, 0xFFFF):04X}", "is_bot_match": i % 3 == 0,
            "reason": "TARGET_SCORE_REACHED", "target_score": target, "hands_played": rnd.randint(6, 20), "results": results,
        })
    print(f"Publicados {PLAYERS} jugadores y {MATCHES} partidas.")


if __name__ == "__main__":
    main()
