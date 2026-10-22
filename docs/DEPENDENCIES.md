# Dependency and responsibility map

Advanced Fabric is provider-neutral: a minimal observation installation needs
Kubernetes and the packaged runtime, while each provider integration remains
optional and bounded.

| Component | Required | What Advanced Fabric consumes or produces | What remains outside this project |
| --- | --- | --- | --- |
| Kubernetes API | Yes | Reads Nodes and declared network resources; publishes AdvFab CRDs, status, Leases, and bounded observation state | Node lifecycle, scheduling, workload reconciliation, API availability |
| Helm 3 | Install time | Renders CRDs, RBAC, controller, agents, and optional adapters | GitOps reconciliation and release promotion policy |
| Linux networking | For node evidence | Reads interfaces, routes, nexthops, counters, and reachability outcomes | Kernel configuration and host lifecycle unless guarded apply is separately authorized |
| Cilium/Hubble | Optional | Reads datapath mode, service-flow evidence, BGP and policy facts exposed by the deployment | Cilium installation, upgrades, policy ownership, and raw flow retention |
| FRR | Optional | Reads BGP peers, routes, counters, and event evidence; applies only through an authorized provider | FRR configuration ownership, ASN allocation, peer credentials, and underlay reachability |
| RouterOS | Optional | Observes declared route domains and performs checksum-bound operations when enabled | Router lifecycle, firewall/NAT, credentials, public addressing, and physical links |
| Gateway API | Optional | Reads Gateway and route state for the virtual Ingress adapter and observations | Gateway controller, listeners, certificates, Routes, Services, and backends |
| DNS/DoH | Optional | Provides an authoritative Kubernetes DNS/DoH capability and measures declared DNS dependencies | Parent-zone delegation, registrar, upstream resolver, and public DNS provider credentials |
| Prometheus-compatible storage | Optional | Receives measurement-only series and can provide bounded historical queries | Storage sizing, retention, backup, access control, and raw telemetry authority |
| Public Edge Manager | Optional consumer | Reads fresh provider-neutral `NetworkPathAssessment` evidence | Public edge eligibility, DNS publication, external probes, and failover policy |
| Headlamp client | Optional consumer | Discovers and reads the Observation API | UI installation, authentication, authorization, and release lifecycle |

## Credential boundary

AdvFab CRD status, observation payloads, logs, examples, tests, and release
assets contain no credentials. Provider credentials are mounted only into the
specific adapter that needs them and are referenced by Kubernetes Secret name,
never copied into values or status.

## Failure isolation

An unavailable optional integration changes only its declared evidence scope.
For example, absent Hubble evidence cannot be replaced with an active-probe
value, and an unavailable Public Edge consumer does not stop measurement. The
result is `partial`, `not-observed`, `Unknown`, or `Stale` according to the
contract—not a fabricated zero or a component-wide healthy state.
