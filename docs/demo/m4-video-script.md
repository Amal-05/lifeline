# M4 demo video script (about 4 minutes)

**0:00–0:30 — Context.** Show the Lifeline field client offline. Explain that all records in this demo are synthetic and that official emergency channels remain primary.

**0:30–1:10 — Offline request.** Submit a two-person synthetic medical SOS with a manual location, then switch the browser offline and reload. Show that the signed request remains queued.

**1:10–1:55 — Mesh and sync.** Show the M3 100-node simulation summary and a three-hop gateway path. State clearly that physical device testing is still required. Restore connectivity and show the sync acknowledgement.

**1:55–2:45 — Triage dashboard.** Sign into `/dashboard`, show urgency explanations, review candidate availability, incident status, and the synthetic H3 risk map. Do not show real household information.

**2:45–3:25 — Registration privacy.** Register the synthetic household example, show the encrypted status and H3 aggregate. Confirm no contact details are returned by the API response.

**3:25–4:00 — Resilience.** Show simulator results, k6 report artifact, and the backup/restore rehearsal output. End with limitations: synthetic hazard data, no licensed live basemap, no production routing, and device-lab verification pending.
