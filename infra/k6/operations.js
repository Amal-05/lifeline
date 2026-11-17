import http from 'k6/http';
import { check } from 'k6';

export const options = {
  scenarios: { operations_read: { executor: 'ramping-vus', startVUs: 1,
    stages: [{ duration: '20s', target: 50 }, { duration: '40s', target: 100 }, { duration: '20s', target: 0 }] } },
  thresholds: { http_req_failed: ['rate<0.01'], http_req_duration: ['p(95)<500'] },
};

const base = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const email = __ENV.DEMO_EMAIL || 'coordinator@example.com';
const password = __ENV.DEMO_PASSWORD || 'demo-only-change-me';
const maxVUs = Number(__ENV.MAX_VUS || 100);
options.scenarios.operations_read.stages[0].target = Math.ceil(maxVUs / 2);
options.scenarios.operations_read.stages[1].target = maxVUs;
export function setup() {
  const response = http.post(`${base}/api/v1/auth/login`, JSON.stringify({ email, password }),
    { headers: { 'Content-Type': 'application/json' } });
  check(response, { 'demo login succeeds': (r) => r.status === 200 });
  return { token: response.json('access_token') };
}
export default function (data) {
  const response = http.get(`${base}/api/v1/incidents?limit=50`,
    { headers: { Authorization: `Bearer ${data.token}` }, timeout: '5s' });
  check(response, { 'incident list succeeds': (r) => r.status === 200 });
}
