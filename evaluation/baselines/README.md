# Blessed baselines

One `<suite>.json` per suite: `{"<metric>": {"min": <float>}}`. The eval CLI
(`python -m spidey.evaluation run --check-baselines`) fails when a metric drops below its minimum.

Baselines change **only** via reviewed re-bless commits with justification in the PR description
(docs/10 §4). CI never updates this directory automatically.
