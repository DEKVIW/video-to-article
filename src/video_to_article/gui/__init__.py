"""Desktop GUI for video-to-article (Phase A workbench)."""

__all__ = ["main"]


def main() -> None:
    from .app import main as app_main

    app_main()
