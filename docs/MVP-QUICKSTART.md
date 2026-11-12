# External MVP quickstart

This path installs AdvFab as a read-only Kubernetes network evidence producer.
It is the smallest supported external evaluation: real observations are
published through CRDs and the Observation API, while every mutation surface
remains disabled.

## Prerequisites

- Kubernetes 1.30 or newer;
- cluster-admin access for CRDs, node observers, and their RBAC;
- Linux worker nodes that permit privileged DaemonSets and host networking;
- outbound access to the immutable images declared by the chart; and
- `helm`, `kubectl`, and `python3` on the operator workstation.

Cilium/Hubble and FRR are optional evidence providers. Without them, Linux and
Kubernetes observations remain available, while unsupported measurements stay
`Partial` or `Unknown`. The MVP never substitutes demo values for missing data.

Do not use this profile when privileged node observers are prohibited. AdvFab
cannot truthfully inspect host routes, interfaces, or datapath state from an
unprivileged Pod.

## Install

```sh
helm upgrade --install advanced-fabric \
  oci://ghcr.io/advanced-fabrics/charts/advanced-fabric \
  --version 1.0.0-rc.14 \
  --namespace advanced-fabric \
  --create-namespace \
  --values examples/mvp-values.yaml \
  --wait \
  --timeout 5m
```

The profile enables node and pod-plane observation, but keeps
`mode=observe-only`, `applyEnabled=false`, DNS replacement, RouterOS, Mihomo,
virtual Ingress, and policy enforcement disabled.

## Verify

Run the repository verifier against the installed namespace:

```sh
./scripts/verify_mvp.sh advanced-fabric
```

The verifier fails unless:

1. the public CRDs exist;
2. the controller and both observation DaemonSets complete rollout;
3. the live custom resource is still observe-only;
4. the advertised Observation API passes its `v1` health contract; and
5. at least one real node subject has been published.

Inspect the evidence without depending on implementation ConfigMaps:

```sh
kubectl get advancedfabrics.networking.advfab.org advanced-fabric -o yaml
kubectl get networkpathassessments.networking.advfab.org -A
kubectl get --raw \
  '/api/v1/namespaces/advanced-fabric/services/http:advanced-fabric-observation-api:8080/proxy/api/v1/subjects'
```

An observation in `Partial` state is valid and means required evidence is
missing. It is not an installation failure and must not be presented as a
healthy or complete O/S/I result.

## MVP boundary

This MVP supports external installation, real node discovery, bounded network
measurements, public observation resources, and read-only API consumption. It
does not promise provider mutations, DNS takeover, automatic routing changes,
causal trade-off identification, or a bundled UI. The Headlamp client is a
separate consumer of the advertised API.

Uninstall with:

```sh
helm uninstall advanced-fabric --namespace advanced-fabric
```

Helm intentionally retains CRDs. Remove them only after exporting any evidence
resources and confirming that no other AdvFab release uses them.
