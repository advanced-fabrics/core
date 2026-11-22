# Bounded TLS transfer evidence (`tls-transfer-v1`)

A successful TCP connect does not establish that TLS records or an HTTP request
can cross the same path. The existing host/pod conformance collector can make
explicit, anonymous TLS GET measurements at two fixed request sizes. It publishes
`tlsTransfers` alongside existing path and DNS evidence in the same result
ConfigMap and Node Exporter textfile. No additional collector service is needed.

Targets are disabled by default. `TLS_PROBE_TARGETS` is a reviewed JSON array;
there is no endpoint discovery, DNS resolution, redirect following, authorization
header, client certificate, token lookup, or network configuration change in this
procedure. Existing Kubernetes credentials remain confined to the collector's
existing discovery/publication client and are never copied into target requests.

Example target (documentation addresses only):

```json
[{
  "name": "api-version",
  "targetService": "example/control-api",
  "endpoint": "192.0.2.10",
  "port": 443,
  "serverName": "api.example.test",
  "caFile": "/public-ca/ca.crt",
  "path": "/version",
  "pathId": "declared-service-vip",
  "sourceNodes": ["worker-a", "worker-b"],
  "required": true,
  "expectedStatuses": [200],
  "paddingBytes": [0, 2048],
  "timeoutSeconds": 2,
  "maximumTotalMs": 1000
}]
```

`endpoint` must be an IPv4/IPv6 literal. `serverName` is independently supplied
for strict certificate/hostname verification and the HTTP Host header. When
`caFile` is omitted, the system CA store is used; otherwise it must name a public
`.crt`/`.pem` certificate file. A service-account **CA certificate** may be used;
its token must never be read by this procedure. Query strings, custom headers,
credentials, and unknown target fields are rejected. Paths are explicit ASCII
absolute paths, not URLs.

`sourceNodes` defaults to an empty assignment: it performs no requests and
produces no successful evidence. A maximum of three explicit source nodes can be
assigned. Each assigned node executes the procedure in the existing collector's
host and/or pod plane. The pod plane describes the conformance Pod's network and
identity; it must not be presented as a measurement from every application Pod,
policy identity, or address pool on that node.

## Bounds and completion

- At most four targets, two distinct padding sizes per target (0–4096 bytes).
- Two concurrent transfers; one attempt per target/size per collector snapshot.
- Five-second maximum per transfer, with a shared twenty-second TLS-phase budget.
  Queued work that exhausts this budget fails without dialing.
- Request at most 8192 bytes. Response at most 32768 bytes, headers at most 8192.
  The extra byte used to detect overflow is never retained as evidence.
- Strict CA and hostname verification, TLS 1.2 minimum, HTTP/1.1 only, one GET, connection close.
  A successful status alone is insufficient: the bounded response must complete.
- Content-Length and connection-close response framing are supported. Chunked,
  duplicate-length, truncated, malformed, and oversized responses fail closed.
  There is no retry or fallback to a different path, address, protocol or CA.

`maximumTotalMs` is the separate service quality budget: a positive number at
most 5000, default 1000 milliseconds. It does not extend the socket deadline.
Consumers must require both `success` and `totalMs <= maximumTotalMs`; a transfer
that eventually completes after 3.3 seconds is not healthy under the default
service budget. Transfer success alone describes completion, not service quality.

The socket budget spans connect, TLS handshake, request and response. Each blocking
socket operation receives only the remaining deadline, including trickled reads.
The configured CA must be a local public-certificate mount; remote filesystems or
unbounded name resolution are not part of the procedure. Expected HTTP statuses
are declared per target; accepting an unauthenticated status tests that boundary,
not authenticated application functionality.

## Evidence contract

Every normal `tlsTransfers[]` record contains:

- Identity: `measurementDefinitionId: tls-transfer-v1`, `sourceNode`, `sourcePlane`,
  `targetId`, `targetService`, `endpoint`, `port`, `serverName`, `path`, `pathId`,
  `sourceNodes`, `required`, `paddingBytes`.
- Timing: `startedAt`, `observedAt` (UTC), `connectMs`, `handshakeMs`,
  `requestResponseMs`, `totalMs`. Unreached stages remain null.
- Outcome: `success`, `state` (`Succeeded` or `Failed`), `category`, `error`
  (exception class only), and `statusCode` when received.
- Size and source: `requestBytes`, `responseBytes`, `bodyBytes`, and the selected
  `sourceAddress`/`sourcePort` once connected.

Categories are `ok`, `configuration`, `deadline`, `tls`, `transport`, `http-status`,
`response-limit`, and `http-framing`. Invalid target configuration produces a
configuration-failure record without making target connections. Response bodies,
response headers, certificate contents and exception messages are not published.

`advanced_fabric_tls_transfer_success` is zero on every recorded failure; bounded
byte counts and total duration are exported with the same source/target/path/size
scope. Empty assignments and absent evidence are unknown, never a pass.

This definition supplements `path-quality-v1`; it does not turn TCP-connect
measurements into TLS measurements. Consumers must keep service/endpoint/source
scope and freshness. A failed explicitly required service target may reject that
service's measured path. It must not globally mark a node unreachable, withdraw
routes, choose an unmeasured alternate, or enable guarded apply. Compare padding
sizes on the same declared scope to investigate transfer degradation; size
sensitivity alone does not prove an MTU cause or authorize an MSS/MTU change.

### Declaration identity and changes

Each row includes `targetConfigurationDigest`: SHA-256 hex (no prefix) of UTF-8
`json.dumps(identity, sort_keys=True, separators=(',', ':'))`. `identity` contains
`name`, `targetService`, normalized-IP `endpoint`, `port` (default 443),
`serverName`, `path` (default `/version`), `pathId` (default name), `caFile`
(default null), sorted `expectedStatuses` (default [200]), sorted `paddingBytes`
(default [0,2048]), and sorted `sourceNodes` (default []). Consumers must match
this digest against the current declaration before accepting any old row.

`maximumTotalMs`, `timeoutSeconds`, and `required` are excluded: current quality
policy can reject existing measured facts without changing their identity.
Changing a CA file reference, expected statuses, path ID or endpoint invalidates
old evidence. Rotation of CA contents at the same path is not content-pinned by
this version; that requires a separately reviewed certificate-digest contract.
