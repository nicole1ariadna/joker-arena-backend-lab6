#!/usr/bin/env bash
# Laboratorio 6 · ejecuta performance_test.js una vez por nivel de carga.
#   bash perf/lab6/run_sweep.sh                 niveles por defecto
#   bash perf/lab6/run_sweep.sh 1 50 2000       niveles indicados
# Variables:
#   RAMP_UP   (1s)  los usuarios entran repartidos en ese tiempo, como el "Ramp-Up Period" de JMeter.
#   COOLDOWN  (70)  pausa en segundos entre niveles. Debe superar los 60 s que el gateway tarda en
#                   liberar las conexiones TCP cerradas (TIME_WAIT); si no, un nivel contamina al siguiente.
# Resultados: perf/lab6/results/vus_*.json  →  python perf/lab6/build_report.py
set -u
cd "$(dirname "$0")/../.."
K6="${K6:-k6}"
command -v "$K6" >/dev/null 2>&1 || K6="/c/Program Files/k6/k6.exe"
LEVELS=("$@")
[ ${#LEVELS[@]} -eq 0 ] && LEVELS=(1 50 100 200 300 400 500 600 800 1000 1500 2000 3000)
mkdir -p perf/lab6/results
for vus in "${LEVELS[@]}"; do
  echo "=== $vus usuarios concurrentes ==="
  "$K6" run --quiet -e VUS="$vus" -e RAMP_UP="${RAMP_UP:-1s}" perf/lab6/performance_test.js 2>&1 \
    | grep -E "vus=|http_req_|solo respuestas|fallas entre"
  sleep "${COOLDOWN:-70}"
done
