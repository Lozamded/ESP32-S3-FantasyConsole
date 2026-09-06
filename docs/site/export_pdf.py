#!/usr/bin/env python3
"""Builds the Docusaurus docs site and exports every page as one PDF.

Renders the production build through headless Chromium (Playwright) so the
output matches what visitors see, generates a table-of-contents page from
sidebars.js (the sidebar's single source of truth), and stitches everything
together with pypdf — including a PDF outline (bookmarks) that mirrors the
sidebar's groups.

Setup (once):
    pip install -r requirements-pdf.txt
    playwright install chromium

Usage:
    python export_pdf.py [-o OUTPUT] [--no-build]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, sync_playwright
from pypdf import PdfReader, PdfWriter

DOCS_SITE = Path(__file__).resolve().parent
DOCS_DIR = DOCS_SITE / "docs"
PORT = 4173
BASE_URL = f"http://localhost:{PORT}"
PDF_MARGIN = {"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"}


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=DOCS_SITE, check=True)


def doc_title(doc_id: str) -> str:
    """Read the frontmatter title from a doc markdown file."""
    for ext in (".md", ".mdx"):
        path = DOCS_DIR / (doc_id + ext)
        if path.exists():
            text = path.read_text(encoding="utf-8")
            m = re.search(r"^title:\s*(.+)$", text, re.MULTILINE)
            if m:
                return m.group(1).strip()
            m = re.search(r"^# (.+)$", text, re.MULTILINE)
            if m:
                return m.group(1).strip()
    return doc_id.split("/")[-1].replace("-", " ").title()


def load_nav() -> list[dict]:
    """Parse sidebars.js via Node require and return a nav structure matching
    the format used by render_toc_pdf / compute_offsets."""
    node = shutil.which("node")
    if not node:
        sys.exit("node is required (sidebars.js is a CommonJS module)")
    script = (
        "const s = require('./sidebars.js');"
        "process.stdout.write(JSON.stringify(s.mainSidebar));"
    )
    result = subprocess.run(
        [node, "-e", script],
        cwd=DOCS_SITE, check=True, capture_output=True, text=True,
    )
    raw = json.loads(result.stdout)

    nav: list[dict] = []
    for entry in raw:
        if isinstance(entry, str):
            # Top-level standalone page (e.g. "intro")
            nav.append({
                "title": doc_title(entry),
                "items": [{"label": doc_title(entry), "path": f"/{entry}"}],
            })
        elif isinstance(entry, dict) and entry.get("type") == "category":
            items = [
                {"label": doc_title(item), "path": f"/{item}"}
                for item in entry.get("items", [])
                if isinstance(item, str)
            ]
            if items:
                nav.append({"title": entry["label"], "items": items})
    return nav


def wait_for_server(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except (urllib.error.URLError, socket.timeout):
            time.sleep(0.3)
    sys.exit(f"preview server never came up at {url}")


def render_page_pdf(browser: Browser, url: str, out: Path) -> None:
    page = browser.new_page()
    page.emulate_media(media="print", color_scheme="light")
    page.goto(url, wait_until="networkidle")
    page.pdf(path=str(out), format="A4", print_background=True, margin=PDF_MARGIN)
    page.close()


def render_toc_pdf(
    browser: Browser,
    nav: list[dict],
    page_numbers: dict[str, int],
    out: Path,
) -> None:
    groups_html = []
    for group in nav:
        rows = "\n".join(
            f'<li><span class="label">{html.escape(item["label"])}</span>'
            f'<span class="dots"></span>'
            f'<span class="num">{page_numbers[item["path"]]}</span></li>'
            for item in group["items"]
        )
        groups_html.append(f'<h2>{html.escape(group["title"])}</h2><ul>{rows}</ul>')

    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>
      body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
              color: #1c1e21; padding: 0 0.5rem; }}
      h1 {{ font-size: 2rem; margin-bottom: 0.2rem; }}
      .sub {{ color: #5b6270; margin-bottom: 2.5rem; font-size: 1rem; }}
      h2 {{ font-size: 0.85rem; text-transform: uppercase; letter-spacing: .04em;
            color: #5b6270; margin: 1.5rem 0 0.4rem; }}
      ul {{ list-style: none; margin: 0; padding: 0; }}
      li {{ display: flex; align-items: baseline; font-size: 1rem; padding: 0.28rem 0; }}
      .label {{ white-space: nowrap; }}
      .dots {{ flex: 1; border-bottom: 1px dotted #c7cad1; margin: 0 0.5rem 0.3rem; }}
      .num {{ color: #5b6270; }}
    </style></head><body>
      <h1>FantasyConsole Documentation</h1>
      <div class="sub">TurtleReader — ESP32-S3 Lua Game Console</div>
      {"".join(groups_html)}
    </body></html>"""

    page = browser.new_page()
    page.set_content(doc)
    page.pdf(path=str(out), format="A4", print_background=True, margin=PDF_MARGIN)
    page.close()


def compute_offsets(
    flat_pages: list[dict],
    page_pdfs: list[Path],
    toc_page_count: int,
) -> dict[str, int]:
    """Return 1-indexed page number each route starts on, after the TOC."""
    offsets: dict[str, int] = {}
    cursor = toc_page_count
    for item, pdf_path in zip(flat_pages, page_pdfs):
        offsets[item["path"]] = cursor + 1
        cursor += len(PdfReader(pdf_path).pages)
    return offsets


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=DOCS_SITE / "turtlereader-docs.pdf",
        help="Output PDF path (default: docs/site/turtlereader-docs.pdf)",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip 'npm run build' and use the existing build/ folder",
    )
    args = parser.parse_args()

    nav = load_nav()
    flat_pages = [item for group in nav for item in group["items"]]
    print(f"Exporting {len(flat_pages)} pages across {len(nav)} sections")

    if not args.no_build:
        run(["npm", "run", "build"])

    preview = subprocess.Popen(
        ["npx", "docusaurus", "serve", "--port", str(PORT), "--no-open"],
        cwd=DOCS_SITE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(BASE_URL + "/")

        with tempfile.TemporaryDirectory() as tmp_str, sync_playwright() as pw:
            tmp = Path(tmp_str)
            browser = pw.chromium.launch()

            page_pdfs: list[Path] = []
            for i, item in enumerate(flat_pages):
                out = tmp / f"page-{i:03d}.pdf"
                render_page_pdf(browser, BASE_URL + item["path"], out)
                page_pdfs.append(out)
                print(f"  rendered {item['path']}")

            # Render TOC once to measure its page count, then re-render with
            # correct offsets if it spans more than one page.
            toc_pdf = tmp / "toc.pdf"
            offsets = compute_offsets(flat_pages, page_pdfs, toc_page_count=1)
            render_toc_pdf(browser, nav, offsets, toc_pdf)
            actual_toc_pages = len(PdfReader(toc_pdf).pages)
            if actual_toc_pages != 1:
                offsets = compute_offsets(flat_pages, page_pdfs, toc_page_count=actual_toc_pages)
                render_toc_pdf(browser, nav, offsets, toc_pdf)

            browser.close()

            writer = PdfWriter()
            writer.append(str(toc_pdf))
            for pdf_path in page_pdfs:
                writer.append(str(pdf_path))

            for group in nav:
                first_path = group["items"][0]["path"]
                parent = writer.add_outline_item(group["title"], offsets[first_path] - 1)
                for item in group["items"]:
                    writer.add_outline_item(item["label"], offsets[item["path"]] - 1, parent=parent)

            args.output.parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "wb") as f:
                writer.write(f)
            print(f"wrote {args.output} ({len(writer.pages)} pages)")
    finally:
        preview.terminate()
        preview.wait(timeout=5)


if __name__ == "__main__":
    main()
