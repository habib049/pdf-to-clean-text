"""Read a PDF as clean markdown, and say which parts not to trust.

A thin layer over docling: it already handles layout, reading order, tables and OCR. This adds the
watermark strip, page markers, warnings about OCR'd pages, section search, and errors phrased for a human.

    python pdf_to_clean_text.py FILE.pdf > doc.md 2> doc.log
    python pdf_to_clean_text.py FILE.pdf --find "refund policy"

    python pdf_to_clean_text.py --warmup     # download docling's models once, before the first real PDF

Importable too: `from pdf_to_clean_text import extract`.
Needs: pip install docling pypdfium2
"""

import argparse
import atexit
import hashlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path

try:
    import pypdfium2 as pdfium
except ImportError:  # reported by _preflight as a typed error, so importing this file never explodes
    pdfium = None

SCANNED_MAX_CHARS = 20  # a page with (almost) no text layer but an embedded image is a scan
MIN_PAGES = 4  # below this, repetition isn't evidence of boilerplate
MIN_FRACTION = 0.6  # a line must recur on this share of pages before it's stripped
MAX_LEN = 40  # boilerplate is short; long repeated text is content
MAX_MATCHES = 10  # --find stops here: a term like "the" would otherwise return the whole document
CHARS_PER_TOKEN = 3.0  # measured on a 30-page document: 75,982 chars was 25,052 tokens
CACHE_VERSION = 4  # bump when the output changes, so stale cached results are ignored
MAX_CACHE_ENTRIES = 200  # oldest-used results are deleted beyond this (a few MB to tens of MB)
# The text is read by a model, not rendered, so markdown's escaping only changes what the document says:
# "&" would become "&amp;" and "max_tokens" would become "max\_tokens", which a search for the real name misses.
_EXPORT = dict(escape_html=False, escape_underscores=False)
_PAGE_BREAK = "\x00pdf-to-clean-text-page-break\x00"  # sentinel; no real document contains a NUL
_CAPTION = re.compile(r"(?i:figure|fig\.?|chart|graph|diagram)\s*\d")  # "Figure 3", "Fig. 2", "Chart 1"
CAPTION_MAX_GAP = 40  # points between a picture and its caption line; real ones sit within ~10-20


# --------------------------------------------------------------------------- errors


class PdfError(Exception):
    """Base class. The message is plain English and safe to show to a user."""


class CorruptPDFError(PdfError):
    pass


class PasswordProtectedError(PdfError):
    pass


class EmptyPDFError(PdfError):
    pass


class DependencyError(PdfError):
    """A required package or model is missing. Says what to do rather than raising a traceback.

    Nothing is installed automatically: docling pulls in torch, several GB, and deciding to write
    that into whatever environment happens to be active is the user's call, not this script's.
    """


# --------------------------------------------------------------------------- results


@dataclass
class Figure:
    page: int
    caption: str


@dataclass
class Result:
    text: str
    warnings: list[str] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)


# --------------------------------------------------------------------------- conversion

_converters = {}


def _converter(ocr: bool):
    """One converter per mode per process; each holds its loaded models, so reuse saves ~20% per call.

    OCR is a separate mode because it is ~95% of docling's run time (measured 8.4s/page with it,
    0.4s/page without) and pages that already have a text layer gain nothing from it. So documents
    are converted with OCR off, and only the pages preflight identified as scanned get OCR'd.
    """
    if ocr not in _converters:
        try:  # slow imports, kept off the error paths
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as e:
            raise DependencyError("docling isn't installed. Run: pip install docling") from e
        options = PdfFormatOption(pipeline_options=PdfPipelineOptions(do_ocr=ocr))
        _converters[ocr] = DocumentConverter(format_options={InputFormat.PDF: options})
    return _converters[ocr]


def _is_network_error(e: Exception) -> bool:
    return isinstance(e, OSError) or type(e).__module__.split(".")[0] in ("httpx", "httpcore", "huggingface_hub")


def _convert(path: Path, ocr: bool, page_range=(1, sys.maxsize)):
    """docling asks Hugging Face about its models on every conversion, even when they are cached, so a
    flaky or missing network can fail a conversion that needs no network at all. On a network error the
    conversion is retried once from the local model cache; only if that fails too is it reported, as a
    network problem, since the PDF itself is fine.
    """
    try:
        return _converter(ocr).convert(path, page_range=page_range).document
    except PdfError:
        raise
    except Exception as e:
        if not _is_network_error(e):
            raise CorruptPDFError(f"{path.name} could not be converted ({type(e).__name__}).") from e
        first = e
    from huggingface_hub import constants  # present whenever docling is: a network error implies it ran

    constants.HF_HUB_OFFLINE = True
    try:
        return _converter(ocr).convert(path, page_range=page_range).document
    except Exception as e:
        raise DependencyError(
            "docling could not reach Hugging Face to check its models, and they are not fully downloaded "
            f"yet ({type(first).__name__}). Check your connection and try again."
        ) from e
    finally:
        constants.HF_HUB_OFFLINE = False


def _preflight(path: Path) -> tuple[set[int], int]:
    """Classify the file before docling sees it, which raises one generic error for every bad input.

    Returns (scanned page numbers, page count).
    """
    if pdfium is None:
        raise DependencyError("pypdfium2 isn't installed. Run: pip install pypdfium2")
    if not path.is_file():
        raise CorruptPDFError(f"No file at {path}.")
    try:
        doc = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise PasswordProtectedError(f"{path.name} is password-protected.") from e
        with open(path, "rb") as f:
            is_pdf = b"%PDF" in f.read(1024)
        raise CorruptPDFError(
            f"{path.name} is damaged or incomplete and can't be read." if is_pdf else f"{path.name} is not a PDF."
        ) from e
    except OSError as e:
        raise CorruptPDFError(f"{path.name} could not be read ({e.strerror or type(e).__name__}).") from e
    try:
        if len(doc) == 0:
            raise EmptyPDFError(f"{path.name} has no pages.")
        scans = set()
        for i in range(len(doc)):
            page = doc[i]
            try:
                chars = len(page.get_textpage().get_text_range().strip())
                if chars < SCANNED_MAX_CHARS and any(True for _ in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE])):
                    scans.add(i + 1)
            finally:
                page.close()
        return scans, len(doc)
    finally:
        doc.close()


def _norm(text: str) -> str:
    """Digits are dropped so "Page 3" and "Page 4" compare equal."""
    return re.sub(r"\d+", "", text).strip().lower()


def strip_repeated(doc) -> list[str]:
    """Delete short body lines that recur at the same position on >=60% of pages. Returns the removed texts.

    docling already drops headers and footers, but a watermark comes through as body text on every
    page. Repetition across pages is required, so a one-off line near a margin is never touched.
    """
    npages = len(doc.pages)
    if npages < MIN_PAGES:
        return []
    groups = defaultdict(list)
    for t in doc.texts:
        if t.label != "text" or not t.prov or len(t.text) > MAX_LEN:
            continue
        b = t.prov[0].bbox
        # Positions are bucketed to a 20pt grid to absorb rendering jitter; a stamp that drifts across a
        # bucket edge won't group, and will survive. Clustering would fix that, if it ever matters.
        groups[(_norm(t.text), round(b.l / 20), round(b.t / 20))].append(t)
    hits = [g for g in groups.values() if len({t.prov[0].page_no for t in g}) >= npages * MIN_FRACTION]
    doc.delete_items(node_items=[t for g in hits for t in g])
    return sorted({g[0].text for g in hits})


def _page_markdown(doc, first: int, last: int) -> dict[int, str]:
    """Markdown per page, in one pass. Exporting page by page rescans the whole document each time, which was
    measured at 21x slower on 30 pages and grows with length; a page break placeholder does it in one.
    """
    chunks = doc.export_to_markdown(page_break_placeholder=_PAGE_BREAK, **_EXPORT).split(_PAGE_BREAK)
    if len(chunks) == last - first + 1:
        return dict(zip(range(first, last + 1), chunks))
    # A page with no content can change the number of breaks; then fall back to the slow, exact way.
    return {n: doc.export_to_markdown(page_no=n, **_EXPORT) for n in range(first, last + 1)}


def _nearby_caption(doc, pic) -> str:
    """The closest "Figure N" line touching a picture, for when docling didn't link one.

    docling links a caption to its figure when its layout model labels the caption, and that varies with the
    platform: the same page linked it on macOS and not on Linux, leaving a false "no caption" warning with the
    caption sitting right under the figure. So when there's no link, take the nearest matching line on the same
    page that overlaps the picture horizontally and is within CAPTION_MAX_GAP points of it vertically.
    """
    pb = pic.prov[0]
    p_lo, p_hi = sorted((pb.bbox.b, pb.bbox.t))
    best = None
    for t in doc.texts:
        if not t.prov or t.prov[0].page_no != pb.page_no or not _CAPTION.match(t.text.strip()):
            continue
        tb = t.prov[0].bbox
        t_lo, t_hi = sorted((tb.b, tb.t))
        gap = max(0, max(p_lo, t_lo) - min(p_hi, t_hi))
        if min(pb.bbox.r, tb.r) - max(pb.bbox.l, tb.l) > 0 and gap <= CAPTION_MAX_GAP and (best is None or gap < best[0]):
            best = (gap, t.text.strip())
    return best[1] if best else ""


def _runs(pages: set[int]) -> list[tuple[int, int]]:
    """{1, 2, 3, 7} -> [(1, 3), (7, 7)]: consecutive scanned pages are OCR'd in one conversion."""
    runs = []
    for p in sorted(pages):
        if runs and p == runs[-1][1] + 1:
            runs[-1][1] = p
        else:
            runs.append([p, p])
    return [tuple(r) for r in runs]


# --------------------------------------------------------------------------- cache


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):  # in blocks, so a huge PDF isn't held in memory
            h.update(block)
    return h.hexdigest()


def _cache_file(digest: str) -> Path:
    # PDF_TO_CLEAN_TEXT_CACHE has its own name on purpose: XDG_CACHE_HOME also moves Hugging Face's
    # model cache, so overriding it would force a re-download of ~500 MB of docling models.
    root = Path(os.environ.get("PDF_TO_CLEAN_TEXT_CACHE") or Path.home() / ".cache" / "pdf-to-clean-text")
    try:
        docling_version = metadata.version("docling")
    except metadata.PackageNotFoundError:
        docling_version = "unknown"
    # The key covers everything the output depends on: the file, this script's format, docling itself.
    return root / f"{digest[:40]}-v{CACHE_VERSION}-d{docling_version}.json"


def _cache_load(digest: str):
    f = _cache_file(digest)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        result = Result(data["text"], data["warnings"], [Figure(**x) for x in data["figures"]])
        os.utime(f)  # mark as recently used, so pruning removes the least recently read
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _cache_save(digest: str, result: Result) -> None:
    """Cached text can be as sensitive as the PDF it came from, so the directory and files are owner-only."""
    try:  # a cache that can't be written is only a missed speed-up, never a failure
        f = _cache_file(digest)
        f.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        f.write_text(json.dumps(asdict(result)), encoding="utf-8")
        f.chmod(0o600)
        old = sorted(f.parent.glob("*.json"), key=lambda p: p.stat().st_mtime)[:-MAX_CACHE_ENTRIES]
        for p in old:
            p.unlink(missing_ok=True)
    except OSError:
        pass


# --------------------------------------------------------------------------- extract


def extract(path, use_cache: bool = True) -> Result:
    """Convert a PDF. With use_cache, results are stored by content hash so re-reading a file is instant."""
    path = Path(path)
    scans, npages = _preflight(path)
    digest = _file_digest(path) if use_cache else None
    if use_cache and (cached := _cache_load(digest)):
        return cached
    warnings = [f"page {p}: scanned page, text came from OCR and was not verified" for p in sorted(scans)]

    doc = _convert(path, ocr=False)
    removed = strip_repeated(doc)
    if removed:
        warnings.append(f"removed lines repeated across pages: {removed}")

    figures = []
    for pic in doc.pictures:
        page = pic.prov[0].page_no
        if page in scans:  # the "figure" on a scanned page is the page itself
            continue
        caption = pic.caption_text(doc) or _nearby_caption(doc, pic)
        figures.append(Figure(page, caption))
        if not caption:
            warnings.append(f"page {page}: figure with no caption found")

    pages = _page_markdown(doc, 1, npages)
    drop = {_norm(r) for r in removed} | {"<!-- image -->"}  # on a scanned page the one image is the page
    for first, last in _runs(scans):
        ocr_doc = _convert(path, ocr=True, page_range=(first, last))
        for n, md in _page_markdown(ocr_doc, first, last).items():
            pages[n] = "\n".join(line for line in md.splitlines() if _norm(line) not in drop)

    if not "".join(pages.values()).strip():
        raise EmptyPDFError(f"{path.name} has no extractable text.")
    # Page markers make the page numbers in `warnings` locatable, and let a caller cite a page back.
    text = "\n\n".join(f"<!-- page {n} -->\n\n{md.strip()}" for n, md in pages.items())
    result = Result(text.strip(), warnings, figures)
    if use_cache:
        _cache_save(digest, result)
    return result


# --------------------------------------------------------------------------- search


def find_sections(text: str, terms: list[str]) -> tuple[list[str], int]:
    """Return (sections that contain any of the terms, total matches).

    A section runs from one "## " heading to the next, which is the natural unit: one question, one
    rationale, one chapter. A document with no headings falls back to one section per page. Each
    section is prefixed with the page it starts on, so it can be cited. Matching is a plain,
    case-insensitive substring: it finds words that are in the text, not meanings that aren't.
    Hyphens are ignored on both sides, because docling joins a word split across lines ("large-scale"
    becomes "largescale") and a search for the real spelling should still find it.
    """
    lines = text.splitlines()
    cut = re.compile(r"## " if any(l.startswith("## ") for l in lines[1:]) else r"<!-- page \d+ -->")
    sections, current, page = [], [], 1
    for line in lines:
        if m := re.match(r"<!-- page (\d+) -->", line):
            page = int(m.group(1))
        if cut.match(line) and current:
            sections.append((current[0][0], "\n".join(l for _, l in current).strip()))
            current = []
        current.append((page, line))
    if current:
        sections.append((current[0][0], "\n".join(l for _, l in current).strip()))
    plain = lambda s: s.lower().replace("-", "")
    wanted = [plain(t) for t in terms]
    hits = [(pg, body) for pg, body in sections if any(t in plain(body) for t in wanted)]
    return [f"<!-- match: starts on page {pg} -->\n{body}" for pg, body in hits[:MAX_MATCHES]], len(hits)


# --------------------------------------------------------------------------- warm-up


def _warmup_pdf_bytes() -> bytes:
    """A one-page PDF built in memory. Converting it is what makes docling fetch its models."""
    stream = b"BT /F1 12 Tf 20 50 Td (warm-up) Tj ET"
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    return out + b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def warmup() -> int:
    """Download docling's models now (about 0.5 GB, once), so the first real conversion isn't the one that stalls.

    docling-tools' own `models download` isn't used: it saves to ~/.cache/docling, while the conversion reads the
    Hugging Face cache, so the models would be downloaded again. Converting a page goes through the real path.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "warmup.pdf"
        path.write_bytes(_warmup_pdf_bytes())
        try:
            _convert(path, ocr=False)
        except PdfError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    print("info: docling's models are downloaded and ready", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- cli


def _quieten():
    """Keep stderr readable so the warnings aren't buried in library chatter.

    This runs only from the command line, so importing this file leaves the caller's logging alone.
    docling's loggers inherit their level from "docling", so setting it there covers every module;
    the OCR engine sets its own level at start-up, which would undo that, so it gets a filter instead.
    Real failures still arrive as exceptions and are reported as errors below.
    """
    os.environ.setdefault("TQDM_DISABLE", "1")  # model loading draws progress bars on stderr
    for name in ("docling", "docling_core", "docling_parse"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    logging.getLogger("RapidOCR").addFilter(lambda record: record.levelno >= logging.WARNING)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=f"python {Path(__file__).name}", description="Read a PDF as clean markdown.")
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--warmup", action="store_true", help="download docling's models now (about 0.5 GB, once) so the "
                    "first real conversion isn't the one that stalls, then exit")
    ap.add_argument("--find", action="append", metavar="TERM", help="print only the sections containing TERM "
                    "(repeat for several terms; any match counts)")
    ap.add_argument("--no-cache", action="store_true", help="don't read or write the result cache "
                    "(the cache holds the extracted text, so use this for sensitive documents)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):  # a Windows console defaults to a codec that can't print most text
        sys.stdout.reconfigure(encoding="utf-8")
    _quieten()
    if args.warmup:
        return warmup()
    if not args.pdf:
        ap.error("a PDF is required (or use --warmup)")
    try:
        result = extract(args.pdf, use_cache=not args.no_cache)
    except PdfError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    try:
        tokens = round(len(result.text) / CHARS_PER_TOKEN, -2)
        print(f"info: {result.text.count('<!-- page ')} pages, about {tokens:,.0f} tokens as markdown", file=sys.stderr)
        if args.find:
            shown, total = find_sections(result.text, args.find)
            print("\n\n".join(shown))  # stdout is only what was asked for; diagnostics go to stderr
            if total > len(shown):
                print(f"warning: {total} sections matched, showing the first {len(shown)}; use a more specific term", file=sys.stderr)
            elif not shown:
                print(f"warning: no section contains {args.find}; try other words the document might use", file=sys.stderr)
        else:
            print(result.text)  # stdout is the document only; diagnostics go to stderr
        for w in result.warnings:
            print(f"warning: {w}", file=sys.stderr)
    except BrokenPipeError:  # the reader (for example `| head`) closed early; that is not an error
        pass
    return 0


if __name__ == "__main__":
    code = main()
    # Skip normal interpreter shutdown. docling's OCR engine (onnxruntime) tears down its Microsoft
    # telemetry client at exit while a worker thread can still be handling a response; when they collide
    # the process aborts with SIGABRT after all the work is done: exit code 134 and a macOS "Python quit
    # unexpectedly" dialog. Everything has been written by now, so flush and leave without the teardown.
    # The registered exit handlers still run first (multiprocessing uses them to release its semaphores);
    # only the C++ static destructors, where the crash happens, are skipped.
    atexit._run_exitfuncs()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except OSError:  # includes BrokenPipeError
            pass
    os._exit(code)
