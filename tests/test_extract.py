"""Tests for pdf_to_clean_text.

Most run the real docling on a generated fixture (about 20 seconds for the lot); the rest are fast unit tests
that need no models. Needs: pip install pytest reportlab matplotlib (plus the skill's docling and pypdfium2).
"""
import logging
import os
import sys
import tempfile
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

os.environ["PDF_TO_CLEAN_TEXT_CACHE"] = tempfile.mkdtemp()  # never touch the real result cache
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "pdf-to-clean-text" / "scripts"))
import make_test_pdf  # noqa: E402
import pdf_to_clean_text as m  # noqa: E402
from pdf_to_clean_text import (  # noqa: E402
    CorruptPDFError,
    EmptyPDFError,
    PasswordProtectedError,
    extract,
    find_sections,
)


def _pdf(path, draw=None, **canvas_kwargs):
    c = canvas.Canvas(str(path), pagesize=letter, **canvas_kwargs)
    if draw:
        draw(c)
    c.showPage()
    c.save()
    return path


@pytest.fixture(scope="session")
def pdf(tmp_path_factory):
    make_test_pdf.OUT = tmp_path_factory.mktemp("pdf")
    make_test_pdf.main()
    return make_test_pdf.OUT / "test.pdf"


@pytest.fixture(scope="session")
def result(pdf):
    return extract(pdf)


# --------------------------------------------------------------------------- end to end on the fixture


def test_watermark_stripped_but_content_kept(result):
    assert "DRAFT" not in result.text
    assert '"Margins are the story of this year." - CFO' in result.text  # one-off margin line survives
    assert "| North" in result.text  # table intact
    assert "Figure 1: Revenue by quarter" in result.text


def test_boilerplate_absent(result):
    assert "ACME Corp" not in result.text and "Confidential" not in result.text


def test_figure_caption_linked(result):
    assert [(f.page, f.caption) for f in result.figures] == [(3, "Figure 1: Revenue by quarter, fiscal year")]


def test_scanned_page_warns(result):
    assert [w for w in result.warnings if "scanned" in w] == [
        "page 6: scanned page, text came from OCR and was not verified"
    ]
    assert "Alpha Ltd" in result.text  # OCR did recover text


def test_page_markers_locate_the_pages_the_warnings_name(result):
    """A warning about page 6 is only actionable if page 6 can be found in the text."""
    assert [f"<!-- page {n} -->" in result.text for n in range(1, 7)] == [True] * 6
    assert "Alpha Ltd" in result.text.split("<!-- page 6 -->")[1]
    assert "Figure 1" in result.text.split("<!-- page 3 -->")[1].split("<!-- page 4 -->")[0]


def test_text_is_not_rewritten_by_markdown_escaping(tmp_path):
    """"R&D" must stay "R&D" and "max_tokens" must stay searchable, or --find misses real names."""
    p = _pdf(tmp_path / "esc.pdf", lambda c: c.drawString(72, 700, "Set max_tokens for the R&D team, if a < b and b > c."))
    r = extract(p)
    assert "max_tokens" in r.text and "R&D" in r.text and "a < b" in r.text
    assert "&amp;" not in r.text and "\\_" not in r.text and "&lt;" not in r.text
    assert find_sections(r.text, ["max_tokens"])[1] == 1


def test_second_read_comes_from_cache_without_converting(pdf, result, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("converted again despite a cached result")

    monkeypatch.setattr(m, "_convert", boom)
    again = extract(pdf)
    assert (again.text, again.warnings, again.figures) == (result.text, result.warnings, result.figures)


# --------------------------------------------------------------------------- errors


def test_typed_errors(tmp_path, pdf):
    with pytest.raises(CorruptPDFError, match="No file"):
        extract(tmp_path / "missing.pdf")

    (tmp_path / "x.pdf").write_text("hello")
    with pytest.raises(CorruptPDFError, match="not a PDF"):
        extract(tmp_path / "x.pdf")

    data = pdf.read_bytes()
    (tmp_path / "cut.pdf").write_bytes(data[: len(data) // 3])
    with pytest.raises(CorruptPDFError, match="damaged or incomplete"):
        extract(tmp_path / "cut.pdf")

    with pytest.raises(PasswordProtectedError):
        extract(_pdf(tmp_path / "locked.pdf", encrypt="secret"))

    with pytest.raises(EmptyPDFError):
        extract(_pdf(tmp_path / "blank.pdf"))


def test_missing_dependency_is_reported_not_raised_as_traceback(pdf, monkeypatch):
    """A fresh machine without the deps should get an instruction, not a ModuleNotFoundError."""
    monkeypatch.setattr(m, "pdfium", None)
    with pytest.raises(m.DependencyError, match="pip install pypdfium2"):
        extract(pdf)


class _FakeConverter:
    """Stands in for docling's converter: fails with `error` for the first `fail_times` calls."""

    def __init__(self, error, fail_times):
        self.error, self.fail_times, self.calls, self.offline_seen = error, fail_times, 0, []

    def convert(self, path, page_range=None):
        from huggingface_hub import constants

        self.calls += 1
        self.offline_seen.append(constants.HF_HUB_OFFLINE)
        if self.calls <= self.fail_times:
            raise self.error
        return type("R", (), {"document": "DOC"})()


def _net_error():
    import httpx

    return httpx.RemoteProtocolError("Server disconnected without sending a response.")


def test_a_network_error_is_retried_once_from_the_local_model_cache(monkeypatch, tmp_path):
    from huggingface_hub import constants

    fake = _FakeConverter(_net_error(), fail_times=1)
    monkeypatch.setattr(m, "_converter", lambda ocr: fake)
    assert m._convert(tmp_path / "x.pdf", ocr=False) == "DOC"
    assert fake.offline_seen == [False, True]  # online first, then offline for the retry
    assert constants.HF_HUB_OFFLINE is False  # and the switch is put back


def test_a_network_error_that_persists_is_reported_as_a_network_problem_not_a_bad_pdf(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "_converter", lambda ocr: _FakeConverter(_net_error(), fail_times=9))
    with pytest.raises(m.DependencyError, match="Hugging Face.*connection"):
        m._convert(tmp_path / "x.pdf", ocr=False)


def test_a_non_network_failure_is_not_retried_and_stays_a_conversion_error(monkeypatch, tmp_path):
    fake = _FakeConverter(ValueError("boom"), fail_times=9)
    monkeypatch.setattr(m, "_converter", lambda ocr: fake)
    with pytest.raises(CorruptPDFError, match="could not be converted"):
        m._convert(tmp_path / "x.pdf", ocr=False)
    assert fake.calls == 1


# --------------------------------------------------------------------------- search

DOC = """<!-- page 1 -->

## Alpha

first alpha text

## Beta

beta text starts here
<!-- page 2 -->

and the beta text runs onto the next page

## Gamma

gamma text"""


def test_find_returns_the_whole_section_even_across_a_page_break():
    shown, total = find_sections(DOC, ["Beta"])
    assert total == 1
    assert "beta text starts here" in shown[0] and "runs onto the next page" in shown[0]
    assert "Alpha" not in shown[0] and "Gamma" not in shown[0]
    assert shown[0].startswith("<!-- match: starts on page 1 -->")


def test_find_is_case_insensitive_takes_several_terms_and_reports_no_match():
    assert find_sections(DOC, ["GAMMA TEXT"])[1] == 1
    assert find_sections(DOC, ["alpha", "gamma"])[1] == 2
    assert find_sections(DOC, ["nothing here"]) == ([], 0)


def test_find_caps_the_output_and_says_how_many_really_matched():
    big = "\n\n".join(f"## S{i}\n\nthe word" for i in range(m.MAX_MATCHES + 5))
    shown, total = find_sections(big, ["the"])
    assert (len(shown), total) == (m.MAX_MATCHES, m.MAX_MATCHES + 5)


def test_find_falls_back_to_pages_when_there_are_no_headings():
    shown, _ = find_sections("<!-- page 1 -->\n\nnothing\n\n<!-- page 2 -->\n\nneedle here", ["needle"])
    assert len(shown) == 1 and "nothing" not in shown[0] and "page 2" in shown[0]


def test_find_ignores_hyphens_because_docling_joins_words_split_across_lines():
    joined = "## A\n\na largescale dataset"  # what docling produces for "large-\nscale"
    assert find_sections(joined, ["large-scale"])[1] == 1
    assert find_sections("## A\n\na large-scale dataset", ["largescale"])[1] == 1


def test_find_on_the_real_fixture_returns_the_ocrd_page_not_the_whole_document(result):
    shown, total = find_sections(result.text, ["Alpha Ltd"])
    assert total == 1 and "Alpha Ltd" in shown[0] and len(shown[0]) < len(result.text) / 3


# --------------------------------------------------------------------------- tidy, outline, pages, extract path


def test_tidy_drops_blank_lines_and_doubled_spaces_but_keeps_indentation_and_code():
    md = "Para  one  here.\n\n\n  - indented  item\n\n```\nx  =  1\n\ny = 2\n```\n| a   | b |"
    assert m._tidy(md) == "Para one here.\n  - indented item\n```\nx  =  1\n\ny = 2\n```\n| a | b |"


def test_the_real_fixture_has_no_blank_lines(result):
    assert "\n\n" not in result.text


PAGED = "<!-- page 1 -->\n## Intro\nhello\n<!-- page 2 -->\ntext\n## Pricing\nprices\n<!-- page 3 -->\nend"


def test_outline_lists_each_heading_with_its_page():
    assert m.outline(PAGED) == ["p1 Intro", "p2 Pricing"]


def test_outline_falls_back_to_each_pages_first_line_without_headings():
    assert m.outline("<!-- page 1 -->\nfirst line\nmore\n<!-- page 2 -->\n<!-- page 3 -->\nlast") == [
        "p1 first line", "p3 last"]


def test_parse_pages_reads_single_pages_ranges_and_lists():
    assert m.parse_pages("3", 9) == [3]
    assert m.parse_pages("7-9, 1,4 ,8", 9) == [1, 4, 7, 8, 9]
    for bad in ("0", "10", "5-3", "a", "2-", "3-x"):
        with pytest.raises(ValueError):
            m.parse_pages(bad, 9)


def test_select_pages_keeps_the_page_markers():
    assert m.select_pages(PAGED, "2-3") == "<!-- page 2 -->\ntext\n## Pricing\nprices\n<!-- page 3 -->\nend"


def test_cli_outline_and_pages(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(m, "extract", lambda path, use_cache=True: m.Result(PAGED))
    assert m.main([str(tmp_path / "x.pdf"), "--outline"]) == 0
    assert capsys.readouterr().out == "p1 Intro\np2 Pricing\n"
    assert m.main([str(tmp_path / "x.pdf"), "--pages", "3"]) == 0
    assert capsys.readouterr().out == "<!-- page 3 -->\nend\n"
    assert m.main([str(tmp_path / "x.pdf"), "--pages", "4"]) == 2
    assert "which has pages 1-3" in capsys.readouterr().err


def test_view_flags_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit) as e:
        m.main([str(tmp_path / "x.pdf"), "--outline", "--pages", "1"])
    assert e.value.code == 2


# --------------------------------------------------------------------------- pages, cache, cli


def test_scanned_pages_are_ocrd_in_consecutive_runs():
    assert m._runs({7, 1, 2, 3, 10, 11}) == [(1, 3), (7, 7), (10, 11)]
    assert m._runs(set()) == []


class _FakeDoc:
    def __init__(self, chunks):
        self.chunks, self.calls = chunks, []

    def export_to_markdown(self, page_break_placeholder=None, page_no=None, **kw):
        self.calls.append(page_no)
        if page_no is not None:
            return f"page {page_no}"
        return page_break_placeholder.join(self.chunks)


def test_pages_are_exported_in_one_pass_when_the_page_count_matches():
    doc = _FakeDoc(["a", "b", "c"])
    assert m._page_markdown(doc, 1, 3) == {1: "a", 2: "b", 3: "c"}
    assert doc.calls == [None]  # one export, not one per page


def test_pages_fall_back_to_exact_per_page_export_when_a_page_has_no_content():
    doc = _FakeDoc(["a", "c"])  # a blank middle page produced no chunk
    assert m._page_markdown(doc, 1, 3) == {1: "page 1", 2: "page 2", 3: "page 3"}


def test_cache_round_trips_and_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_TO_CLEAN_TEXT_CACHE", str(tmp_path / "c"))
    r = m.Result("text", ["w"], [m.Figure(3, "cap")])
    m._cache_save("a" * 64, r)
    assert m._cache_load("a" * 64) == r
    assert m._cache_load("b" * 64) is None
    if os.name != "nt":
        assert (tmp_path / "c").stat().st_mode & 0o777 == 0o700
        assert m._cache_file("a" * 64).stat().st_mode & 0o777 == 0o600


def test_cache_prunes_the_least_recently_used_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_TO_CLEAN_TEXT_CACHE", str(tmp_path / "c"))
    for i in range(5):
        m._cache_save(str(i) * 64, m.Result("t"))
        os.utime(m._cache_file(str(i) * 64), (1000 + i, 1000 + i))  # entry i was last used i seconds after 0
    monkeypatch.setattr(m, "MAX_CACHE_ENTRIES", 3)
    m._cache_save("9" * 64, m.Result("t"))  # the newest of all; triggers the prune
    assert sorted(p.name[0] for p in (tmp_path / "c").glob("*.json")) == ["3", "4", "9"]


def test_cache_key_changes_with_the_docling_version(monkeypatch):
    before = m._cache_file("d" * 64)
    monkeypatch.setattr(m.metadata, "version", lambda name: "0.0.1")
    assert m._cache_file("d" * 64) != before


def test_cache_key_changes_when_the_script_itself_changes(monkeypatch):
    """No hand-maintained CACHE_VERSION to forget bumping: the script's own source is part of the key."""
    before = m._cache_file("d" * 64)
    monkeypatch.setattr(m, "_script_digest", lambda: "different")
    assert m._cache_file("d" * 64) != before


def test_no_cache_flag_reaches_extract(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(m, "extract", lambda path, use_cache=True: seen.append(use_cache) or m.Result("t"))
    assert m.main([str(tmp_path / "x.pdf")]) == 0
    assert m.main([str(tmp_path / "x.pdf"), "--no-cache"]) == 0
    assert seen == [True, False]


def test_a_closed_pipe_is_not_an_error(monkeypatch, tmp_path):
    class Closed:
        def write(self, _):
            raise BrokenPipeError

        def flush(self):
            raise BrokenPipeError

    monkeypatch.setattr(m, "extract", lambda path, use_cache=True: m.Result("text"))
    monkeypatch.setattr(sys, "stdout", Closed())
    assert m.main([str(tmp_path / "x.pdf")]) == 0  # for example: pdf_to_clean_text.py f.pdf | head


def test_quietening_covers_every_docling_module_without_touching_the_callers_logging():
    before = logging.getLogger("unrelated").level
    m._quieten()
    assert logging.getLogger("docling.datamodel.anything").getEffectiveLevel() == logging.CRITICAL
    assert logging.getLogger("unrelated").level == before


# --------------------------------------------------------------------------- caption fallback


class _Box:
    def __init__(self, l, r, t, b):
        self.l, self.r, self.t, self.b = l, r, t, b


class _Item:
    def __init__(self, text, page, box):
        self.text, self.prov = text, [type("P", (), {"page_no": page, "bbox": box})()]


class _CaptionDoc:
    def __init__(self, *texts):
        self.texts = list(texts)


PICTURE = _Item("", 3, _Box(l=107, r=423, t=516, b=352))  # the geometry docling gave the fixture's chart


def test_a_figure_caption_docling_did_not_link_is_found_next_to_the_picture():
    below = _Item("Figure 1: Revenue by quarter", 3, _Box(l=100, r=281, t=339, b=330))  # 13 pt under it
    assert m._nearby_caption(_CaptionDoc(below), PICTURE) == "Figure 1: Revenue by quarter"


def test_a_nearby_caption_is_ignored_when_it_is_far_away_on_another_page_or_not_a_figure_line():
    far = _Item("Figure 2: Elsewhere", 3, _Box(l=100, r=281, t=200, b=190))
    other_page = _Item("Figure 3: Other page", 4, _Box(l=100, r=281, t=339, b=330))
    table = _Item("Table 1: Regional revenue", 3, _Box(l=100, r=281, t=339, b=330))
    prose = _Item("Figures show the trend was up", 3, _Box(l=100, r=281, t=339, b=330))
    beside = _Item("Figure 4: To the side", 3, _Box(l=500, r=590, t=339, b=330))  # no horizontal overlap
    assert m._nearby_caption(_CaptionDoc(far, other_page, table, prose, beside), PICTURE) == ""


def test_the_closest_of_two_candidate_captions_wins():
    near = _Item("Figure 1: Near", 3, _Box(l=100, r=281, t=339, b=330))
    farther = _Item("Figure 2: Farther", 3, _Box(l=100, r=281, t=320, b=311))
    assert m._nearby_caption(_CaptionDoc(farther, near), PICTURE) == "Figure 1: Near"


def test_a_caption_beside_the_picture_is_found_too():
    """Two-column layouts sometimes put the caption to the side rather than above or below."""
    beside = _Item("Figure 1: Beside", 3, _Box(l=440, r=550, t=480, b=400))  # vertical overlap with PICTURE,
    assert m._nearby_caption(_CaptionDoc(beside), PICTURE) == "Figure 1: Beside"  # 17pt gap to its right

    too_far = _Item("Figure 2: Too far", 3, _Box(l=500, r=600, t=480, b=400))  # same row, gap > CAPTION_MAX_GAP
    assert m._nearby_caption(_CaptionDoc(too_far), PICTURE) == ""


def test_the_fallback_finds_the_real_fixtures_caption_and_agrees_with_docling_where_docling_linked_it(pdf):
    """docling links the caption on macOS and not on Linux; the fallback must find it on both."""
    doc = m._convert(pdf, ocr=False)
    chart = next(p for p in doc.pictures if p.prov[0].page_no == 3)
    found = m._nearby_caption(doc, chart)
    assert found == "Figure 1: Revenue by quarter, fiscal year"
    linked = chart.caption_text(doc)
    assert linked in ("", found)  # empty where docling didn't link it; the same text where it did


# --------------------------------------------------------------------------- warm-up


def test_the_warmup_pdf_is_a_valid_one_page_pdf(tmp_path):
    (tmp_path / "w.pdf").write_bytes(m._warmup_pdf_bytes())
    doc = m.pdfium.PdfDocument(tmp_path / "w.pdf")
    assert len(doc) == 1 and "warm-up" in doc[0].get_textpage().get_text_range()


def test_warmup_converts_a_real_pdf_and_reports_ready(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(m, "_convert", lambda path, ocr, page_range=None: seen.append((Path(path).read_bytes()[:5], ocr)))
    assert m.main(["--warmup"]) == 0
    assert seen == [(b"%PDF-", False), (b"%PDF-", True)]  # both the layout/table models and the OCR path
    assert "models are downloaded and ready" in capsys.readouterr().err


def test_warmup_reports_a_network_failure_instead_of_a_traceback(monkeypatch, capsys):
    def fail(*a, **k):
        raise m.DependencyError("docling could not reach Hugging Face. Check your connection and try again.")

    monkeypatch.setattr(m, "_convert", fail)
    assert m.main(["--warmup"]) == 1
    assert "error: docling could not reach Hugging Face" in capsys.readouterr().err


def test_running_with_no_pdf_and_no_warmup_is_a_usage_error():
    with pytest.raises(SystemExit) as e:
        m.main([])
    assert e.value.code == 2
