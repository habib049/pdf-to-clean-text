# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub:
**Security → Report a vulnerability** on this repository. Don't open a public issue.

You should get a reply within a week.

## Things to know

- This tool parses untrusted files. PDF parsing is done by docling and pypdfium2 (PDFium); a flaw in
  either can affect this project, so keep them updated.
- Extracted text is cached in plain form under `~/.cache/pdf-to-clean-text/` with owner-only
  permissions. Use `--no-cache` for sensitive documents, or delete that folder.
- Nothing is redacted: the output contains whatever the PDF contains.
- The tool itself makes no network requests. docling downloads its models from Hugging Face on first
  use, and its OCR engine, onnxruntime, ships its own telemetry client.
