# Poppler binaries

This folder contains optional Poppler binaries used by the OCR skill.

`iris_pdf_to_images.mjs` discovers Poppler in this order:

1. `--poppler-bin`
2. `IRIS_POPPLER_BIN` or `POPPLER_BIN`
3. `scripts/bin/poppler/<platform>/bin`
4. `scripts/bin/poppler/<platform>`
5. `scripts/bin`
6. `PATH`

Packaged layout examples:

```text
scripts/bin/poppler/win/bin/pdfinfo.exe
scripts/bin/poppler/win/bin/pdftoppm.exe
scripts/bin/poppler/win/share/poppler
scripts/bin/poppler/linux/bin/pdfinfo
scripts/bin/poppler/linux/bin/pdftoppm
scripts/bin/poppler/macos/bin/pdfinfo
scripts/bin/poppler/macos/bin/pdftoppm
```

Keep the Poppler license files beside the binaries when bundling them.
