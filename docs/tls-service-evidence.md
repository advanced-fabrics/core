# Endpoint-scoped TLS evidence

`tls-transfer-v1` measures a complete bounded strict-TLS HTTP transfer, separately
from TCP-connect `path-quality-v1`. `networkQuality.tlsTargets` is empty by
default. Targets require a reviewed Service identity (`namespace/name`), literal
endpoint, TLS server name, assigned source nodes and bounded request sizes.
The existing host/pod collectors receive the same immutable target declaration.

The controller publishes v1alpha2 Service NetworkPathAssessments for each
configured target and assigned active source node. Scope includes endpoint,
port, SNI, request path and sizes. Ready requires every configured size from
both host and pod planes, fresh matching transfer records, and complete success.
TCP success, a different endpoint, a different source, stale records, or an
incomplete large transfer cannot satisfy this scope. Validity uses the oldest
accepted record. Changing an endpoint immediately makes its old observations
ineligible on the next reconciliation; removed targets' old assessments expire.

Consumers must match the entire Service and path scope plus freshness before
using this evidence. This does not certify arbitrary services on the same node,
does not mutate IPAM or routes, and does not enable global quality enforcement.
Use the configured service's admission/withdrawal policy, retain a separately
verified fallback, and prove recovery by real application calls.
