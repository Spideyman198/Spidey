"""Dependency license gate (M15, SEC-SUP).

Reads `pip-licenses --format=json` and fails the build if any dependency's
license is not on the allow-list. The policy (docs/security/license-policy.md):

- **Allowed**: permissive (MIT/BSD/ISC/Apache-2.0/PSF/Unlicense/Zlib/CC0) and
  weak copyleft acceptable under dynamic use (LGPL-3.0, MPL-2.0).
- **Denied**: strong copyleft (GPL, AGPL, SSPL) and proprietary/commercial.
- **Overrides**: a few packages report license metadata PyPI cannot classify
  (`UNKNOWN` / `Other/Proprietary`); their real, verified license is pinned here
  by name so the gate is honest rather than either falsely failing or blanket-
  ignoring unknowns.

Usage:
    uv run --with pip-licenses pip-licenses --format=json > licenses.json
    python scripts/check_licenses.py licenses.json
"""

from __future__ import annotations

import json
import sys

# Weak copyleft we accept (dynamic linking / file-level). Checked FIRST, because
# "lgpl-3.0" and "mpl-2.0" contain the substrings the GPL denial matches on.
_WEAK_COPYLEFT_TOKENS = ("lgpl", "mpl", "mozilla public license")

# Permissive license tokens we accept. Matching is substring and case-insensitive,
# so "BSD License", "BSD-3-Clause", etc. all match "bsd".
_ALLOWED_TOKENS = (
    "mit",
    "bsd",
    "apache",
    "isc",
    "python software foundation",
    "psf",
    "unlicense",
    "zlib",
    "cc0",
)

# Strong copyleft / proprietary tokens that always fail, even if a permissive
# token also appears (a conservative reading of dual/compound license strings).
_DENIED_TOKENS = (
    "gpl-2",
    "gpl-3",
    "gplv2",
    "gplv3",
    "gnu general public",
    "agpl",
    "affero",
    "sspl",
    "server side public",
    "commercial",
)

# Verified real licenses for packages whose PyPI metadata is UNKNOWN/Other.
_OVERRIDES = {
    "fastembed": "Apache-2.0",  # Qdrant fastembed — Apache-2.0 (PyPI classifier gap)
    "py_rust_stemmers": "MIT",  # rust-stemmers binding — MIT
    "py-rust-stemmers": "MIT",
}


def is_within_policy(license_text: str) -> bool:
    """True if a license string is acceptable under the policy.

    Weak copyleft (LGPL/MPL) is checked before the GPL denial precisely because
    "lgpl"/"mpl" strings contain the substrings the denial matches on.
    """
    low = license_text.lower()
    if any(token in low for token in _WEAK_COPYLEFT_TOKENS):
        return True
    if any(token in low for token in _DENIED_TOKENS):
        return False
    return any(token in low for token in _ALLOWED_TOKENS)


def check(entries: list[dict[str, str]]) -> list[str]:
    violations: list[str] = []
    for entry in entries:
        name = entry.get("Name", "?")
        license_text = _OVERRIDES.get(name, entry.get("License", ""))
        if not is_within_policy(license_text):
            violations.append(f"{name} {entry.get('Version', '?')}: {license_text!r}")
    return violations


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: check_licenses.py <pip-licenses.json>", file=sys.stderr)
        return 2
    entries = json.loads(open(args[0], encoding="utf-8").read())
    violations = check(entries)
    if violations:
        print("Disallowed or unrecognized dependency licenses:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  - {v}", file=sys.stderr)
        print(
            "\nAdd a verified override in scripts/check_licenses.py or replace the dependency.",
            file=sys.stderr,
        )
        return 1
    print(f"license gate: {len(entries)} dependencies, all within policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
