"""Extract the English (right-hand column) rules of the 2026 WEC Sporting
Regulations PDF into a structured JSON file.

The PDF is laid out in two columns: French on the left (x < COLUMN_SPLIT),
English on the right. Pages 86+ are the table of contents and are skipped.

The document has two numbering regimes:
  * main body   - "1. CHAPTER" > "1.2 Section" > "1.2.3 Article title" + text
  * appendices  - numbering restarts per appendix: "1. Section" > "1.1 text"
"""

import json
import re
import sys
from pathlib import Path

import pymupdf

COLUMN_SPLIT = 235.0  # x0 threshold: everything to the right is English
HEADER_Y = 20.0       # running header / publication line above this
FOOTER_Y = 598.0      # page number below this
LAST_BODY_PAGE = 85   # pages 86-90 are the table of contents

DOC_TITLE = "FIA World Endurance Championship Sporting Regulations 2026"

RE_APPENDIX = re.compile(r"^(APPENDIX\s+(\d+)\s*:|DRAWING\s+N)", re.I)
RE_PART = re.compile(r"^PART\s+([A-Z])\b\s*[-–:]?\s*(.*)$")
RE_CHAPTER = re.compile(r"^(\d{1,2})\s*\.\s+([A-Z][A-Z0-9\s,:’'()°\-/&]{5,})$")
RE_SECTION = re.compile(r"^(\d{1,2}\.\d{1,2})\s*\.?\s+(\S.*)$")
RE_ARTICLE = re.compile(r"^(\d{1,2}\.\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\s*\.?\s+(\S.*)$")
RE_APPX_SECTION = re.compile(r"^(\d{1,2})\s*\.?\s+([A-Za-z][^.]{3,90})$")
RE_LETTER = re.compile(r"^([a-z])\)\s+(\S[^.]{0,70})$")
RE_ORPHAN_NUMBER = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,3}\.?$")

TITLE_MAX = 140  # a heading title is never longer than this

SKIP_LINES = (
    "SPORTING REGULATIONS OF THE FIA WORLD ENDURANCE CHAMPIONSHIP",
    "RÈGLEMENT SPORTIF DU CHAMPIONNAT DU MONDE",
    "Publié le/published on",
)


def clean(text: str) -> str:
    """Collapse the PDF's tab/newline soup into a single normalised string."""
    text = text.replace("­", "").replace("​", "")
    text = text.replace("\t", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def paragraphs(block_text: str):
    """Split a text block into logical paragraphs.

    The layout marks each new paragraph/bullet with a leading tab, which
    pymupdf renders as a tab followed by a newline at the paragraph start.
    """
    parts = [p for p in (clean(p) for p in re.split(r"\t\s*\n", block_text)) if p]
    # A heading number is often split from its title ("3.1.5" / "Driver's licence").
    merged = []
    for part in parts:
        if merged and RE_ORPHAN_NUMBER.match(merged[-1]):
            merged[-1] = f"{merged[-1].rstrip('.')} {part}"
        else:
            merged.append(part)
    return merged


def looks_like_title(text: str) -> bool:
    return len(text) <= TITLE_MAX and not text.endswith((".", ",", ";", ":"))


def classify(par: str, in_appendix: bool):
    """Return (kind, number, title, body) for a paragraph, or None for body text."""
    m = RE_APPENDIX.match(par)
    if m:
        return ("appendix", m.group(2), par, "")
    m = RE_PART.match(par)
    if m and len(par) <= TITLE_MAX:
        return ("part", m.group(1), par, "")

    if in_appendix:
        m = RE_SECTION.match(par)
        if m:
            rest = m.group(2).strip()
            if looks_like_title(rest):
                return ("article", m.group(1), rest, "")
            return ("article", m.group(1), "", rest)
        m = RE_APPX_SECTION.match(par)
        if m:
            return ("section", m.group(1), m.group(2).strip(), "")
        return None

    m = RE_ARTICLE.match(par)
    if m and looks_like_title(m.group(2)):
        return ("article", m.group(1), m.group(2).strip(), "")
    m = RE_SECTION.match(par)
    if m and looks_like_title(m.group(2)):
        return ("section", m.group(1), m.group(2).strip(), "")
    m = RE_CHAPTER.match(par)
    if m and par == par.upper():
        return ("chapter", m.group(1), m.group(2).strip(), "")
    return None


def english_paragraphs(doc):
    """Yield (page_number, paragraph) for the English column, in reading order."""
    for page_index in range(min(LAST_BODY_PAGE, doc.page_count)):
        page = doc[page_index]
        blocks = [
            b for b in page.get_text("blocks")
            if b[0] >= COLUMN_SPLIT and HEADER_Y < b[1] < FOOTER_Y
        ]
        blocks.sort(key=lambda b: (round(b[1]), b[0]))
        for block in blocks:
            if any(s in block[4] for s in SKIP_LINES):
                continue
            for par in paragraphs(block[4]):
                if par.isdigit():  # stray table/page artefacts
                    continue
                yield page_index + 1, par


def extract(pdf_path: Path):
    doc = pymupdf.open(pdf_path)
    rules = []
    chapter = section = part = appendix = None
    current = None
    subheading = None

    def flush():
        nonlocal current
        if current and current["text"]:
            rules.append(current)
        current = None

    def start(number, title, page, text=""):
        prefix = f"{appendix}-" if appendix else ""
        return {
            "id": f"{prefix}{number}" if number else f"{prefix}{title}",
            "article": number,
            "title": title,
            "chapter": chapter,
            "section": section,
            "part": part,
            "appendix": appendix,
            "pages": [page],
            "text": text,
        }

    pending_title = False
    for page, par in english_paragraphs(doc):
        head = classify(par, in_appendix=appendix is not None)
        if pending_title:
            pending_title = False
            if not head and par == par.upper() and len(par) <= 50:
                chapter = f"{chapter} {par}".strip()  # title wrapped onto a 2nd line
                continue
        if head:
            kind, number, title, body = head
            flush()
            subheading = None
            if kind == "appendix":
                appendix = f"APPENDIX {number}" if number else "DRAWING"
                chapter = title
                section = part = None
                pending_title = True
            elif kind == "part":
                part = title
                section = None
            elif kind == "chapter":
                chapter = f"{number}. {title}"
                section = None
            elif kind == "section":
                section = f"{number}. {title}" if appendix else f"{number} {title}"
            else:  # article
                current = start(number, title, page, body)
            continue

        m = RE_LETTER.match(par)
        if m and current:
            subheading = m.group(2).strip()
            continue

        if current is None:
            # Body text under a section (or chapter) with no numbered article.
            if not (section or chapter):
                continue
            number = section.split(" ")[0].rstrip(".") if section else None
            title = section or chapter
            if rules and rules[-1]["title"] == title and rules[-1]["article"] == number:
                current = rules.pop()
            else:
                current = start(number, "", page)
                current["id"] = (f"{appendix}-{number}" if appendix and number
                                 else number or f"{appendix or 'DOC'}-untitled")
                current["title"] = ""

        chunk = f"{subheading}: {par}" if subheading else par
        subheading = None
        current["text"] = f"{current['text']} {chunk}".strip() if current["text"] else chunk
        if page not in current["pages"]:
            current["pages"].append(page)

    flush()

    seen = {}
    for rule in rules:  # ids must be unique for downstream indexing
        base = rule["id"]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            rule["id"] = f"{base}#{seen[base]}"

    return {
        "source": pdf_path.name,
        "document": DOC_TITLE,
        "language": "en",
        "published": "2025-10-16",
        "applicable_from": "2026-01-01",
        "rule_count": len(rules),
        "rules": rules,
    }


def main():
    pdf = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/pdf/2026_WEC.pdf")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "output/2026_WEC_rules_en.json")
    data = extract(pdf)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{data['rule_count']} rules -> {out}")


if __name__ == "__main__":
    main()
