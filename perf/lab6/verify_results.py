"""Laboratorio 6 · verificación de los resultados.

Comprueba que los datos sean coherentes entre sí y con lo que vio el servidor:
  1. Aritmética de cada nivel (peticiones esperadas, suma de fallas, throughput).
  2. Cruce con el API Gateway: las respuestas 200 y 503 que registró nginx durante la
     ventana de cada ejecución deben coincidir con las que contó k6. También detecta
     carga ajena (otra prueba corriendo al mismo tiempo).
  3. Reproducibilidad: compara con la segunda ejecución guardada en results/_repeat.
     (results/_bateria, medido en otra condición del equipo, solo se cruza con el gateway.)
  4. results.csv y la tabla del README coinciden con los JSON crudos.

Uso (con los contenedores arriba):  python perf/lab6/verify_results.py
"""
import csv
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
RESULTS = HERE / "results"
ACCESS = re.compile(r'^(\S+) .*HTTP/1\.1" (\d{3}) ')
problems: list[str] = []


def check(ok: bool, msg: str) -> str:
    if not ok:
        problems.append(msg)
    return "OK " if ok else "MAL"


def load(folder: pathlib.Path) -> list[dict]:
    rows = []
    for p in sorted(folder.glob("vus_*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        r["_end"] = p.stat().st_mtime
        rows.append(r)
    return sorted(rows, key=lambda r: r["vus"])


def gateway_log() -> list[tuple[float, int]]:
    out = subprocess.run(["docker", "logs", "-t", "jokerarena-gateway"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    entries = []
    for line in (out.stdout + out.stderr).splitlines():
        m = ACCESS.match(line)
        if not m or "/api/leaderboard/top" not in line:
            continue
        ts = m.group(1)[:26].rstrip("Z")  # docker da nanosegundos; datetime acepta microsegundos
        entries.append((datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).timestamp(), int(m.group(2))))
    return entries


def arithmetic(rows: list[dict]) -> None:
    print("1. Aritmética de cada nivel")
    print(f"   {'VUs':>5} {'peticiones':>10} {'esperadas':>9} {'%':>4}  {'fallas=suma':>12}  {'ok+fallas=total':>15}")
    for r in rows:
        secs = r["requests"] / r["throughput_rps"]
        ramp = 0.5 if r.get("ramp_up", "0s") != "0s" else 0.0  # rampa lineal de 1 s ≈ 0,5 s de carga plena
        expected = r["vus"] * (30 + ramp) / (1 + r["avg_ms"] / 1000)
        ratio = r["requests"] / expected
        s = r["fail_connection"] + r["fail_503"] + r["fail_other_status"]
        a = check(0.93 <= ratio <= 1.10, f"{r['vus']} VUs: peticiones {r['requests']} vs esperadas {expected:.0f}")
        b = check(s == r["failed_requests"], f"{r['vus']} VUs: las fallas clasificadas no suman el total")
        ok = round(r["ok_throughput_rps"] * secs)
        c = check(abs(ok + r["failed_requests"] - r["requests"]) <= 1, f"{r['vus']} VUs: ok + fallas != total")
        print(f"   {r['vus']:>5} {r['requests']:>10} {expected:>9.0f} {100 * ratio:>4.0f} {a} {s:>5}={r['failed_requests']:<5} {b} {ok:>7}+{r['failed_requests']:<6} {c}")


def cross_check(rows: list[dict], log: list[tuple[float, int]], label: str) -> None:
    print(f"\n2. Cruce con el log del API Gateway ({label})")
    print(f"   {'VUs':>5} {'k6 ok':>7} {'nginx 200':>9} {'k6 503':>7} {'nginx 503':>9} {'otros':>6}")
    for r in rows:
        secs = r["requests"] / r["throughput_rps"]
        lo, hi = r["_end"] - secs - 6, r["_end"] + 2
        codes = [c for t, c in log if lo <= t <= hi]
        n200, n503 = codes.count(200), codes.count(503)
        other = len(codes) - n200 - n503
        k_ok = r["requests"] - r["failed_requests"]
        # nginx registra con 499 las peticiones que k6 cortó al terminar la prueba: se toleran unas pocas.
        tol = max(3, int(0.002 * r["requests"]))
        a = check(abs(n200 - k_ok) <= tol, f"{r['vus']} VUs ({label}): nginx vio {n200} respuestas 200 y k6 contó {k_ok}")
        b = check(abs(n503 - r["fail_503"]) <= tol, f"{r['vus']} VUs ({label}): nginx vio {n503} respuestas 503 y k6 contó {r['fail_503']}")
        print(f"   {r['vus']:>5} {k_ok:>7} {n200:>9} {a} {r['fail_503']:>5} {n503:>9} {b} {other:>4}")


def repeatability(rows: list[dict], rep: list[dict]) -> None:
    print("\n3. Reproducibilidad (segunda ejecución)")
    print(f"   {'VUs':>5} {'fallos % 1ª':>11} {'fallos % 2ª':>11} {'ok req/s 1ª':>11} {'ok req/s 2ª':>11} {'avg ms 1ª':>10} {'avg ms 2ª':>10}")
    by = {r["vus"]: r for r in rows}
    for b in rep:
        a = by.get(b["vus"])
        if not a:
            continue
        same_side = (a["failed_pct"] == 0) == (b["failed_pct"] == 0)
        v = check(same_side, f"{b['vus']} VUs: una ejecución tuvo errores y la otra no")
        thr = check(abs(a["ok_throughput_rps"] - b["ok_throughput_rps"]) <= 0.15 * a["ok_throughput_rps"],
                    f"{b['vus']} VUs: el throughput exitoso difiere más de 15 % entre ejecuciones")
        print(f"   {b['vus']:>5} {a['failed_pct']:>11.2f} {b['failed_pct']:>11.2f} {v} {a['ok_throughput_rps']:>8.1f} {b['ok_throughput_rps']:>11.1f} {thr} {a['avg_ms']:>7.2f} {b['avg_ms']:>10.2f}")


def deliverables(rows: list[dict]) -> None:
    print("\n4. CSV y README contra los JSON crudos")
    with (RESULTS / "results.csv").open(encoding="utf-8") as f:
        c = {int(r["vus"]): r for r in csv.DictReader(f)}
    ok_csv = len(c) == len(rows) and all(
        abs(float(c[r["vus"]]["avg_ms"]) - r["avg_ms"]) < 0.01 and int(c[r["vus"]]["failed_requests"]) == r["failed_requests"]
        and int(c[r["vus"]]["requests"]) == r["requests"] for r in rows if r["vus"] in c)
    print(f"   {check(ok_csv, 'results.csv no coincide con los JSON')} results.csv ({len(c)} niveles)")
    md = (HERE / "README.md").read_text(encoding="utf-8")
    bad = []
    for r in rows:
        m = re.search(rf"^\| {r['vus']:,} \|.*$".replace(",", " "), md, re.M)
        cells = [x.strip().replace(" ", "") for x in m.group(0).split("|")] if m else []
        want = [str(r["requests"]), f"{r['ok_throughput_rps']:.1f}", f"{r['avg_ms']:.1f}", f"{r['failed_pct']:.2f}%"]
        if not all(w in cells for w in want):
            bad.append(r["vus"])
    print(f"   {check(not bad, f'filas del README que no coinciden: {bad}')} tabla del README ({len(rows)} filas)")
    svg = (RESULTS / "performance_curve.svg").read_text(encoding="utf-8")
    n_points = svg.count('r="4.5"')
    print(f"   {check(n_points == len(rows), f'la gráfica tiene {n_points} puntos y hay {len(rows)} niveles')} gráfica: {n_points} puntos")


def main() -> None:
    rows, rep = load(RESULTS), load(RESULTS / "_repeat")
    if not rows:
        raise SystemExit("No hay resultados.")
    arithmetic(rows)
    log = gateway_log()
    cross_check(rows, log, "ejecución principal")
    if rep:
        cross_check(rep, log, "segunda ejecución")
        repeatability(rows, rep)
    battery = load(RESULTS / "_bateria")
    if battery:
        cross_check(battery, log, "anexo: equipo con batería")
    deliverables(rows)
    print("\n" + ("TODO COHERENTE." if not problems else "PROBLEMAS:\n - " + "\n - ".join(problems)))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
