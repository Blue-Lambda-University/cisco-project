#!/usr/bin/env python3
"""
Generate a PDF from docs/SESSION_CONNECTION_WORKFLOW.html.

Automated (requires Playwright + Chromium):
  uv sync --extra dev
  uv run playwright install chromium
  uv run python scripts/generate_session_workflow_pdf.py

Manual alternative (no install):
  Open docs/SESSION_CONNECTION_WORKFLOW.html in Chrome or Edge, wait for
  diagrams to load, then File → Print → Save as PDF.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "docs" / "SESSION_CONNECTION_WORKFLOW.html"
OUTPUT_PDF = REPO_ROOT / "docs" / "SESSION_CONNECTION_WORKFLOW.pdf"


def main() -> int:
    if not HTML_PATH.exists():
        print(f"Error: {HTML_PATH} not found.", file=sys.stderr)
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright not installed. Run:\n"
            "  uv sync --extra dev\n"
            "  uv run playwright install chromium\n\n"
            "Or generate PDF manually: open the HTML file in Chrome, then Print → Save as PDF.",
            file=sys.stderr,
        )
        return 1

    file_url = HTML_PATH.as_uri()
    print(f"Loading {HTML_PATH} ...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(file_url, wait_until="networkidle")
            page.wait_for_timeout(2500)
            print(f"Writing PDF to {OUTPUT_PDF} ...")
            page.pdf(
                path=str(OUTPUT_PDF),
                format="A4",
                margin={"top": "20mm", "right": "20mm", "bottom": "20mm", "left": "20mm"},
                print_background=True,
            )
            browser.close()
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "browser" in str(e).lower():
            print(
                "Chromium not installed or wrong architecture. Run:\n"
                "  uv run playwright install chromium\n\n"
                "Or generate PDF manually: open docs/SESSION_CONNECTION_WORKFLOW.html "
                "in Chrome, wait for diagrams to load, then File → Print → Save as PDF.",
                file=sys.stderr,
            )
        else:
            raise
        return 1

    print(f"Done: {OUTPUT_PDF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
