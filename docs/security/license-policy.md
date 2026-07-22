# Dependency License Policy (SEC-SUP)

Spidey is Apache-2.0. To keep distribution unencumbered, dependency licenses are
gated in CI. The policy is enforced by [`scripts/check_licenses.py`](../../scripts/check_licenses.py)
(backend) and `license-checker` (frontend) in the
[security workflow](../../.github/workflows/security.yml).

## Policy

**Allowed — permissive:** MIT (and variants), BSD (0/2/3-clause), ISC, Apache-2.0,
Python Software Foundation, Unlicense, Zlib, CC0.

**Allowed — weak copyleft (acceptable under dynamic use):** LGPL-3.0, MPL-2.0.
These impose obligations only on modifications to the dependency itself, which we
do not make; we depend on published releases.

**Denied:** strong copyleft (GPL-2.0/3.0, AGPL) and SSPL, and any
proprietary/commercial license. A dependency under these must be replaced.

Compound strings (`"MPL-2.0 AND (Apache-2.0 OR MIT)"`) are accepted when a weak-
copyleft or permissive term applies; a denied term anywhere fails the check.

## Verified overrides

A few packages publish license metadata PyPI cannot classify (`UNKNOWN` or
`Other/Proprietary License`). Rather than blanket-ignore unknowns, their real,
verified license is pinned by name in the checker:

| Package | PyPI metadata | Verified license | Source |
| --- | --- | --- | --- |
| `fastembed` | Other/Proprietary | **Apache-2.0** | Qdrant `fastembed` repository |
| `py_rust_stemmers` | UNKNOWN | **MIT** | project repository |

An override is added only after confirming the upstream license text. Any *other*
unknown fails the gate until it is either verified-and-overridden or removed.

## Current status

As of v1.0 the gate passes over **186 backend dependencies**: predominantly
MIT/BSD/Apache, with LGPL-3.0 (`psycopg`) and MPL-2.0 (`certifi`, `pathspec`,
`tqdm`, `orjson`) accepted as weak copyleft. No GPL/AGPL/SSPL is present.

## Adding a dependency

1. Prefer permissive (MIT/BSD/Apache) where a choice exists.
2. If the license reports as unknown/proprietary, verify the real license from the
   source repository; add a documented override only if it is truly permissive or
   weak copyleft.
3. If it is strong copyleft or proprietary, choose a different dependency.
4. Run the gate locally:
   `uv run --with pip-licenses pip-licenses --format=json > licenses.json && python scripts/check_licenses.py licenses.json`.
