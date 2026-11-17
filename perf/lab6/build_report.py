"""Laboratorio 6 · construye la curva de desempeño a partir de los resultados de k6.

Lee perf/lab6/results/vus_*.json (uno por nivel de carga) y genera:
  - perf/lab6/results/results.csv           tabla con todos los niveles
  - perf/lab6/results/performance_curve.svg  curva: usuarios vs. tiempo de respuesta y % de error

Uso:  python perf/lab6/build_report.py
"""
import csv
import json
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
RESULTS = HERE / "results"
FIELDS = [
    "vus", "ramp_up", "requests", "failed_requests", "failed_pct", "fail_connection", "fail_503", "fail_other_status",
    "first_fail_s", "last_fail_s", "throughput_rps", "ok_throughput_rps",
    "avg_ms", "med_ms", "p95_ms", "max_ms", "ok_avg_ms", "ok_med_ms", "ok_p95_ms",
]


def load() -> list[dict]:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in RESULTS.glob("vus_*.json")]
    return sorted(rows, key=lambda r: r["vus"])


def find_knee(rows: list[dict]) -> tuple[dict | None, dict | None]:
    """Último nivel sin errores y primer nivel con http_req_failed > 0 (criterio del laboratorio)."""
    last_ok, first_bad = None, None
    for r in rows:
        if r["failed_pct"] > 0:
            first_bad = r
            break
        last_ok = r
    return last_ok, first_bad


def nice_max(v: float) -> float:
    """Tope "redondo" del eje (1, 2 o 5 por una potencia de 10)."""
    if v <= 0:
        return 1.0
    mag = 10 ** len(str(int(v))) / 10
    for m in (1, 2, 5, 10):
        if v <= m * mag:
            return m * mag
    return 10 * mag


def svg(rows: list[dict], last_ok: dict | None, first_bad: dict | None) -> str:
    w, h, left, right, top, bottom = 960, 560, 80, 80, 96, 70
    pw, ph = w - left - right, h - top - bottom
    # Eje X logarítmico: los niveles van de 1 a miles de usuarios y en escala lineal
    # todos los puntos anteriores a la rodilla quedarían amontonados en el origen.
    lx_max = math.log10(max(r["vus"] for r in rows))
    y_max = nice_max(max(r["avg_ms"] for r in rows))
    e_max = max(nice_max(max(r["failed_pct"] for r in rows)), 1.0)

    def x(v: float) -> float:
        return left + pw * math.log10(max(v, 1)) / lx_max

    def y(v: float) -> float:
        return top + ph * (1 - v / y_max)

    def ye(v: float) -> float:
        return top + ph * (1 - v / e_max)

    blue, red, ink, muted, grid = "#2563eb", "#dc2626", "#111827", "#6b7280", "#e5e7eb"
    o = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="Segoe UI, Arial, sans-serif">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="{left}" y="30" font-size="19" font-weight="700" fill="{ink}">Curva de desempeño · GET /api/leaderboard/top (JokerArena)</text>',
        f'<text x="{left}" y="50" font-size="12.5" fill="{muted}">k6 → API Gateway → leaderboard-stats-ms → Redis / Neo4j · 30 s por nivel de carga</text>',
        f'<line x1="{left}" y1="72" x2="{left + 30}" y2="72" stroke="{blue}" stroke-width="2.5"/>',
        f'<text x="{left + 36}" y="76" font-size="12" fill="{ink}">http_req_duration (avg), eje izquierdo</text>',
        f'<line x1="{left + 290}" y1="72" x2="{left + 320}" y2="72" stroke="{red}" stroke-width="2" stroke-dasharray="6 4"/>',
        f'<text x="{left + 326}" y="76" font-size="12" fill="{ink}">http_req_failed, eje derecho</text>',
    ]
    for i in range(6):
        gy = top + ph * i / 5
        o.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{left + pw}" y2="{gy:.1f}" stroke="{grid}"/>')
        o.append(f'<text x="{left - 10}" y="{gy + 4:.1f}" font-size="12" text-anchor="end" fill="{blue}">{y_max * (5 - i) / 5:,.0f}</text>')
        o.append(f'<text x="{left + pw + 10}" y="{gy + 4:.1f}" font-size="12" fill="{red}">{e_max * (5 - i) / 5:.0f} %</text>')
    last_tick = -99.0
    for r in rows:  # una marca por nivel probado (se omite la etiqueta si no cabe)
        gx = x(r["vus"])
        o.append(f'<line x1="{gx:.1f}" y1="{top + ph}" x2="{gx:.1f}" y2="{top + ph + 6}" stroke="{muted}"/>')
        if gx - last_tick >= 34:
            o.append(f'<text x="{gx:.1f}" y="{top + ph + 22}" font-size="12" text-anchor="middle" fill="{ink}">{r["vus"]}</text>')
            last_tick = gx
    o.append(f'<line x1="{left}" y1="{top + ph}" x2="{left + pw}" y2="{top + ph}" stroke="{muted}"/>')
    o.append(f'<text x="{left + pw / 2}" y="{h - 18}" font-size="13" text-anchor="middle" fill="{ink}">Usuarios concurrentes (VUs) · escala logarítmica</text>')
    o.append(f'<text transform="translate(22 {top + ph / 2}) rotate(-90)" font-size="13" text-anchor="middle" fill="{blue}">Tiempo de respuesta promedio (ms)</text>')
    o.append(f'<text transform="translate({w - 16} {top + ph / 2}) rotate(90)" font-size="13" text-anchor="middle" fill="{red}">Peticiones fallidas (%)</text>')

    if last_ok and first_bad:
        x0, x1 = x(last_ok["vus"]), x(first_bad["vus"])
        o.append(f'<rect x="{x0:.1f}" y="{top}" width="{x1 - x0:.1f}" height="{ph}" fill="#f59e0b" opacity="0.2"/>')
        o.append(f'<text x="{x0 - 8:.1f}" y="{top + 20}" font-size="13" font-weight="700" text-anchor="end" fill="#b45309">Rodilla</text>')
        o.append(f'<text x="{x0 - 8:.1f}" y="{top + 37}" font-size="12" text-anchor="end" fill="#b45309">entre {last_ok["vus"]} y {first_bad["vus"]} usuarios</text>')

    err = " ".join(f"{x(r['vus']):.1f},{ye(r['failed_pct']):.1f}" for r in rows)
    o.append(f'<polyline points="{err}" fill="none" stroke="{red}" stroke-width="2" stroke-dasharray="6 4"/>')
    for r in rows:
        o.append(f'<circle cx="{x(r["vus"]):.1f}" cy="{ye(r["failed_pct"]):.1f}" r="3.5" fill="{red}"/>')
    avg = " ".join(f"{x(r['vus']):.1f},{y(r['avg_ms']):.1f}" for r in rows)
    o.append(f'<polyline points="{avg}" fill="none" stroke="{blue}" stroke-width="2.5"/>')
    for r in rows:
        cx, cy = x(r["vus"]), y(r["avg_ms"])
        o.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="{blue}" stroke="#ffffff" stroke-width="1.5"/>')
        if r["avg_ms"] >= y_max * 0.03:  # los valores pegados al eje van en la tabla
            o.append(f'<text x="{cx - 9:.1f}" y="{cy - 7:.1f}" font-size="11.5" font-weight="600" text-anchor="end" fill="{blue}">{r["avg_ms"]:,.0f} ms</text>')
    o.append("</svg>")
    return "\n".join(o)


def main() -> None:
    rows = load()
    if not rows:
        raise SystemExit("No hay resultados en perf/lab6/results. Ejecute primero run_sweep.sh.")
    with (RESULTS / "results.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: (round(r[k], 2) if isinstance(r.get(k), float) else r.get(k)) for k in FIELDS})
    last_ok, first_bad = find_knee(rows)
    (RESULTS / "performance_curve.svg").write_text(svg(rows, last_ok, first_bad), encoding="utf-8")

    def n(v, fmt="{:.2f}"):
        return "-" if v is None else fmt.format(v)

    print(f"{'VUs':>5} {'req':>7} {'ok req/s':>9} {'avg ms':>9} {'ok avg':>9} {'ok p95':>9} {'fallos %':>8} {'sin resp':>8} {'503':>6} {'otros':>5} {'fallas (s)':>13}")
    for r in rows:
        window = "-" if r["first_fail_s"] is None else f"{r['first_fail_s']:.1f}-{r['last_fail_s']:.1f}"
        print(f"{r['vus']:>5} {r['requests']:>7} {r['ok_throughput_rps']:>9.1f} {r['avg_ms']:>9.2f} {n(r['ok_avg_ms']):>9} {n(r['ok_p95_ms']):>9} "
              f"{r['failed_pct']:>8.2f} {r['fail_connection']:>8} {r['fail_503']:>6} {r['fail_other_status']:>5} {window:>13}")
    if first_bad and last_ok:
        print(f"\nRodilla: entre {last_ok['vus']} y {first_bad['vus']} usuarios concurrentes "
              f"(último nivel sin errores: {last_ok['vus']}; primer nivel con errores: {first_bad['vus']}, {first_bad['failed_pct']:.2f} %).")
    elif first_bad:
        print(f"\nHay errores desde el primer nivel probado ({first_bad['vus']} usuarios).")
    else:
        print("\nNingún nivel presentó errores: hay que probar con más usuarios para encontrar la rodilla.")


if __name__ == "__main__":
    main()
