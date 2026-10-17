"""Backward-compatible CLI entry point. All original commands remain available."""

from __future__ import annotations

from arcanacart.cli import legacy_main


def main(argv: list[str] | None = None) -> int:
    return legacy_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
