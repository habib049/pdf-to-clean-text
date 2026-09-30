"""Read a PDF as clean markdown, and say which parts not to trust.

A thin layer over docling: it already handles layout, reading order, tables and OCR. This adds the
watermark strip, page markers, warnings about OCR'd pages, section search, and errors phrased for a human.

    python pdf_to_clean_text.py FILE.pdf > doc.md 2> doc.log
    python pdf_to_clean_text.py FILE.pdf --find "refund policy"
    python pdf_to_clean_text.py FILE.pdf --outline           # headings with their pages
    python pdf_to_clean_text.py FILE.pdf --map               # the card a reader agent wrote, else the outline
    python pdf_to_clean_text.py FILE.pdf --pages 12-14       # just those pages

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


def _tidy(md: str) -> str:
    """Drop blank lines and collapse runs of spaces: they cost tokens and mean nothing to a model reading the text.

    docling separates every paragraph with a blank line, and justified text comes through with doubled spaces.
    Leading indentation is kept, and code blocks are left exactly as they are, since there spacing can be content.
    """
    out, fenced = [], False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            if not line.strip():
                continue
            line = re.sub(r"(?<=\S) {2,}", " ", line.rstrip())
        out.append(line)
    return "\n".join(out)


def _nearby_caption(doc, pic) -> str:
    """The closest "Figure N" line touching a picture, for when docling didn't link one.

    docling links a caption to its figure when its layout model labels the caption, and that varies with the
    platform: the same page linked it on macOS and not on Linux, leaving a false "no caption" warning with the
    caption sitting right under the figure. So when there's no link, take the nearest matching line on the same
    page that either overlaps the picture horizontally and sits within CAPTION_MAX_GAP points above or below it
    (the common case), or overlaps it vertically and sits within CAPTION_MAX_GAP points to either side (a
    caption beside the figure, as in some two-column layouts). A line that overlaps on neither axis is diagonal
    to the picture, not adjacent to it, and is never a match.
    """
    pb = pic.prov[0]
    p_lo, p_hi = sorted((pb.bbox.b, pb.bbox.t))
    best = None
    for t in doc.texts:
        if not t.prov or t.prov[0].page_no != pb.page_no or not _CAPTION.match(t.text.strip()):
            continue
        tb = t.prov[0].bbox
        t_lo, t_hi = sorted((tb.b, tb.t))
        h_overlap = min(pb.bbox.r, tb.r) - max(pb.bbox.l, tb.l)
        v_overlap = min(p_hi, t_hi) - max(p_lo, t_lo)
        if h_overlap > 0:
            gap = max(0, max(p_lo, t_lo) - min(p_hi, t_hi))
        elif v_overlap > 0:
            gap = max(0, max(pb.bbox.l, tb.l) - min(pb.bbox.r, tb.r))
        else:
            continue
        if gap <= CAPTION_MAX_GAP and (best is None or gap < best[0]):
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


def _script_digest() -> str:
    """A stand-in for a hand-maintained CACHE_VERSION: this script's own source, hashed, so a change to any
    constant or code path here invalidates old cache entries automatically instead of relying on someone
    remembering to bump a number. A stale cache entry costs nothing but a re-conversion, so hashing the whole
    file (docstrings included) is fine even though it invalidates more than strictly necessary.
    """
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        return "unknown"


def _cache_root() -> Path:
    # PDF_TO_CLEAN_TEXT_CACHE has its own name on purpose: XDG_CACHE_HOME also moves Hugging Face's
    # model cache, so overriding it would force a re-download of ~500 MB of docling models.
    return Path(os.environ.get("PDF_TO_CLEAN_TEXT_CACHE") or Path.home() / ".cache" / "pdf-to-clean-text")


def _cache_file(digest: str) -> Path:
    root = _cache_root()
    try:
        docling_version = metadata.version("docling")
    except metadata.PackageNotFoundError:
        docling_version = "unknown"
    # The key covers everything the output depends on: the file, this script's own logic, and docling itself.
    return root / f"{digest[:40]}-v{_script_digest()}-d{docling_version}.json"


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
    text = "\n".join(f"<!-- page {n} -->\n{_tidy(md).strip()}" for n, md in pages.items())
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


_MARKER = re.compile(r"^<!-- page (\d+) -->$", re.MULTILINE)


def _split_pages(text: str) -> dict[int, str]:
    parts = _MARKER.split(text)  # ["", "1", body, "2", body, ...]
    return {int(n): body.strip() for n, body in zip(parts[1::2], parts[2::2])}


def outline(text: str) -> list[str]:
    """Every heading with the page it's on, as "p12 Pricing": the document's structure for a few percent of its
    tokens, so a reader can pick the pages a task needs. docling's heading levels aren't reliable, so they're
    left out. A document with no headings gets each page's first line instead.
    """
    pages = _split_pages(text)
    heads = [f"p{n} {line.lstrip('#').strip()}" for n, body in pages.items()
             for line in body.splitlines() if line.startswith("#")]
    if heads:
        return heads
    return [f"p{n} {body.splitlines()[0][:80]}" for n, body in pages.items() if body]


def parse_pages(spec: str, npages: int) -> list[int]:
    """"3", "3-5" or "1,4,7-9" -> sorted page numbers. A bad spec raises ValueError with a message for a user."""
    wanted = set()
    for part in spec.split(","):
        first, dash, last = part.strip().partition("-")
        if not first.isdigit() or (dash and not last.isdigit()):
            raise ValueError(f"can't read the page range {part.strip()!r}; use a form like 3, 3-5 or 1,4,7-9")
        lo, hi = int(first), int(last or first)
        if not 1 <= lo <= hi <= npages:
            raise ValueError(f"pages {part.strip()} aren't in this document, which has pages 1-{npages}")
        wanted.update(range(lo, hi + 1))
    return sorted(wanted)


def select_pages(text: str, spec: str) -> str:
    """Only the requested pages, each still under its page marker so it can be cited."""
    pages = _split_pages(text)
    return "\n".join(f"<!-- page {n} -->\n{pages[n]}".rstrip() for n in parse_pages(spec, len(pages)))


NOTES_MIN_SHARE = 0.2  # notes shorter than this share of the text have summarized facts away, not compressed them
_PAGE_TAG = re.compile(r"(?<![\w/])p(\d{1,4})(?:/(\d{1,4}))?(?![\d-])")  # p12 or p4/22; not a range like p3-6
_LABEL = re.compile(r"^#+\s*([A-Z][A-Za-z]+\.?\s+\d+(?:\.\d+)*)\b", re.MULTILINE)  # "## Question 5.9 · ..."


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", s).lower()


def check_notes(text: str, notes: str) -> list[str]:
    """What's wrong with a reader agent's notes, as plain sentences; empty when they cover the whole document.

    A page counts as covered when some note carries its tag (`p12`, or `p4/22` for a question and its answer).
    A range like `p3-6` in a heading doesn't count: it can sit above notes that skipped half the range. Every
    numbered heading label (`Question 5.9`, `Section 4.2`, `Table 3`) must appear too, since that's what a later
    task looks things up by.
    """
    tagged = {int(n) for pair in _PAGE_TAG.findall(notes) for n in pair if n}
    missing = [n for n, body in _split_pages(text).items() if len(body) >= 100 and n not in tagged]
    problems = []
    if missing:
        spans = ", ".join(f"{a}-{b}" if a != b else f"{a}" for a, b in _runs(set(missing)))
        problems.append(f"pages {spans} have text but no notes tagged with their page")
    in_notes = _plain(notes)
    lost = list(dict.fromkeys(l for l in _LABEL.findall(text) if _plain(l) not in in_notes))
    if lost:
        more = f" and {len(lost) - 10} more" if len(lost) > 10 else ""
        problems.append(f"these headings' labels are missing from the notes: {', '.join(lost[:10])}{more}")
    share = len(notes) / max(len(text), 1)
    if share < NOTES_MIN_SHARE:
        problems.append(f"the notes are {share:.0%} of the text's length, under {NOTES_MIN_SHARE:.0%}: facts were "
                        "summarized away rather than compressed")
    return problems


def compiled_paths(path) -> tuple[Path, Path]:
    """Where this PDF's card (a short map of it) and notes (a condensed copy) live once a reader agent writes them.

    Keyed by the file's content alone, so they survive script and docling upgrades: they cost a model's full read
    of the document to rebuild, and depend on neither.
    """
    # ponytail: these aren't pruned with the cache's JSON entries; they're small, prune them too if that changes.
    stem = _file_digest(Path(path))[:40]
    return _cache_root() / f"{stem}.card.md", _cache_root() / f"{stem}.notes.md"


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
    """Download docling's layout and table models now (about 0.5 GB, once), so the first real conversion isn't
    the one that stalls.

    The OCR path is exercised too, converting the same warm-up PDF a second time with OCR on. RapidOCR's own
    checkpoints ship inside its pip package (`docling[rapidocr]`), not fetched at runtime, so this isn't
    downloading anything extra - it just means a broken OCR setup (a bad install, a missing native dependency)
    is caught here instead of surfacing on someone's first scanned PDF.

    docling-tools' own `models download` isn't used: it saves to ~/.cache/docling, while the conversion reads the
    Hugging Face cache, so the models would be downloaded again. Converting a page goes through the real path.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "warmup.pdf"
        path.write_bytes(_warmup_pdf_bytes())
        try:
            _convert(path, ocr=False)
            _convert(path, ocr=True)
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
    view = ap.add_mutually_exclusive_group()
    view.add_argument("--find", action="append", metavar="TERM", help="print only the sections containing TERM "
                      "(repeat for several terms; any match counts)")
    view.add_argument("--outline", action="store_true", help="print only the headings, each with its page")
    view.add_argument("--map", action="store_true", help="print the document's card if a reader agent has written "
                      "one, otherwise the outline")
    view.add_argument("--pages", metavar="RANGE", help="print only these pages, e.g. 3, 3-5 or 1,4,7-9")
    view.add_argument("--compiled-paths", action="store_true", help="print where this PDF's card and notes are "
                      "kept (they may not exist yet), then exit")
    view.add_argument("--check-notes", action="store_true", help="check that the notes cover every page with text "
                      "and aren't cut to a summary; prints ok, or what's missing (exit 1)")
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
    if args.compiled_paths:
        if args.no_cache:
            ap.error("--compiled-paths is for notes kept on disk, so it can't be used with --no-cache")
        try:
            _preflight(Path(args.pdf))
        except PdfError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        card, notes = compiled_paths(args.pdf)
        card.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        state = lambda p: "exists" if p.is_file() else "missing"
        print(f"info: card {state(card)}, notes {state(notes)}", file=sys.stderr)
        print(f"card {card}\nnotes {notes}")
        return 0
    try:
        result = extract(args.pdf, use_cache=not args.no_cache)
    except PdfError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    try:
        tokens = round(len(result.text) / CHARS_PER_TOKEN, -2)
        print(f"info: {result.text.count('<!-- page ')} pages, about {tokens:,.0f} tokens as markdown", file=sys.stderr)
        if args.check_notes:
            notes = None if args.no_cache else compiled_paths(args.pdf)[1]
            if not notes or not notes.is_file():
                print("error: there are no notes for this PDF yet (see --compiled-paths)", file=sys.stderr)
                return 1
            problems = check_notes(result.text, notes.read_text(encoding="utf-8"))
            print("\n".join(problems) or "ok: the notes cover every page with text")
            return 1 if problems else 0
        card = compiled_paths(args.pdf)[0] if args.map and not args.no_cache else None
        if card and card.is_file():
            print("info: the document's card, written by a reader agent", file=sys.stderr)
            print(card.read_text(encoding="utf-8").strip())
        elif args.outline or args.map:
            if args.map:
                print("info: no card yet, so the outline instead", file=sys.stderr)
            print("\n".join(outline(result.text)))
        elif args.pages:
            try:
                print(select_pages(result.text, args.pages))
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
        elif args.find:
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
