# Evidence and network scenario matrix

This nine-cell matrix is the minimum deterministic test and review model for an
AdvFab component. The axes are independent:

- **network reality:** healthy, degraded, or failed;
- **evidence coverage:** sparse, sufficient, or rich.

| Network reality \ Evidence | Sparse: one scope or stale baseline | Sufficient: current required scopes | Rich: current alternatives and history |
| --- | --- | --- | --- |
| **Healthy** | Publish `Partial` or `Unknown`; preserve the successful observation but make no comparative O/S/I claim. | Publish fresh eligible evidence for the measured scope; leave unmeasured dimensions null. | Publish comparable path and temporal evidence with confidence and provenance; do not infer causality without an intervention. |
| **Degraded** | Expose the observed degradation and missing evidence separately; request bounded measurement work. | Diagnose only the dimensions supported by current evidence and emit an observe-only recommendation. | Compare same-scope alternatives, retain event history, and evaluate a guarded recommendation without hiding uncertainty. |
| **Failed** | Mark the subject unavailable or stale; never convert absence to a numeric zero or healthy default. | Publish the explicit failure outcome and keep unrelated scopes available. | Isolate the failed path/domain, show verified alternatives, and validate any separately authorized action with the same measurement definition. |

## Deterministic facts

Tests model network state with facts rather than a subjective quality score:

| State | Representative facts |
| --- | --- |
| Healthy | fresh reachability, accepted protocol response, stable route/peer state, current dependency evidence |
| Degraded | loss, elevated latency, churn, partial reachability, stale dependency, or one failed plane |
| Failed | explicit rejection, no viable same-scope path, withdrawn route, failed required dependency, or expired validity |

Evidence coverage changes what can be claimed, not what happened in the
network. Sparse evidence MUST reduce certainty or leave a field unknown; it
MUST NOT improve or worsen the observed value by convention.

## Review assertions

For each affected cell, assertions should cover:

- subject and scope identity;
- observed and validity timestamps;
- raw value, unit, procedure, and failure semantics;
- missingness distinct from zero;
- confidence distinct from the measured value;
- recommendation without implicit mutation; and
- post-action validation when guarded apply is explicitly enabled.

Use unit fixtures, Helm renders, or an isolated test cluster. Do not inject
faults into production to complete this matrix, and keep production addresses,
credentials, packet contents, and raw telemetry out of Git.
