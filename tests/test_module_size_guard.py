from __future__ import annotations

from pathlib import Path

from telegram_pair.module_size_guard import evaluate_module_sizes, format_summary, main


def write_lines(path: Path, count: int) -> None:
    path.write_text("\n".join(f"line {index}" for index in range(count)) + "\n", encoding="utf-8")


def test_evaluate_module_sizes_flags_warning_and_error(tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    write_lines(package_dir / "small.py", 10)
    write_lines(package_dir / "warn.py", 400)
    write_lines(package_dir / "too_big.py", 501)

    summary = evaluate_module_sizes(tmp_path, include_dirs=("pkg",), warning_lines=400, limit_lines=500)

    statuses = {report.path.name: report.status for report in summary.reports}
    assert statuses == {
        "small.py": "ok",
        "warn.py": "warning",
        "too_big.py": "error",
    }
    assert summary.has_violations is True


def test_format_summary_includes_status_labels(tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    write_lines(package_dir / "warn.py", 400)

    summary = evaluate_module_sizes(tmp_path, include_dirs=("pkg",), warning_lines=400, limit_lines=500)
    rendered = format_summary(summary)

    assert "Python module size report" in rendered
    assert "[WARNING]" in rendered
    assert "warn.py" in rendered


def test_main_returns_zero_when_no_violations(tmp_path: Path, capsys) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    write_lines(package_dir / "ok.py", 20)

    exit_code = main(["--root", str(tmp_path), "--include", "pkg"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "[OK]" in captured.out


def test_main_returns_one_when_limit_exceeded(tmp_path: Path, capsys) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    write_lines(package_dir / "too_big.py", 501)

    exit_code = main(["--root", str(tmp_path), "--include", "pkg"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "[ERROR]" in captured.out
