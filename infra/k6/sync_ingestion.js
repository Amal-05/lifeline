import http from 'k6/http';
import { check } from 'k6';
import { SharedArray } from 'k6/data';
import exec from 'k6/execution';

const base = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const corpusPath = __ENV.SYNC_EVENTS || './reports/k6-sync/events.jsonl';
const events = new SharedArray('signed synthetic sync bundles', () =>
  open(corpusPath).trim().split('\n').map((line) => JSON.parse(line)));
const rate = Number(__ENV.EVENTS_PER_SECOND || 1000);
const duration = __ENV.DURATION || '60s';

export const options = {
  scenarios: {
    sync_ingestion: {
      executor: 'constant-arrival-rate',
      rate,
      timeUnit: '1s',
      duration,
      preAllocatedVUs: Math.max(rate, 100),
      maxVUs: Math.max(rate * 5, 500),
      gracefulStop: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const index = exec.scenario.iterationInTest;
  if (index >= events.length) return;
  const bundle = events[index];
  const response = http.post(`${base}/api/v1/sync`, JSON.stringify(bundle), {
    headers: { 'Content-Type': 'application/json' }, timeout: '30s',
  });
  check(response, {
    'sync returns 200': (r) => r.status === 200,
    'event accepted': (r) => r.status === 200 && r.json('accepted_ids').includes(bundle.events[0].event_id),
  });
}

export function handleSummary(data) {
  return {
    'reports/k6-sync/k6-summary.json': JSON.stringify(data, null, 2),
    stdout: `sync load: ${data.metrics.http_reqs.values.rate.toFixed(1)} req/s · p95 ${data.metrics.http_req_duration.values['p(95)'].toFixed(1)} ms · failures ${(data.metrics.http_req_failed.values.rate * 100).toFixed(2)}%\n`,
  };
}
