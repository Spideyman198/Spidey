"""CLI exit-code contract: 0 green, 1 failed suite or baseline violation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from spidey.evaluation.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path


class TestEvalCli:
    def test_empty_registry_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(
            [
                "run",
                "--tier",
                "t1",
                "--check-baselines",
                "--baselines-dir",
                str(tmp_path / "baselines"),
                "--reports-dir",
                str(tmp_path / "reports"),
            ]
        )
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "no suites registered" in out
        assert list((tmp_path / "reports").glob("eval-t1-*.json"))

    def test_report_is_always_written(self, tmp_path: Path) -> None:
        main(["run", "--reports-dir", str(tmp_path / "r"), "--baselines-dir", str(tmp_path / "b")])
        assert len(list((tmp_path / "r").glob("*.json"))) == 1

    def test_usage_error_exits_2(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["run", "--tier", "t9"])
        assert excinfo.value.code == 2
