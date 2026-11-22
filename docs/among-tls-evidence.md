# Among ingress TLS evidence

`advancedFabric.networkQuality.amongTlsTargets` is opt-in (`[]`). Static
`tlsTargets` remains available; both lists together permit four uniquely named
targets. Each dynamic entry supplies `name`, `sourceNodes`, optional existing TLS
probe policy fields, and `discovery` containing `source: AmongCluster`,
`clusterRef`, SPIFFE `serviceRef`, `protocol`, stable `endpointId`, and exact
`advertisementRef` / `importedServiceRef` `{namespace,name,uid}` bindings.

The existing controller GETs each distinct reference once per reconcile round.
It checks identities, generations, Ready imported observation, explicit typed
HTTPS endpoint, publication timestamp/TTL, withdrawal and deletion. Namespace
Roles grant only GET for the named resources. No peer discovery, QUIC conversion,
credential lookup, alternate endpoint or stale-address fallback occurs.

Resolved endpoint address, hostname, port and path enter the existing evidence
plan. Its validity ends at the earlier of measurement freshness and advertisement
expiry. Existing host/pod collectors consume only a current plan. A failed plan
read or expired plan produces no dynamic connections. The path identity includes
advertisement/import UID, endpoint ID and revision, excluding heartbeat resource
versions. The existing configuration digest also binds the endpoint, so previous
measurements cannot establish readiness for a changed endpoint/revision.

Service NPA subjects come from the SPIFFE `/ns/<namespace>/service/<name>`, not
the peering namespace. The NPA name stays `tls-` plus the first 24 SHA256 hex
characters of `sourceNode/name`. Resolution failure explicitly writes state
`Stale` and `EvidenceReady=False` on that same NPA and clears observation validity;
`NotReady` is not an existing CRD state. Valid NPA evidence is capped at the Among
TTL even when the controller subsequently stops.

Runtime acceptance still requires reviewed exact UID bindings and a controlled
canary: observe primary address A, change the source primary to B without changing
consumer references, verify a new plan/digest/probe/NPA, then revoke or expire the
advertisement and verify the old Ready evidence is withdrawn. Static readiness,
source CI, or a successful chart publication does not establish that live result.
