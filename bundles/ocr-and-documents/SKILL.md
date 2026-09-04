---
name: ocr-and-documents
description: "Render PDF/image files into page images so TTG OS can OCR them with the configured Iris OCR vision tool."
version: 3.0.0
author: TTG OS
license: MIT
platforms: [linux, macos, windows]
metadata:
  iris:
    tags: [OCR, PDF, Vision, Documents, Vietnamese, Scanned-PDF]
    related_skills: [pdf, docx, powerpoint]
---

# OCR File With Iris Vision

Use this skill when the user asks to OCR a file, read a scanned PDF, extract
text from document images, or recover text from document pages that have no
text layer.

The correct Iris pipeline is:

1. If the input is not PDF/image, convert it to PDF first with LibreOffice
   (`soffice --headless --convert-to pdf`).
2. Render PDF pages to PNG images with Poppler (`pdfinfo` + `pdftoppm`).
3. Read the generated `manifest.json`.
4. Call `iris_vision_ocr` with the generated `manifest.json`.
5. Report the exact markdown and JSON output paths returned by the tool.

The render script only prepares page images. OCR reading belongs to the
`iris_vision_ocr` tool, which uses the OCR model configured in Settings > OCR
or the app environment (`IRIS_VISION_MODEL`, `IRIS_VISION_API_KEY`,
`IRIS_VISION_BASE_URL`).

## Main Command

Render a PDF into an OCR working folder:

```powershell
node apps/desktop/assets/bundled-skills/ocr-and-documents/scripts/iris_pdf_to_images.mjs input.pdf --out-dir ocr_pages
```

Render selected pages:

```powershell
node apps/desktop/assets/bundled-skills/ocr-and-documents/scripts/iris_pdf_to_images.mjs input.pdf --pages 1-3,7 --out-dir ocr_pages
```

Prepare an image file:

```powershell
node apps/desktop/assets/bundled-skills/ocr-and-documents/scripts/iris_pdf_to_images.mjs scan.png --out-dir ocr_pages
```

Prepare a non-PDF document by converting it to PDF first, then rendering it:

```powershell
node apps/desktop/assets/bundled-skills/ocr-and-documents/scripts/iris_pdf_to_images.mjs file.docx --out-dir ocr_pages
node apps/desktop/assets/bundled-skills/ocr-and-documents/scripts/iris_pdf_to_images.mjs deck.pptx --out-dir ocr_pages
node apps/desktop/assets/bundled-skills/ocr-and-documents/scripts/iris_pdf_to_images.mjs workbook.xlsx --out-dir ocr_pages
```

The command writes:

```text
ocr_pages/manifest.json
ocr_pages/page-0001.png
ocr_pages/page-0002.png
...
```

For converted documents it also writes:

```text
ocr_pages/converted-pdf/<source-name>.pdf
```

## Agent OCR Procedure

After rendering:

1. Read `ocr_pages/manifest.json`.
2. Confirm `pages[]` is non-empty. If not, report the render/convert problem.
3. Call:

```json
{
  "manifest_path": "ocr_pages/manifest.json"
}
```

with the `iris_vision_ocr` tool. For selected pages, pass:

```json
{
  "manifest_path": "ocr_pages/manifest.json",
  "pages": "1-3,7"
}
```

4. Let `iris_vision_ocr` read each `pages[].imagePath`, call the configured
   vision endpoint, and write `ocr.md` plus `ocr.json`.
5. Preserve Vietnamese accents, numbers, punctuation,
   headings, table-like rows, stamps, signatures, checkboxes, and page
   boundaries.
6. The markdown output path is returned by the tool, normally:

```text
ocr_pages/ocr.md
```

7. The JSON output path is returned by the tool, normally:

```text
ocr_pages/ocr.json
```

8. Tell the user the exact paths of the markdown and JSON outputs.

## How Vision Is Invoked

`iris_vision_ocr` calls an OpenAI-compatible `/chat/completions` endpoint with
the page image as a base64 `image_url`, matching the OCR approach used by the
Iris wiki worker. This bypasses Harness `read_image` model-catalog gating, so a
vision-capable model can be used even when the active chat model is text-only.

If the tool says OCR is not configured, ask the user to open Settings > OCR or
set app-level environment variables:

```text
IRIS_VISION_BASE_URL=https://api.openai.com/v1
IRIS_VISION_API_KEY=<key>
IRIS_VISION_MODEL=gpt-4o-mini
```

## File-Type Routing

- PDF: render directly with `iris_pdf_to_images.mjs`.
- Image (`.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, `.tiff`): copy into
  the OCR folder and read it as one page.
- Office/document (`.doc`, `.docx`, `.ppt`, `.pptx`, `.xls`, `.xlsx`, `.odt`,
  `.ods`, `.odp`, `.rtf`, `.html`, `.txt`, `.csv`): let
  `iris_pdf_to_images.mjs` convert it to PDF with LibreOffice, then render.
- Unsupported binary formats: report that the file must be converted to PDF
  first and ask for a PDF export or a supported Office/image format.

## Poppler Bundled In Skill

Windows Poppler is bundled in:

```text
apps/desktop/assets/bundled-skills/ocr-and-documents/scripts/bin/poppler/win/bin
apps/desktop/assets/bundled-skills/ocr-and-documents/scripts/bin/poppler/win/share/poppler
```

Binary lookup order:

1. `--poppler-bin`
2. `IRIS_POPPLER_BIN` or `POPPLER_BIN`
3. `scripts/bin/poppler/<win|linux|macos>/bin`
4. `scripts/bin/poppler/<win|linux|macos>`
5. `scripts/bin`
6. `PATH`

For Ubuntu server, install Poppler with:

```bash
sudo apt-get update
sudo apt-get install -y poppler-utils
```

or bundle Linux binaries under:

```text
scripts/bin/poppler/linux/bin/pdfinfo
scripts/bin/poppler/linux/bin/pdftoppm
```

## LibreOffice For Non-PDF Conversion

Non-PDF office/document files require LibreOffice `soffice`.

Lookup order:

1. `--soffice-bin`
2. `IRIS_SOFFICE_BIN` or `SOFFICE_BIN`
3. `PATH`

Windows example:

```powershell
$env:IRIS_SOFFICE_BIN='C:\Program Files\LibreOffice\program\soffice.exe'
```

Ubuntu example:

```bash
sudo apt-get update
sudo apt-get install -y libreoffice
```

## Quality Rules

- Do not summarize unless the user asks for a summary.
- Do not say a scanned PDF has no content just because text-layer extraction is
  empty.
- If the file is not PDF/image, convert it to PDF first, then render and OCR
  the converted PDF.
- If a region is unreadable, mark it as `[khong ro]` instead of inventing text.
- For large PDFs, choose or ask for a page range before processing the entire
  document.
- Keep page order and page boundaries.
- Report exact output file paths at the end.

## Troubleshooting

If Poppler is missing, report that `pdfinfo/pdftoppm` is missing and give one
of these fixes:

```powershell
$env:IRIS_POPPLER_BIN='C:\path\to\poppler\bin'
```

or install Poppler so `pdfinfo` and `pdftoppm` are available on PATH.

If rendering succeeds but OCR is incomplete, re-inspect the affected page image
at higher DPI:

```powershell
node apps/desktop/assets/bundled-skills/ocr-and-documents/scripts/iris_pdf_to_images.mjs input.pdf --pages 3 --dpi 300 --out-dir ocr_page_3
```

If conversion fails for non-PDF files, report that LibreOffice/`soffice` is
missing or failed, then ask for a PDF export or configure `IRIS_SOFFICE_BIN`.
