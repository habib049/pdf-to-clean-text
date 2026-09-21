"""Build test.pdf: a 6-page document that deliberately contains every case the skill has to handle.

Pages 1-5 are native text, page 6 is image-only (a scan).
Every page: repeated header + "Confidential - Page N of 6" footer + diagonal DRAFT watermark.
Page 2: a table. Page 3: a captioned figure. Page 4: a one-off pull-quote in the top margin (must survive).

Needs reportlab, matplotlib and pypdfium2.
"""
import io
from pathlib import Path

import matplotlib
import pypdfium2 as pdfium

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent  # the tests point this at a temp directory
W, H = letter
TOTAL = 6

BODY = (
    "Revenue grew steadily across all regions during the fiscal year, driven mostly by "
    "subscription renewals and a modest increase in enterprise seats. Operating costs "
    "stayed flat, which improved margins in the second half. The board reviewed the "
    "infor-mation security roadmap and approved the proposed budget for next year."
)
VENDORS = "The scanned appendix lists the approved vendors: Alpha Ltd, Beta Inc, Gamma GmbH."


def wrap(c, text, x, y, width=440, leading=15, size=11):
    c.setFont("Helvetica", size)
    line = ""
    for word in text.split():
        if c.stringWidth(line + " " + word, "Helvetica", size) > width:
            c.drawString(x, y, line.strip())
            y -= leading
            line = word
        else:
            line += " " + word
    c.drawString(x, y, line.strip())
    return y - leading


def chrome(c, n):
    c.saveState()
    c.setFillGray(0.85)
    c.setFont("Helvetica-Bold", 90)
    c.translate(W / 2, H / 2)
    c.rotate(45)
    c.drawCentredString(0, 0, "DRAFT")
    c.restoreState()
    c.setFont("Helvetica", 9)
    c.drawString(72, H - 40, "ACME Corp Quarterly Report")
    c.drawString(72, 30, f"Confidential - Page {n} of {TOTAL}")


def chart_png():
    fig, ax = plt.subplots(figsize=(4.5, 2.4))
    ax.bar(["Q1", "Q2", "Q3", "Q4"], [12, 15, 14, 19])
    ax.set_ylabel("Revenue ($M)")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    return buf


def draw_native_pages(c):
    for n in range(1, 6):
        chrome(c, n)
        y = H - 100
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, y, f"Section {n}")
        y = wrap(c, BODY, 72, y - 25)
        y = wrap(c, BODY, 72, y - 10)
        if n == 2:
            y -= 15
            c.setFont("Helvetica-Bold", 11)
            c.drawString(72, y, "Table 1: Regional revenue ($M)")
            y -= 8
            rows = [("Region", "Q1", "Q2", "Q3"), ("North", "4.1", "4.8", "5.2"),
                    ("South", "3.0", "3.3", "3.1"), ("West", "4.9", "6.9", "5.7")]
            for i, r in enumerate(rows):
                y -= 18
                for j, cell in enumerate(r):
                    c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 10)
                    c.drawString(72 + j * 90, y, cell)
                c.line(72, y - 4, 72 + 4 * 90, y - 4)
        if n == 3:
            c.drawImage(ImageReader(chart_png()), 100, y - 190, width=330, height=175)
            c.setFont("Helvetica-Oblique", 10)
            c.drawString(100, y - 205, "Figure 1: Revenue by quarter, fiscal year")
        if n == 4:
            c.setFont("Helvetica-Oblique", 12)
            c.drawString(72, H - 62, "\"Margins are the story of this year.\" - CFO")
        c.showPage()


def scanned_page_image():
    """Render a page of text to a bitmap, the way a scanner would."""
    src = io.BytesIO()
    c = canvas.Canvas(src, pagesize=letter)
    chrome(c, 6)
    y = H - 100
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, y, "Section 6 (scanned page)")
    y = wrap(c, BODY, 72, y - 25)
    wrap(c, VENDORS, 72, y - 10)
    c.showPage()
    c.save()
    doc = pdfium.PdfDocument(src.getvalue())
    png = io.BytesIO()
    doc[0].render(scale=150 / 72).to_pil().save(png, format="PNG")
    png.seek(0)
    return ImageReader(png)


def main():
    final = OUT / "test.pdf"
    c = canvas.Canvas(str(final), pagesize=letter)
    draw_native_pages(c)
    c.drawImage(scanned_page_image(), 0, 0, width=W, height=H)  # page 6 is only a picture
    c.showPage()
    c.save()
    print(f"wrote {final}, {len(pdfium.PdfDocument(final))} pages")


if __name__ == "__main__":
    main()
