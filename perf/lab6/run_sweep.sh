#!/usr/bin/env bash
# Laboratorio 6 · ejecuta performance_test.js una vez por nivel de carga.
#   bash perf/lab6/run_sweep.sh                 niveles por defecto (unos 25 minutos)
#   bash perf/lab6/run_sweep.sh 1 50 2000       niveles indicados
# Variables:
#   OUT_DIR   (perf/lab6/results/_local)  carpeta de resultados. Los resultados publicados están en
#                   perf/lab6/results y no se tocan: cada ejecución propia va a _local.
#   RAMP_UP   (1s)  los usuarios entran repartidos en ese tiempo, como el "Ramp-Up Period" de JMeter.
#   COOLDOWN  (70)  pausa en segundos entre niveles. Debe superar los 60 s que el gateway tarda en
#                   liberar las conexiones TCP cerradas (TIME_WAIT); si no, un nivel contamina al siguiente.
# Después:  python perf/lab6/build_report.py perf/lab6/results/_local
#           python perf/lab6/verify_results.py perf/lab6/results/_local
set -u
cd "$(dirname "$0")/../.."
K6="${K6:-k6}"
command -v "$K6" >/dev/null 2>&1 || K6="/c/Program Files/k6/k6.exe"
command -v "$K6" >/dev/null 2>&1 || { echo "No se encontró k6. Instálelo: https://grafana.com/docs/k6/latest/set-up/install-k6/"; exit 1; }
export OUT_DIR="${OUT_DIR:-perf/lab6/results/_local}"
LEVELS=("$@")
[ ${#LEVELS[@]} -eq 0 ] && LEVELS=(1 50 100 200 300 400 500 600 800 1000 1500 2000 3000)
mkdir -p "$OUT_DIR"
echo "Resultados en: $OUT_DIR"
for vus in "${LEVELS[@]}"; do
  echo "=== $vus usuarios concurrentes ==="
  "$K6" run --quiet -e VUS="$vus" -e RAMP_UP="${RAMP_UP:-1s}" -e OUT_DIR="$OUT_DIR" perf/lab6/performance_test.js 2>&1     | grep -E "vus=|http_req_|solo respuestas|fallas entre"
  sleep "${COOLDOWN:-70}"
done
