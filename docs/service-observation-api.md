# AFEP: scoped Service observation read interface

Status: accepted source contract; additive observation API extension, not a new registry or controller.
Release: 1.0.0-rc.16; do not rebuild or relabel the rc.15 artifact.

The existing observation API only enumerated Node subjects. Applications and
operator clients needing the same TLS Service evidence had to read the formal
Kubernetes NPA API separately. Reuse the existing API process and ServiceAccount:

- `GET /api/v1/subjects?kind=Service` returns observed namespace/name identities.
- `GET /api/v1/subjects/service/<namespace>/<name>/snapshot` returns the actual
  formal `networking.advfab.org/v1alpha2` Service NPAs for that exact subject.
- Default subjects and Node snapshots remain compatible; no Node inventory lookup
  is required for a Service request. No new CLI binary, storage or credentials.

Each assessment preserves UID/generation/resourceVersion, subjectRef, full scope
(sourceNode, targetId, endpoint, SNI/path, sizes and targetConfigurationDigest),
observedAt/validUntil, raw EvidenceReady condition, serviceEvidence and pathEvidence.
`fresh` is calculated independently at request time even when the ten-second
read cache contains an older Ready condition. Expired evidence is Stale; missing
subjects/validity stay Unknown or fresh=false; deleting objects remain Deleting.
`reportedEvidenceReady` is the producer's raw condition, **not** an eligibility
or authorization verdict. Consumers must apply their existing exact-ref, scoped
identity and service-evidence policy; this API does not borrow another source.

One bounded NPA list (limit200) is coalesced through the existing cache. If the
Kubernetes response is paginated, `truncated=true` stays explicit; an incomplete
list must never be interpreted as a complete absence or a global Ready result.
Clients needing a known exact object can continue using its existing Kubernetes
GET API. Provider/read failures remain HTTP503 rather than cached successful empties.

The rc.15 NPA scope binds Among endpoint revisions through pathId and configuration
digest but does not contain plaintext advertisement/import UID lineage. This API
retains those actual observed fields and does not fabricate an ad/import join from
current desired configuration. Any later explicit lineage field belongs to the
NPA producer contract first, then can pass through here unchanged.

The API shares the existing internal network/authorization boundary. It adds no
public exposure or RBAC and never reads Secret values. Tests cover actual HTTP
requests, local/remote inventory separation, exact subject filtering, revision
identity, expiry/deletion, raw-condition separation and incomplete-list reporting.
