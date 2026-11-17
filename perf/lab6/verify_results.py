"""Laboratorio 6 · verificación de los resultados.

  python perf/lab6/verify_results.py
      Revisa los resultados publicados (perf/lab6/results): aritmética, reproducibilidad
      (results/_repeat) y que el CSV, la tabla del README y la gráfica salgan de los JSON crudos.

  python perf/lab6/verify_results.py perf/lab6/results/_local
      Revisa una ejecución propia del barrido: aritmética, cruce con el log del API Gateway
      (requiere los contenedores arriba) y comparación con los resultados publicados.

Cruce con el gateway: las respuestas 200 y 503 que registró nginx durante cada ejecución deben
coincidir con las que contó k6. Solo es posible mientras exista el contenedor que atendió la
prueba; para ejecuciones anteriores (como las publicadas) ese log ya no existe y se omite.
"""
import csv
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
PUBLISHED = HERE / "results"
ACCESS = re.compile(r'^(\S+) .*HTTP/1\.1" (\d{3}) ')
GATEWAY_PORTS = 28232  # puertos efímeros del contenedor del gateway (32768-60999)
problems: list[str] = []
notes: list[str] = []


def check(ok: bool, msg: str) -> str:
    if not ok:
        problems.append(msg)
    return "OK " if ok else "MAL"


def load(folder: pathlib.Path) -> list[dict]:
    rows = []
    for p in sorted(folder.glob("vus_*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        # Hora de fin de la ejecución, guardada por k6. No se usa la fecha del archivo: cambia al clonar o copiar.
        r["_end"] = datetime.fromisoformat(r["ended_at"].replace("Z", "+00:00")).timestamp() if r.get("ended_at") else None
        rows.append(r)
    return sorted(rows, key=lambda r: r["vus"])


def knee(rows: list[dict]) -> tuple[int | None, int | None]:
    last_ok = None
    for r in rows:
        if r["failed_pct"] > 0:
            return last_ok, r["vus"]
        last_ok = r["vus"]
    return last_ok, None


def gateway_log() -> list[tuple[float, int]]:
    try:
        out = subprocess.run(["docker", "logs", "-t", "jokerarena-gateway"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    entries = []
    for line in (out.stdout + out.stderr).splitlines():
        m = ACCESS.match(line)
        if not m or "/api/leaderboard/top?limit=10" not in line:
            continue
        ts = m.group(1)[:26].rstrip("Z")  # docker da nanosegundos; datetime acepta microsegundos
        entries.append((datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).timestamp(), int(m.group(2))))
    return entries


def arithmetic(rows: list[dict]) -> None:
    print("Aritmética de cada nivel")
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


def cross_check(rows: list[dict], log: list[tuple[float, int]]) -> None:
    print("\nCruce con el log del API Gateway")
    log_start = min((t for t, _ in log), default=float("inf"))
    printed_header, skipped = False, []
    for r in rows:
        secs = r["requests"] / r["throughput_rps"]
        if r["_end"] is None or r["_end"] < log_start:  # terminó antes de que existiera el gateway actual: no hay registro de esa ejecución
            skipped.append(r["vus"])
            continue
        lo, hi = r["_end"] - secs - 6, r["_end"] + 2
        # La ventana no debe alcanzar la ejecución anterior (pasa si se usó una pausa corta entre niveles).
        earlier = [x["_end"] for x in rows if x["_end"] is not None and x["_end"] < r["_end"]]
        if earlier:
            lo = max(lo, max(earlier) + 0.5)
        if not printed_header:
            print(f"   {'VUs':>5} {'k6 ok':>7} {'nginx 200':>9} {'k6 503':>7} {'nginx 503':>9}")
            printed_header = True
        codes = [c for t, c in log if lo <= t <= hi]
        n200, n503 = codes.count(200), codes.count(503)
        k_ok = r["requests"] - r["failed_requests"]
        tol = max(3, int(0.002 * r["requests"]))
        a = check(abs(n200 - k_ok) <= tol, f"{r['vus']} VUs: nginx vio {n200} respuestas 200 y k6 contó {k_ok}")
        b = check(abs(n503 - r["fail_503"]) <= tol, f"{r['vus']} VUs: nginx vio {n503} respuestas 503 y k6 contó {r['fail_503']}")
        print(f"   {r['vus']:>5} {k_ok:>7} {n200:>9} {a} {r['fail_503']:>5} {n503:>9} {b}")
    if skipped:
        print(f"   Omitido para {len(skipped)} nivel(es): el gateway actual no tiene registro de esas ejecuciones.")


def repeatability(rows: list[dict], rep: list[dict]) -> None:
    print("\nReproducibilidad (segunda ejecución, results/_repeat)")
    print(f"   {'VUs':>5} {'fallos % 1ª':>11} {'fallos % 2ª':>11} {'ok req/s 1ª':>11} {'ok req/s 2ª':>11} {'avg ms 1ª':>10} {'avg ms 2ª':>10}")
    by = {r["vus"]: r for r in rows}
    for b in rep:
        a = by.get(b["vus"])
        if not a:
            continue
        v = check((a["failed_pct"] == 0) == (b["failed_pct"] == 0), f"{b['vus']} VUs: una ejecución tuvo errores y la otra no")
        thr = check(abs(a["ok_throughput_rps"] - b["ok_throughput_rps"]) <= 0.15 * a["ok_throughput_rps"],
                    f"{b['vus']} VUs: el throughput exitoso difiere más de 15 % entre ejecuciones")
        print(f"   {b['vus']:>5} {a['failed_pct']:>11.2f} {b['failed_pct']:>11.2f} {v} {a['ok_throughput_rps']:>8.1f} {b['ok_throughput_rps']:>11.1f} {thr} {a['avg_ms']:>7.2f} {b['avg_ms']:>10.2f}")


def deliverables(rows: list[dict]) -> None:
    print("\nCSV, README y gráfica contra los JSON crudos")
    with (PUBLISHED / "results.csv").open(encoding="utf-8") as f:
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
    last_ok, first_bad = knee(rows)
    stated = f"entre {last_ok:,} y {first_bad:,} usuarios".replace(",", " ")
    print(f"   {check(stated in md, f'el README no dice que la rodilla está {stated}')} rodilla del README: {stated}")
    svg = (PUBLISHED / "performance_curve.svg").read_text(encoding="utf-8")
    n_points = svg.count('r="4.5"')
    print(f"   {check(n_points == len(rows), f'la gráfica tiene {n_points} puntos y hay {len(rows)} niveles')} gráfica: {n_points} puntos")


def compare(local: list[dict], pub: list[dict]) -> None:
    """Lo que debe coincidir en cualquier equipo. Los milisegundos y el punto exacto de la rodilla dependen del equipo."""
    print("\nComparación con los resultados publicados")
    print(f"   {'VUs':>5} {'fallos % pub':>12} {'fallos % aquí':>13} {'ok req/s pub':>12} {'ok req/s aquí':>13} {'avg ms pub':>10} {'avg ms aquí':>11}")
    by = {r["vus"]: r for r in pub}
    pub_last_ok, pub_first_bad = knee(pub)
    for b in local:
        a = by.get(b["vus"])
        if not a:
            continue
        mark = ""
        if pub_last_ok is not None and b["vus"] <= pub_last_ok * 0.75:
            # Bien por debajo de la rodilla publicada: no debe haber fallas y el throughput debe ser el mismo.
            mark = check(b["failed_pct"] == 0, f"{b['vus']} VUs: hay fallas en un nivel que debería pasar limpio") + " " + \
                   check(abs(a["ok_throughput_rps"] - b["ok_throughput_rps"]) <= 0.05 * a["ok_throughput_rps"],
                         f"{b['vus']} VUs: el throughput exitoso difiere más de 5 % del publicado")
        print(f"   {b['vus']:>5} {a['failed_pct']:>12.2f} {b['failed_pct']:>13.2f} {a['ok_throughput_rps']:>12.1f} {b['ok_throughput_rps']:>13.1f} {a['avg_ms']:>10.1f} {b['avg_ms']:>11.1f}  {mark}")

    saturated = [r for r in local if r["fail_503"] > 0]
    if saturated:
        top = max(r["requests"] - r["failed_requests"] for r in saturated)
        print(f"   {check(top <= GATEWAY_PORTS + 5, f'hubo {top} respuestas 200 en un nivel saturado: supera los puertos del gateway')} "
              f"tope de respuestas 200 con el gateway saturado: {top} (puertos del gateway: {GATEWAY_PORTS})")
    last_ok, first_bad = knee(local)
    here = f"entre {last_ok} y {first_bad}" if first_bad else f"por encima de {last_ok} (sin errores en los niveles probados)"
    print(f"   Rodilla publicada: entre {pub_last_ok} y {pub_first_bad} usuarios · en esta ejecución: {here}")
    if (last_ok, first_bad) != (pub_last_ok, pub_first_bad):
        notes.append("La rodilla de esta ejecución no cae en el mismo intervalo que la publicada. Es esperable en otro equipo: "
                     "los errores aparecen cuando una prueba supera ~28 000 peticiones en 30 s, y eso depende de la velocidad de la máquina.")


def main() -> None:
    pub = load(PUBLISHED)
    if len(sys.argv) > 1:
        folder = pathlib.Path(sys.argv[1]).resolve()
        rows = load(folder)
        if not rows:
            raise SystemExit(f"No hay resultados en {folder}. Ejecute primero run_sweep.sh.")
        print(f"Ejecución propia: {folder}\n")
        arithmetic(rows)
        cross_check(rows, gateway_log())
        compare(rows, pub)
    else:
        print(f"Resultados publicados: {PUBLISHED}\n")
        arithmetic(pub)
        cross_check(pub, gateway_log())
        rep = load(PUBLISHED / "_repeat")
        if rep:
            repeatability(pub, rep)
        deliverables(pub)
    for n in notes:
        print(f"\nNota: {n}")
    print("\n" + ("TODO COHERENTE." if not problems else "PROBLEMAS:\n - " + "\n - ".join(problems)))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
