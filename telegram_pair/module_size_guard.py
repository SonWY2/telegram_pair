from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_WARNING_LINES = 400
DEFAULT_LIMIT_LINES = 500
DEFAULT_INCLUDE = ("telegram_pair", "tests")
DEFAULT_EXCLUDE_PARTS = ("__pycache__", ".git", ".pytest_cache", ".venv", "venv")


@dataclass(frozen=True)
class ModuleSizeReport:
    path: Path
    line_count: int
    status: str


@dataclass(frozen=True)
class ModuleSizeSummary:
    reports: tuple[ModuleSizeReport, ...]
    warning_lines: int
    limit_lines: int

    @property
    def has_violations(self) -> bool:
        return any(report.status == "error" for report in self.reports)


def _iter_python_files(root: Path, include_dirs: Sequence[str]) -> Iterable[Path]:
    for include_dir in include_dirs:
        base = root / include_dir
        if not base.exists():
            continue
        yield from sorted(path for path in base.rglob("*.py") if _is_included_file(path))


def _is_included_file(path: Path) -> bool:
    return not any(part in DEFAULT_EXCLUDE_PARTS for part in path.parts)


def count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def evaluate_module_sizes(
    root: Path,
    *,
    include_dirs: Sequence[str] = DEFAULT_INCLUDE,
    warning_lines: int = DEFAULT_WARNING_LINES,
    limit_lines: int = DEFAULT_LIMIT_LINES,
) -> ModuleSizeSummary:
    reports = []
    for path in _iter_python_files(root, include_dirs):
        line_count = count_lines(path)
        if line_count > limit_lines:
            status = "error"
        elif line_count >= warning_lines:
            status = "warning"
        else:
            status = "ok"
        reports.append(
            ModuleSizeReport(
                path=path.relative_to(root),
                line_count=line_count,
                status=status,
            )
        )
    return ModuleSizeSummary(tuple(reports), warning_lines, limit_lines)


def format_summary(summary: ModuleSizeSummary) -> str:
    header = [
        f"Python module size report (warn: {summary.warning_lines}, limit: {summary.limit_lines})",
    ]
    body = [
        f"[{report.status.upper()}] {report.line_count:>4} {report.path}"
        for report in summary.reports
    ]
    if not body:
        body = ["No Python files found in configured include directories."]
    return "\n".join(header + body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check Python module sizes and flag files that need modularization.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root to scan (default: current working directory).",
    )
    parser.add_argument(
        "--include",
        nargs="+",
        default=list(DEFAULT_INCLUDE),
        help="Directories to scan for Python modules.",
    )
    parser.add_argument(
        "--warning-lines",
        type=int,
        default=DEFAULT_WARNING_LINES,
        help="Warn when a file reaches or exceeds this many lines.",
    )
    parser.add_argument(
        "--limit-lines",
        type=int,
        default=DEFAULT_LIMIT_LINES,
        help="Fail when a file exceeds this many lines.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.warning_lines > args.limit_lines:
        parser.error("--warning-lines must be less than or equal to --limit-lines")

    summary = evaluate_module_sizes(
        args.root.resolve(),
        include_dirs=tuple(args.include),
        warning_lines=args.warning_lines,
        limit_lines=args.limit_lines,
    )
    print(format_summary(summary))
    return 1 if summary.has_violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
