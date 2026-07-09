# spidey (backend)

The Spidey backend package: bounded contexts under `src/spidey/`, tests under `tests/`,
migrations under `alembic/`. See the [repository README](../README.md) and
[docs/03-repository-structure.md](../docs/03-repository-structure.md) for the full map.

```bash
uv sync --group dev   # environment
uv run pytest         # tests
uv run ruff check .   # lint
uv run pyright        # types
```
