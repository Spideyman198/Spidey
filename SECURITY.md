# Security Policy

## Reporting a vulnerability

Please report vulnerabilities **privately** via GitHub Security Advisories (the repository's
**Security → Report a vulnerability** page) — do not open a public issue.

You can expect an acknowledgement within 72 hours and a status update within 14 days. Please allow
up to 90 days for a fix before public disclosure; we will credit reporters in the advisory unless
you prefer otherwise.

## Scope

Especially welcome:

- **Sandbox escapes** — any way agent-executed code reaches the host, the network (when disabled),
  or Spidey's own services/secrets.
- **Approval-gate bypasses** — any path to a destructive action (file deletion outside plan,
  off-allow-list commands, PR creation) without a recorded human approval.
- **Prompt/retrieval/memory injection** — repository or tool content that steers agents into
  unauthorized actions.
- Authentication/authorization flaws, path traversal, SSRF, injection of any kind.

Out of scope: vulnerabilities requiring a malicious *operator* (the deployment model trusts the
person running the stack), and denial of service against your own self-hosted instance.

## Supported versions

| Version | Supported |
|---|---|
| `main` (pre-1.0 milestones) | ✅ latest milestone only |
| < latest milestone tag | ❌ |

## Hardening guidance

Deployment hardening, the threat model, and the security architecture are documented in
[docs/11-security.md](docs/11-security.md) and [docs/01-requirements.md §5](docs/01-requirements.md).
