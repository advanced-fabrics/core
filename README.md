# Advanced Fabrics Core

[![Artifact Hub](https://img.shields.io/endpoint?url=https://artifacthub.io/badge/repository/advanced-fabric)](https://artifacthub.io/packages/search?repo=advanced-fabric)

AdvFab is an observe-first, provider-neutral network evidence controller for
Kubernetes. It turns Linux, Cilium, FRR, DNS, Gateway API, and declared topology
facts into versioned observation resources without making missing evidence look
healthy.

Use AdvFab when you need to answer:

- Which network paths are currently reachable and fresh?
- What evidence supports a routing or placement decision?
- Which dimensions are unknown, stale, partial, or contradictory?
- Did a separately authorized network change improve the same measured scope?

## Install

Public defaults are disabled and contain no private inventory or credentials.

```sh
helm upgrade --install advanced-fabric \
  oci://ghcr.io/advanced-fabrics/charts/advanced-fabric \
  --version 1.0.0-rc.14 \
  --namespace advanced-fabric --create-namespace
```

Enable observation with a reviewed values file:

```yaml
advancedFabric:
  enabled: true
  applyEnabled: false
  networkQuality:
    enabled: true
```

```sh
helm upgrade --install advanced-fabric \
  oci://ghcr.io/advanced-fabrics/charts/advanced-fabric \
  --version 1.0.0-rc.14 \
  --namespace advanced-fabric --create-namespace \
  --values my-values.yaml

kubectl get advancedfabrics.networking.advfab.org
kubectl get networkpathassessments.networking.advfab.org
```

Installation alone does not authorize network mutation. Guarded apply requires
an advertised provider capability, explicit policy, RBAC, and authenticated
identity.

## Stable boundaries

- The component owns measurement definitions, bounded collection, evidence,
  observation resources, and explicitly authorized guarded apply.
- Kubernetes, Cilium, FRR, routers, DNS providers, and telemetry storage retain
  their own lifecycle and authority.
- Consumers use CRDs and the advertised Observation API; they do not read
  internal ConfigMaps or depend on a release name, namespace, or UI.
- The Headlamp client is installed and released independently.

See the [component standard](docs/COMPONENT-STANDARD.md),
[dependency map](docs/DEPENDENCIES.md), and
[scenario matrix](docs/SCENARIO-MATRIX.md).

## Documentation

- [Core Wiki](https://github.com/advanced-fabrics/core/wiki) — concepts,
  operator navigation, and project layout
- [Component contract](docs/component-contract.md) — producer/consumer boundary
- [Measurement catalog](docs/osi-measurement-catalog.yaml) — symbols, units,
  scopes, windows, and uncertainty
- [Trade-off Observatory](docs/tradeoff-observatory.md) — O/S/I research model
- [Network quality standard](docs/network-quality-standard.md) — reachability
  and DNS evidence
- [DNS rollout](docs/dns-shadow-rollout.md) — staged activation and rollback
- [Security policy](SECURITY.md) and [contributing guide](CONTRIBUTING.md)

Normative cross-implementation decisions use AFEPs. The repository organization
is being simplified according to the
[consolidation plan](docs/REPOSITORY-CONSOLIDATION.md).

## Development

```sh
python -m unittest discover -s tests -v
python scripts/validate_component_standard.py
helm lint charts/re8ch-advanced-fabric
helm template test charts/re8ch-advanced-fabric >/dev/null
```

Behavioral changes require tests, DCO sign-off, signed commits, successful
checks, and review. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. Advanced Fabrics is not a CNCF project and does not claim CNCF
endorsement.
