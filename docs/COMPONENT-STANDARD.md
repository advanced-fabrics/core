# Advanced Fabric component standard

**Status:** repository-enforced v1  
**Audience:** implementers, reviewers, platform operators, and consumers

This document defines what this repository means by an independently usable
Advanced Fabric component. The machine-readable declaration is
[`component-standard.json`](../component-standard.json); CI validates it on
every change. Normative cross-implementation API and compatibility decisions
remain in [`advanced-fabrics/spec`](https://github.com/advanced-fabrics/spec)
and [`advanced-fabrics/api`](https://github.com/advanced-fabrics/api).

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are to be
interpreted as requirements for this implementation and its release process.

## 1. Independent component boundary

The component MUST be installable without a Re8ch repository, private registry,
private topology, Headlamp plugin, Public Edge Manager, or provider credential.
It owns measurement registration, bounded evidence collection, observation
resources, and explicitly authorized guarded apply. It MUST NOT own Kubernetes
node lifecycle, consumer publication policy, credential lifecycle, or a
long-term telemetry database.

Consumers integrate through the advertised Kubernetes APIs and
`AdvancedFabric.status.observationAPI`. They MUST NOT depend on internal
ConfigMaps, release names, namespaces, controller implementation details, or
the presence of an unrelated UI. The detailed data-plane contract is in
[`component-contract.md`](component-contract.md).

## 2. Contract sources

Every public contract MUST have one declared source and an explicit stability
class in `component-standard.json`.

| Contract | Authority | Compatibility rule |
| --- | --- | --- |
| CRDs and OpenAPI | `advanced-fabrics/api` and the chart CRDs | Schema-breaking changes require a new served version and an AFEP |
| Measurement semantics | `osi-measurement-catalog.yaml` | Units, scope, windows, missingness, and uncertainty are part of the contract |
| Consumer evidence | `NetworkPathAssessment/v1alpha2` and the Observation API | Freshness, scope, and nullable values MUST be preserved |
| Guarded apply | provider capability, policy, RBAC, and authenticated identity | Observation never implies authorization to mutate |
| Research claims | `tradeoff-observatory.md` | Descriptive association MUST NOT be presented as an identified causal trade-off |

Unknown, stale, partial, and contradictory evidence MUST remain distinguishable.
A component MUST NOT manufacture a healthy value to complete a dashboard or
release gate.

## 3. Safe defaults and configuration

The public chart MUST render with runtime and mutation disabled. Enabling the
controller MUST still default to observe-only. Public defaults MUST NOT contain
organization inventory, credentials, private endpoints, or mutable image tags.

Configuration MUST be declarative and reviewable. Provider-specific behavior
MUST be behind a capability boundary and MUST fail closed when its authorization
or preconditions are absent. A chart upgrade MUST NOT silently broaden write
authority.

## 4. Dependency discipline

Dependencies are classified as required, optional, or consumer-owned in
[`DEPENDENCIES.md`](DEPENDENCIES.md). Optional integrations MUST be detectable
and independently disabled. Their absence MUST NOT be misreported as general
fabric failure. Credentials belong to the narrow adapter that uses them and
MUST NOT pass through observation resources, logs, release assets, or support
bundles.

## 5. Verification matrix

Every behavioral change MUST include a deterministic unit or render test.
Repository CI MUST run, at minimum:

1. Python unit tests for controller and schema behavior;
2. Helm lint and default rendering;
3. enabled observation and representative optional-feature renders;
4. public-boundary checks for credentials, bundled UI, and safe defaults; and
5. `scripts/validate_component_standard.py`.

The network/resource scenarios in [`SCENARIO-MATRIX.md`](SCENARIO-MATRIX.md)
are the minimum reasoning matrix. Production fault injection is not required
and MUST NOT be performed merely to satisfy repository conformance.

## 6. Release and supply-chain evidence

One tag MUST identify one chart version and app version. The release workflow
MUST publish the declared artifacts from the tagged source, address them by
immutable digest, sign them with short-lived identity, attach build provenance,
and publish an SBOM plus checksum. Release automation and externally sourced
runtime images SHOULD be pinned by immutable digest.

The artifact inventory in `component-standard.json` is authoritative for what
the project publishes. Adding an image, chart, installer, or platform-specific
bundle requires updating the inventory, its evidence, documentation, and
verification in the same pull request.

## 7. Security and governance

The repository MUST use private vulnerability reporting, dependency review,
automated dependency updates, and a scheduled security scorecard. Pull requests
MUST pass tests and security checks for the exact reviewed commit. Compatibility,
protocol, trust-boundary, and new mutation-capability changes require an AFEP.

Generated output, vendored code, binary assets, and credentials MUST NOT be
committed unless they are explicitly declared release inputs with provenance
and license review.

## 8. Definition of done

A change is component-standard complete only when:

- its owner and non-owner boundaries remain explicit;
- public contracts and compatibility consequences are documented;
- safe defaults and least-privilege RBAC are preserved;
- required and optional dependency behavior is tested;
- the relevant scenario cells have deterministic evidence;
- release inventory and evidence remain valid; and
- documentation describes rollback or the absence of mutation.

Passing the validator proves repository conformance to declared checks. It does
not prove a live network healthy, a provider available, or a causal trade-off
identified.
