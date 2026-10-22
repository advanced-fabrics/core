# Security Policy

## Report a vulnerability privately

Do not open a public issue for a suspected vulnerability. Use
[GitHub private vulnerability reporting](https://github.com/advanced-fabrics/core/security/advisories/new)
so maintainers can investigate and coordinate a fix without exposing users.

Include, when available:

- the affected release, chart values, and Kubernetes version;
- the security boundary crossed and expected behavior;
- a minimal reproduction without production credentials or private topology;
- impact, prerequisites, and whether exploitation changes network state; and
- any suggested mitigation or evidence that the issue is already exploited.

Do not include credentials, private keys, tokens, packet contents, private
topology, or raw production telemetry. If sensitive evidence is essential,
describe it first in the private advisory and wait for handling instructions.

## Supported versions

Security fixes target the current release candidate or stable release and the
default branch. Older releases may receive a backport when the issue is severe
and the fix can be applied without changing the public contract. Users should
otherwise upgrade to the newest signed release.

| Version | Security support |
| --- | --- |
| Current tagged release | Supported |
| `main` | Supported for the next release |
| Older tags | Best effort; upgrade normally required |

## Response process

Maintainers will acknowledge a complete private report, assess affected
versions and boundaries, and coordinate remediation and disclosure in the
private advisory. Reports that require more evidence remain private while the
reporter and maintainers establish reproducibility and impact.

After a fix is available, maintainers will publish a signed release and, when
appropriate, a GitHub security advisory with affected versions, severity,
credits, mitigation, and upgrade instructions.

## Repository security controls

The repository uses:

- GitHub dependency graph and Dependabot vulnerability alerts;
- Dependabot security updates and grouped weekly GitHub Actions updates;
- automatic dependency security fixes where GitHub can produce them;
- secret scanning, validity checks, non-provider-pattern detection, and push
  protection;
- CodeQL default setup for Python and GitHub Actions using the extended query
  suite;
- dependency-integrity CI that requires immutable action and runtime-image
  references; and
- OpenSSF Scorecard reporting.

Dependabot pull requests are not auto-merged. They must pass the same exact-SHA
tests, public-boundary checks, and review policy as other changes.

## Product security boundary

AdvFab defaults to observation. Installation or evidence readiness never
authorizes network mutation. Apply requires an advertised provider capability,
explicit policy, least-privilege RBAC, and authenticated identity.

Credentials and private topology must never be written to CRD status,
observation responses, logs, examples, support bundles, or release assets.
Missing, stale, partial, and contradictory evidence must remain distinguishable
and must not be converted into a healthy value.

The organization-wide policy and disclosure expectations are maintained in
[`advanced-fabrics/.github`](https://github.com/advanced-fabrics/.github/blob/main/SECURITY.md).
