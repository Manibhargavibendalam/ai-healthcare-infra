# dashboards/

Provisioned Grafana dashboards live here (M3). One dashboard,
`healthcare.json`, with tiles for: API health/error rate/latency, queue depth,
worker processing rate, failed jobs, DB reachability, EHR failure count,
deployment state. If a tile can't answer "what is failing right now", it
doesn't belong on the dashboard.
