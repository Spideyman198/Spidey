# SEC-* Verification Matrix (v1.0)

Every security requirement from [docs/01 §7](../01-requirements.md) mapped to its
implemented control and the automated test(s) that verify it. This is the M15
"full re-verification of every SEC-* with tests" deliverable — the table is the
sign-off. All referenced suites run in CI (unit + integration + attack-shaped +
SAST); paths are under `backend/` unless noted.

| ID | Threat | Primary control | Verifying tests / gates | Status |
| --- | --- | --- | --- | --- |
| **SEC-PI** | Prompt injection via repo/issue/search content | Retrieved text wrapped in an inert, attributed **data frame**; role tool allow-lists; approval gates; the fence marker is escaped | `tests/unit/codeintel/…` framing · `tests/unit/platform/test_injection.py` · `tests/security/test_memory_poisoning.py` | ✅ |
| **SEC-SBX** | Untrusted code → host compromise | Ephemeral sandbox: no network, non-root, read-only rootfs, CPU/mem/PID caps, wall-clock kill, workspace-only mount — Docker **and** K8s Jobs adapters | `tests/security/test_sandbox_containment.py` · `tests/unit/execution/test_k8s_sandbox.py` · `tests/unit/agents/test_sandbox_tools.py` · conftest `docker.rego`/`kubernetes.rego` | ✅ |
| **SEC-SEC** | Secret exfiltration | Secrets never enter agent context; sandbox env scrubbed; **secret-scanning** on agent output + diffs; egress blocked by default | `tests/unit/execution/test_scrub.py` · `tests/unit/platform/test_secrets.py` | ✅ |
| **SEC-FS** | Path traversal / file escape | `SafeFileSystem`: canonicalization + workspace-root allow-list + symlink/NTFS-junction resolution on every FS op | `tests/security/test_safe_filesystem.py` | ✅ |
| **SEC-CMD** | Command injection | **argv-array only** (no shell); `CommandPolicy` allow-list with typed arg schemas | `tests/unit/execution/test_policy.py` | ✅ |
| **SEC-SSRF** | Agent-triggered internal fetches | URL scheme/host validation, private-range denial, host allow-list on clone | `tests/security/test_url_guard.py` | ✅ |
| **SEC-WEB** | SQLi / XSS / CSRF | Parameterized SQLAlchemy; strict Pydantic; **CSP** (no `unsafe-inline`); agent output rendered as text-only | `tests/security/test_api_hardening.py` · `frontend/index.html` CSP · [M12 review](m12-security-review.md) | ✅ |
| **SEC-QOS** | Resource exhaustion / DoS-by-agent | Per-run step/token/cost **budgets**; Redis rate limiting + lockout; sandbox quotas; Celery time limits | `tests/unit/llm/test_gateway.py` (budgets) · `tests/unit/identity/test_redis_guard.py` (rate) · `tests/security/test_audit_and_lockout.py` · `tests/security/test_sandbox_containment.py` | ✅ |
| **SEC-SUP** | Malicious transitive dependency | Hash-pinned lockfile; `pip-audit`; **license gate**; SBOM (CycloneDX); Cosign signing; gitleaks; Trivy; Dependabot; reranker model hash-pin | `.github/workflows/security.yml` (pip-audit, licenses, SBOM, Trivy, gitleaks) · `release.yml` (Cosign) · `tests/unit/llm/test_reranker.py` (model pin) | ✅ |
| **SEC-IAM** | AuthN/AuthZ failure | Argon2id; short JWT + rotating refresh with reuse detection; RBAC per route + tool; append-only audit log | `tests/integration/test_authz_matrix.py` · `tests/unit/identity/test_auth_service.py` · `tests/security/test_audit_and_lockout.py` | ✅ |
| **SEC-MCP** | Tool poisoning / rug-pull | Tool-definition **pinning + drift alarms**; description sanitization; trust tiers; RBAC choke point | `tests/unit/agents/test_mcp_provider.py` · `tests/unit/agents/test_mcp_server.py` · `tests/unit/agents/test_tool_registry.py` | ✅ |
| **SEC-MEM** | Memory poisoning across sessions | Distillation-only writes through a **fact-only gate**; inert framing at recall; confidence decay | `tests/security/test_memory_poisoning.py` · `evaluation` memory-safety suite | ✅ |
| **SEC-PII** | PII leakage into logs/memory/replay | PII **scrubbing** at the log pipeline, memory write gate, and replay capture | `tests/unit/platform/test_scrubbing.py` | ✅ |

## Enforcement as gates

Beyond the tests above, these run as **blocking CI gates** on every push/PR:

- **SAST**: Bandit (`-ll`) + Semgrep (project invariant rules + `p/python`, `--error`).
- **CodeQL**: `security-extended` on **python and javascript-typescript**.
- **Invariants** (Semgrep): the no-direct-file-IO rule for `agents`/`codeintel`, enforced syntactically.
- **Policy** (Conftest): Dockerfile/compose (`docker.rego`) and Helm manifests (`kubernetes.rego`).
- **Secrets**: full-history gitleaks scan.
- **Supply chain**: `pip-audit --strict`, the license gate, Trivy (CRITICAL/HIGH), and CycloneDX SBOM.

A regression in any control fails the build, so the matrix stays green by
construction rather than by periodic manual review.
