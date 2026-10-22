# Advanced Fabrics repository consolidation plan

**Status:** phase 1 complete; content-bearing migrations remain planned
**Inventory date:** 2026-10-22

## Progress

Phase 1 reduced the active organization surface from 22 repositories to 12.
The following repositories contained only `README.md` and `LICENSE`, and had no
releases, tags, workflows, Pages site, open issues, forks, or associated GitHub
Package. They were marked with `core` as their maintained destination and
archived on 2026-10-22:

- `charts`, `cli`, and `reference-runtime`;
- `providers`, `provider-cilium`, `provider-frr`, and `provider-linux`; and
- `sdk-go`, `sdk-python`, and `sdk-typescript`.

Archiving is reversible and preserves Git history and existing URLs. No
repository was deleted. Content-bearing repositories remain active until their
source, issues, published pages, and inbound references satisfy the exit
criteria below.

## Decision

Reduce the remaining organization surface to five public collaboration
surfaces plus two private product repositories. Consolidate source before
archiving a repository. Preserve history where it contains meaningful work,
and leave an archive notice pointing to the new path.

The current split was designed for a future multi-implementation ecosystem.
Most of those boundaries do not yet contain an independently released
component: ten public repositories are only 5–11 KB, and nine of them contain
only a README and LICENSE. Maintaining separate issues, policies, releases,
security settings, and navigation for those placeholders costs more than the
isolation currently provides.

## Target repositories

| Repository | Purpose | Receives |
| --- | --- | --- |
| `core` | Runtime monorepo and release authority | API schemas/protocols, chart source, CLI, providers, SDKs, examples, reference runtime, and conformance tests |
| `headlamp-advanced-fabric` | Independently built read-only UI client | Existing Headlamp plugin only |
| `docs` | Published documentation and normative specifications | Current docs, AFEPs/specification pages, and the small project website |
| `community` | Roadmap, governance, maintainers, and project-level issues | Existing community process and public planning |
| `.github` | Organization-wide health files and reusable workflows | Existing templates and policies only |
| `product-prd` (private) | Reviewed product requirements and decisions | Remains private and separate |
| `product-assets` (private) | Licensed source artwork and immutable asset references | Remains private and separate |

`headlamp-advanced-fabric` remains separate because it has a distinct
TypeScript toolchain, browser/UI security surface, release cadence, and install
lifecycle. The two private repositories remain separate because their access
and licensing boundaries differ from public implementation source.

## Migration map

| Current repository | Destination | Proposed path | Disposition after migration |
| --- | --- | --- | --- |
| `api` | `core` | `api/` | archive |
| `charts` | `core` | existing `charts/` | archive; it is already superseded by the core release workflow |
| `cli` | `core` | `cmd/afctl/` | archive until substantive CLI code is added in core |
| `conformance` | `core` | `conformance/` | migrate code and result schema, then archive |
| `examples` | `core` | existing `examples/` | migrate useful examples, then archive |
| `reference-runtime` | `core` | `deploy/reference/` | archive placeholder; add runtime manifests in core when maintained |
| `providers` | `core` | `providers/` | archive placeholder; use this directory for shared provider contracts and test doubles |
| `provider-cilium` | `core` | `providers/cilium/` | archive placeholder |
| `provider-frr` | `core` | `providers/frr/` | archive placeholder |
| `provider-linux` | `core` | `providers/linux/` | archive placeholder |
| `sdk-go` | `core` | `sdk/go/` | archive placeholder; split again only after an independent release is justified |
| `sdk-python` | `core` | `sdk/python/` | archive placeholder |
| `sdk-typescript` | `core` | `sdk/typescript/` | archive placeholder |
| `spec` | `docs` | `docs/spec/` and `docs/afeps/` | migrate normative pages, preserve redirects, then archive |
| `website` | `docs` | documentation landing/theme | migrate public landing content, then archive |

## What not to combine

- Do not put the Headlamp build into the controller chart or core release.
- Do not move private PRDs or licensed source assets into public Git history.
- Do not copy generated packages or OCI artifacts into Git; releases remain in
  GHCR and GitHub Releases.
- Do not collapse API compatibility into implementation internals. In a
  monorepo, `api/` remains a separately owned and versioned contract directory.
- Do not archive a repository while an active consumer still fetches source,
  actions, packages, Pages, release assets, or documentation from it.

## Migration sequence

1. Record every repository default branch, release, package, Pages site,
   workflow reference, open issue, and inbound GitHub dependency.
2. Add destination directories, CODEOWNERS boundaries, and path-scoped CI.
3. Import meaningful source with history (`git subtree` or a reviewed history
   import); copy placeholders only when their content remains useful.
4. Move issues and update package, documentation, badge, workflow, and catalog
   links. Keep compatibility redirects for published web paths.
5. Release from the destination and verify consumers against immutable
   artifacts.
6. Replace the source README with an archive notice naming the new path and
   final supported release.
7. Archive the source repository. Do not delete it.
8. After each migration, update the service-backend catalog and locked revision
   through its own signed GitOps pull request.

## Exit criteria

A source repository may be archived only when:

- all retained source and license history is available at the destination;
- open issues and security advisories have an owner;
- releases and package references have an explicit compatibility decision;
- Pages, Actions, Dependabot, branch rules, secrets, and deploy keys have been
  inventoried and either migrated or retired;
- repository search and organization profile point users to the destination;
- no service-backend module or production workflow depends on the old mutable
  branch; and
- rollback is possible by unarchiving the original repository.

## When to split again

A directory should become a repository only after it has at least two of these:

- an independent release and compatibility lifecycle;
- a different maintainer or access-control boundary;
- consumers that do not otherwise depend on `core`;
- a distinct security or licensing boundary;
- a build graph whose isolation materially improves delivery.

This rule keeps current collaboration simple without preventing SDKs or
providers from becoming independent projects when they actually mature.
