# FantasyConsole Docs Site

Docusaurus 3 documentation site for the TurtleReader ESP32-S3 fantasy console.

## Requirements

- Node.js **18+**
- Python **3.10+** (PDF export only)

## Install

```bash
npm install
```

## Dev server

```bash
npm start
```

Opens at `http://localhost:3000`. Pages hot-reload on save.

## Build static site

```bash
npm run build       # output → build/
npm run serve       # preview built site at http://localhost:3000
```

## Export as PDF

Create tnhe envioroment if does't exist

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-pdf.txt
playwright install chromium
```
Create the pdf

```bash
python export_pdf.py                # → turtlereader-docs.pdf
python export_pdf.py -o ~/out.pdf   # custom output path
python export_pdf.py --no-build     # skip rebuild, use existing build/
```

The script builds the site, renders every page through headless Chromium, generates a table of contents, and stitches everything into a single PDF with bookmarks that mirror the sidebar.
