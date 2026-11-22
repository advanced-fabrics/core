# Current Pod allocation evidence

Topology `nodes[].podCIDR` is declared legacy context, not a current Cilium
allocation authority. With `advancedFabric.controller.observeCiliumAllocations:
true`, each reconciliation reads CiliumNode objects with read-only RBAC. For
multi-pool IPAM, `spec.ipam.pools.allocated` supplies every allocated CIDR and
pool. An explicit empty list is an observed empty allocation. `requested` is
never treated as allocated. Legacy IPAM uses `spec.ipam.podCIDRs` only when the
multi-pool allocated field is absent.

AdvancedFabric status, NPA status, desired peer observations and host-agent peer
observations retain current `podCIDRs`, allocation pools, source object UID and
resourceVersion, collection timestamp and the declared legacy CIDR separately.
Reads that fail, missing/deleting objects and malformed allocations are Unknown;
they cannot reuse a previous successful read or promote the declaration to a
current observation. Adds, releases and object recreation converge on the next
successful reconciliation. This read-only provider adapter does not rewrite
Node/CiliumNode allocation, install routes or authorize a network transaction.

Validate a real allocation change in an isolated canary pool and node: record
the CiliumNode revision, then require the same revision and CIDR set in the
AdvancedFabric/NPA and peer observation. Release only an unused allocation,
require its removal on the next observation, and restore canary resources.
Never edit an in-use pool to simulate this test. Service endpoint and DNS
convergence require their own source-revision and application checks.

Provider contract: [Cilium multi-pool IPAM](https://docs.cilium.io/en/stable/network/concepts/ipam/multi-pool/).
