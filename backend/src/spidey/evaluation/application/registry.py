"""Suite registry: the composition point where benchmark suites plug in."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.platform.errors import ConflictError

if TYPE_CHECKING:
    from spidey.evaluation.domain import EvalSuite, Tier


class SuiteRegistry:
    """Named, tier-tagged suite collection. Names are unique by contract."""

    def __init__(self) -> None:
        self._suites: dict[str, EvalSuite] = {}

    def register(self, suite: EvalSuite) -> None:
        if suite.name in self._suites:
            msg = f"evaluation suite {suite.name!r} is already registered"
            raise ConflictError(msg, suite=suite.name)
        self._suites[suite.name] = suite

    def suites_for(self, tier: Tier) -> list[EvalSuite]:
        """Suites executed at ``tier`` — cumulative over lower tiers, name-ordered."""
        selected = [suite for suite in self._suites.values() if tier.includes(suite.tier)]
        return sorted(selected, key=lambda suite: suite.name)

    def __len__(self) -> int:
        return len(self._suites)


def build_default_registry() -> SuiteRegistry:
    """Assemble the platform's suite set.

    Suites register here as their milestones land: retrieval (M4), codegen and
    regression-replay (M7), agent-tasks and groundedness (M10), safety (M11).
    An empty registry is a valid, passing state — CI wiring is proven before
    the first real suite exists.
    """
    return SuiteRegistry()
