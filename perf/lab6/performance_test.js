// Laboratorio 6 · Performance (opción 2: k6)
// Funcionalidad: ranking global de JokerArena.
//   k6 → API Gateway (nginx :8080) → leaderboard-stats-ms → Redis (caché) / Neo4j
//
// Un nivel de carga por ejecución (equivale a "Number of Threads" de JMeter):
//   k6 run -e VUS=50 perf/lab6/performance_test.js
// Variables: VUS (usuarios concurrentes), DURATION (por defecto 30s),
//            RAMP_UP (por defecto 0s = todos los usuarios arrancan a la vez; "1s" = Ramp-Up de JMeter),
//            BASE_URL (por defecto http://localhost:8080), OUT_DIR (carpeta de resultados).
import http from 'k6/http';
import { sleep, check } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const VUS = Number(__ENV.VUS || 1);
const DURATION = __ENV.DURATION || '30s';
const RAMP_UP = __ENV.RAMP_UP || '0s';
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';
const OUT_DIR = __ENV.OUT_DIR || 'perf/lab6/results';

// Clasificación de las peticiones fallidas (http_req_failed solo da el total).
const failConn = new Counter('fail_connection'); // status 0: no hubo respuesta HTTP (conexión rechazada, reset, timeout)
const fail503 = new Counter('fail_503'); // el gateway no pudo llegar al microservicio
const failOther = new Counter('fail_other_status'); // cualquier otro código >= 400
const failAt = new Trend('fail_at_s'); // segundo de la prueba en que ocurrió cada falla

export const options = {
  scenarios: {
    load: {
      executor: 'ramping-vus',
      startVUs: RAMP_UP === '0s' ? VUS : 0,
      stages: [
        { duration: RAMP_UP, target: VUS }, // number of concurrent virtual users
        { duration: DURATION, target: VUS }, // test duration
      ],
      gracefulRampDown: '0s',
      gracefulStop: '30s',
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)'],
  // Umbral que siempre se cumple: solo sirve para que el resumen incluya el tiempo de las respuestas exitosas.
  thresholds: { 'http_req_duration{expected_response:true}': ['max>=0'] },
};

export function setup() {
  return { start: Date.now() };
}

export default function (data) {
  const res = http.get(`${BASE_URL}/api/leaderboard/top?limit=10`);

  check(res, {
    'status is 200': (r) => r.status === 200,
  });

  if (res.status !== 200) {
    if (res.status === 0) failConn.add(1);
    else if (res.status === 503) fail503.add(1);
    else failOther.add(1);
    failAt.add((Date.now() - data.start) / 1000);
    if (__VU <= 2 && __ITER < 3) console.warn(`falla: status=${res.status} error="${res.error}"`);
  }

  sleep(1);
}

// Guarda el resumen del nivel en JSON (para construir la curva) y lo muestra en consola.
export function handleSummary(data) {
  const m = data.metrics;
  const d = m.http_req_duration.values;
  const okD = (m['http_req_duration{expected_response:true}'] || { values: {} }).values;
  const count = (name) => (m[name] ? m[name].values.count : 0);
  const reqs = m.http_reqs.values.count;
  const failed = Math.round(m.http_req_failed.values.rate * reqs);
  const seconds = data.state.testRunDurationMs / 1000;
  const at = m.fail_at_s ? m.fail_at_s.values : null;
  const row = {
    vus: VUS,
    ramp_up: RAMP_UP,
    ended_at: new Date().toISOString(), // para cruzar esta ejecución con el log del gateway
    requests: reqs,
    failed_requests: failed,
    failed_pct: reqs ? (failed / reqs) * 100 : 0,
    fail_connection: count('fail_connection'),
    fail_503: count('fail_503'),
    fail_other_status: count('fail_other_status'),
    first_fail_s: at ? at.min : null,
    median_fail_s: at ? at.med : null,
    last_fail_s: at ? at.max : null,
    throughput_rps: reqs / seconds, // todas las peticiones
    ok_throughput_rps: (reqs - failed) / seconds, // solo las respondidas con 200
    avg_ms: d.avg, // todas las peticiones (incluye fallidas): es el http_req_duration que pide la guía
    med_ms: d.med,
    p95_ms: d['p(95)'],
    max_ms: d.max,
    ok_avg_ms: okD.avg ?? null, // solo las respondidas con 200
    ok_med_ms: okD.med ?? null,
    ok_p95_ms: okD['p(95)'] ?? null,
  };
  const f = (n) => (n === null || n === undefined ? '-' : n.toFixed(2));
  const text =
    `\n  vus=${VUS} ramp_up=${RAMP_UP}  requests=${reqs}  throughput=${f(row.throughput_rps)} req/s (ok: ${f(row.ok_throughput_rps)} req/s)\n` +
    `  http_req_duration.............: avg=${f(d.avg)}ms min=${f(d.min)}ms med=${f(d.med)}ms max=${f(d.max)}ms p(95)=${f(d['p(95)'])}ms\n` +
    `    { solo respuestas 200 }.....: avg=${f(okD.avg)}ms med=${f(okD.med)}ms p(95)=${f(okD['p(95)'])}ms\n` +
    `  http_req_failed...............: ${f(row.failed_pct)}%  (${failed} = ${row.fail_connection} sin respuesta + ${row.fail_503} con 503 + ${row.fail_other_status} otros)\n` +
    (at ? `  fallas entre el segundo ${f(at.min)} y ${f(at.max)} (mediana ${f(at.med)})\n\n` : '\n');
  return {
    stdout: text,
    [`${OUT_DIR}/vus_${String(VUS).padStart(5, '0')}.json`]: JSON.stringify(row, null, 2),
  };
}
