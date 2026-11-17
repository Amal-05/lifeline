# Privacy and safety checklist

- [x] Repository fixtures and simulator inputs are synthetic; no real responder/household data is committed.
- [x] Household contact name, phone, household size, and vulnerability tags are encrypted with SecretBox before database persistence. Production startup fails if `REGISTRY_ENCRYPTION_KEY` is missing.
- [x] Household endpoint requires explicit consent and coordinator/admin authorization; only the H3 cell is exposed to the aggregate summary.
- [x] Registrations expire after one year and expired records are purged on registration/summary requests.
- [x] Public hazard layers can be loaded through an administrator-only risk import route with a source label; the bundled demonstration layer is synthetic.
- [x] Demo risk layers identify themselves as synthetic and do not imply a live forecast.
- [x] SOS media is not persisted by the API; device-side outbox media retention is documented.
- [ ] Production secrets must be injected by the deployment secret manager; rotate JWT and registry keys and test key recovery before production.
- [ ] Set a retention/deletion schedule approved by the data controller and run key-controlled deletion/export processes.
- [ ] Add account provisioning, MFA, rate limits, consent receipt, access review, and regional data-residency review before real deployments.
- [ ] Publish a plain-language privacy notice and emergency-service limitations in all supported languages.
- [ ] Verify no screenshots, crash reports, analytics, logs, or backups expose raw registration contents; backups are encrypted at rest and access logged.

The checklist marks implementation items separately from production governance items. It is not a legal approval.
