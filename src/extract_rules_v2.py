"""Extract the English column of the 2026 WEC Sporting Regulations into
structured, RAG-ready JSON.

The v1 extractor classified headings with regular expressions on flattened text,
which lost tables, merged or dropped articles and mis-read list items as
headings. This version reads the layout instead:

* headings come from the typeface: Bold = chapter / appendix title,
  Heavy = section, Medium = article; appendix articles are the numbers set in
  the left number column (x < 250), body text is indented (x ~ 262);
* tables are rebuilt from their vector rules with pdfplumber and written out as
  one explicit sentence per row (plus a Markdown copy for display);
* figures are replaced by a placeholder and, when provided, a manual
  description from figures.json;
* line-end hyphenation is resolved against the document's own vocabulary.

Usage: python extract_rules_v2.py 2026_WEC.pdf output/2026_WEC_rules_en.v2.json [figures.json]
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber
import pymupdf

import wec_tables

EN_X = 235.0
NUM_COL_MAX_X = 250.0   # article numbers sit at x ~ 239.5, body text at ~ 262
HEADER_Y = 20.0
FOOTER_Y = 598.0
LAST_BODY_PAGE = 85     # pages 86-90: table of contents
PARA_GAP = 4.0          # vertical gap (pt) that starts a new paragraph
SHORT_LINE_X = 395.0    # a line ending left of this is a deliberate line break (column ends ~440)
MIN_FIGURE_AREA = 2000

DOC_TITLE = "FIA World Endurance Championship Sporting Regulations 2026"
SKIP = ("SPORTING REGULATIONS OF THE FIA WORLD ENDURANCE CHAMPIONSHIP",
        "Publié le/published on")

BOLD, HEAVY, MEDIUM = "FuturaStd-Bold", "FuturaStd-Heavy", "FuturaStd-Medium"
BULLETS = {"o": 1, "-": 0, "•": 0, "--": 0, "–": 0}

RE_NUM = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,3})\.?\s*(.*)$")
RE_CHAPTER = re.compile(r"^(\d{1,2})\s*\.\s*(.+)$")
RE_APPX_SECTION = re.compile(r"^(\d{1,2})\s*\.?\s*(.*)$")
RE_APPENDIX = re.compile(r"^APPENDIX\s+(\d+)\s*:?\s*(.*)$", re.I)
RE_PART = re.compile(r"^PART\s+([A-Z])\b\s*[-–:]?\s*(.*)$")
RE_LETTER = re.compile(r"^(?:[a-z]|\d)\)\s")
RE_REF = re.compile(r"\bArticles?\s+(\d{1,2}(?:\.\d{1,2}){0,3})(?![.\d]*\d)"
                    r"((?:\s*(?:,|and|&|or)\s*\d{1,2}(?:\.\d{1,2}){0,3}(?!\d))*)"
                    r"(\s+of\s+(?:the\s+)?(?:present\s+|this\s+)?(?:Appendix\s+[A-Z]\b(?:\s+(?:to|of)\s+the\s+Code)?|"
                    r"Appendix\s*\d+|Appendix\b|International Sporting Code|Code|Technical Regulations?|TR\b))?")
RE_APPX_REF = re.compile(r"\bAppendix\s+(\d{1,2})\b")


# --------------------------------------------------------------------------- layout

def visual_lines(page, page_no, exclude_boxes):
    """English-column lines of a page, with spans on the same baseline merged."""
    raw = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            x0, y0, x1, y1 = line["bbox"]
            if x0 < EN_X or not (HEADER_Y < y0 < FOOTER_Y):
                continue
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if any(b[0] - 2 <= cx <= b[2] + 2 and b[1] - 2 <= cy <= b[3] + 2 for b in exclude_boxes):
                continue
            raw.append({"x0": x0, "y0": y0, "y1": y1, "x1": x1,
                        "spans": [(s["font"], s["text"], s["bbox"][0]) for s in spans],
                        "units": [("".join(s["text"] for s in spans), x0, min(s["size"] for s in spans))]})
    raw.sort(key=lambda l: (round(l["y0"], 0), l["x0"]))
    merged = []
    for l in raw:
        if merged and abs(l["y0"] - merged[-1]["y0"]) < 1.5:
            m = merged[-1]
            m["spans"] += l["spans"]
            m["spans"].sort(key=lambda s: s[2])
            m["units"] = sorted(m["units"] + l["units"], key=lambda u: u[1])
            m["x0"] = min(m["x0"], l["x0"])
            m["y1"] = max(m["y1"], l["y1"])
            m["x1"] = max(m["x1"], l["x1"])
        else:
            merged.append(dict(l))
    out = []
    for m in merged:
        # spans of one PDF line are concatenated as they are (a font change can fall
        # inside a word); separate PDF lines on the same baseline are joined with a
        # space, except superscripts ("13" + "th")
        text = ""
        for unit, _, size in m["units"]:
            glue = "" if (size < 5 and text[-1:].isdigit()) or not text else " "
            text += glue + unit
        text = re.sub(r"\s+", " ", text.replace("\t", " ")).strip()
        text = text.replace("­", "").replace("​", "")
        if any(k in text for k in SKIP):
            continue
        first_font = m["spans"][0][0]
        first_raw = m["spans"][0][1]
        first_txt = first_raw.strip()
        lead = re.match(r"^(o|•|-|--|–)\t", first_raw)
        out.append({"kind": "line", "page": page_no, "x0": m["x0"], "x1": m["x1"], "y0": m["y0"], "y1": m["y1"],
                    "text": text, "font": first_font,
                    "fonts": {s[0] for s in m["spans"]},
                    "marker": lead.group(1) if lead else
                              (first_txt if (first_txt in BULLETS and len(m["spans"]) > 1) else None)})
    return out


def page_items(doc, plumber, page_no, vocab):
    page = doc[page_no - 1]
    ppage = plumber.pages[page_no - 1]
    items, boxes = [], []
    for t in wec_tables.find_tables(ppage, page_no):
        md, sentences, nrows = wec_tables.linearise(ppage, t, vocab)
        boxes.append(t.bbox)
        items.append({"kind": "table", "page": page_no, "x0": t.bbox[0], "y0": t.bbox[1], "y1": t.bbox[3],
                      "markdown": md, "sentences": sentences})
    for im in page.get_image_info():
        x0, y0, x1, y1 = im["bbox"]
        if (x1 - x0) * (y1 - y0) < MIN_FIGURE_AREA or x1 < EN_X + 20:
            continue  # small or French-column-only image
        boxes.append((x0, y0, x1, y1))
        items.append({"kind": "figure", "page": page_no, "x0": x0, "y0": y0, "y1": y1})
    items += visual_lines(page, page_no, boxes)
    items.sort(key=lambda i: (i["y0"], i["x0"]))
    return items


def build_vocab(doc):
    words = Counter()
    for i in range(LAST_BODY_PAGE):
        text = doc[i].get_text(clip=pymupdf.Rect(EN_X, HEADER_Y, doc[i].rect.width, FOOTER_Y))
        for w in re.findall(r"[A-Za-z]{3,}", text):
            words[w.lower()] += 1
    return set(words)


def join_text(left, right, vocab):
    """Append a wrapped line, resolving a line-end hyphen against the vocabulary."""
    if not left:
        return right
    m = re.search(r"([A-Za-z]+)-$", left)
    if m and right[:1].isalpha():
        word = re.match(r"[A-Za-z]+", right).group(0)
        if (m.group(1) + word).lower() in vocab and f"{m.group(1)}-{word}".lower() not in vocab:
            return left[:-1] + right          # typographic hyphen: "Hyper-" + "pole"
        return left + right                   # real compound: "wet-" + "weather"
    return f"{left} {right}"


# --------------------------------------------------------------------------- structure

class Builder:
    def __init__(self, vocab, figures):
        self.vocab = vocab
        self.figures = figures
        self.rules = []
        self.appendix = self.appendix_title = None
        self.chapter = self.part = self.section = None
        self.current = None
        self.prev = None           # previous line item
        self.heading = None        # heading item still open for continuation lines
        self.list_parent = False   # last paragraph was a top-level bullet
        self.figure_ids, self.figure_records = set(), []

    # -- records
    def flush(self):
        if self.current and (self.current["paragraphs"] or self.current["title"]):
            self.rules.append(self.current)
        self.current = None

    def start(self, number, title, page, kind):
        self.flush()
        prefix = f"{self.appendix}-" if self.appendix else ""
        rid = f"{prefix}{number}" if number else (self.appendix or "DOC")
        self.current = {"id": rid, "article": number, "title": title, "level": kind,
                        "appendix": self.appendix, "appendix_title": self.appendix_title,
                        "chapter": self.chapter, "part": self.part, "section": self.section,
                        "pages": [page], "paragraphs": [], "tables": [], "figures": [],
                        "flags": []}
        self.list_parent = False

    def ensure_current(self, page):
        if self.current is None:
            if self.section:
                num, _, title = self.section.partition(" ")
                self.start(num.rstrip("."), title, page, "section")
            elif self.part:
                m = RE_PART.match(self.part)
                self.start(f"PART {m.group(1)}", self.part, page, "part")
            elif self.appendix:
                self.start(None, self.appendix_title or "", page, "appendix")
            else:
                self.start(None, self.chapter or "", page, "chapter")
        if page not in self.current["pages"]:
            self.current["pages"].append(page)

    def add_par(self, text, page, ptype="p", level=0, new=True):
        self.ensure_current(page)
        pars = self.current["paragraphs"]
        if not new and pars and pars[-1]["type"] in ("p", "bullet", "item"):
            pars[-1]["text"] = join_text(pars[-1]["text"], text, self.vocab)
        else:
            pars.append({"type": ptype, "text": text, "level": level, "page": page})

    # -- headings
    def is_continuation(self, item, font):
        h = self.heading
        return (h is not None and font == h["font"] and item["page"] == h["page"]
                and -3 <= item["y0"] - h["y1"] < 3.5 and item["x0"] > NUM_COL_MAX_X - 15)

    def on_line(self, item):
        text, font, page = item["text"], item["font"], item["page"]
        bold = font == BOLD and all(f == BOLD for f in item["fonts"])
        heavy = font == HEAVY
        medium = font == MEDIUM and item["x0"] < NUM_COL_MAX_X

        # continuation of a multi-line heading
        if (bold or heavy or font == MEDIUM) and self.is_continuation(item, font):
            self.extend_heading(text)
            self.heading["y1"] = item["y1"]
            return

        if bold:
            m = RE_APPENDIX.match(text)
            if m:
                self.flush()
                self.appendix = f"APPENDIX {m.group(1)}"
                self.appendix_title = text
                self.chapter = self.part = self.section = None
                self.set_heading(item, "appendix")
                return
            m = RE_CHAPTER.match(text)
            if m and self.appendix is None:
                self.flush()
                self.chapter = f"{m.group(1)}. {m.group(2).strip()}"
                self.part = self.section = None
                self.set_heading(item, "chapter")
                return
        if heavy:
            if text.upper().startswith("DRAWING"):
                self.flush()
                n = re.search(r"(\d+)", text)
                self.appendix = f"DRAWING {n.group(1) if n else ''}".strip()
                self.appendix_title = text
                self.chapter = self.part = self.section = None
                self.set_heading(item, "appendix")
                return
            m = RE_PART.match(text)
            if m:
                self.flush()
                self.part = text
                self.section = None
                self.set_heading(item, "part")
                return
            m = RE_NUM.match(text)
            if m and self.appendix is None:
                self.flush()
                self.section = f"{m.group(1)} {m.group(2).strip()}"
                self.set_heading(item, "section")
                return
            if self.appendix:
                if m:  # "11.1 Session times" inside an appendix: article with a title
                    self.start(m.group(1), m.group(2).strip(), page, "article")
                    self.set_heading(item, "article")
                    return
                m = RE_APPX_SECTION.match(text)
                if m and item["x0"] < NUM_COL_MAX_X:
                    self.flush()
                    self.section = f"{m.group(1)}. {m.group(2).strip()}"
                    self.set_heading(item, "section")
                    return
            # un-numbered heavy line: a sub-heading inside the current text
            self.add_par(text, page, "subheading")
            self.prev = item
            return
        if medium:
            m = RE_NUM.match(text)
            if m:
                self.start(m.group(1), m.group(2).strip(), page, "article")
                self.set_heading(item, "article")
                return
        # appendix articles: plain-weight number in the number column
        if item["x0"] < NUM_COL_MAX_X and self.appendix:
            m = RE_NUM.match(text)
            if m and not item["marker"]:
                self.start(m.group(1), "", page, "article")
                if m.group(2).strip():
                    self.add_par(m.group(2).strip(), page)
                self.heading = None
                self.prev = item
                return
        self.on_body(item)

    def set_heading(self, item, kind):
        self.heading = {"font": item["font"], "page": item["page"], "y1": item["y1"], "kind": kind}
        self.prev = item

    def extend_heading(self, text):
        kind = self.heading["kind"]
        if kind == "appendix":
            self.appendix_title = f"{self.appendix_title} {text}"
        elif kind == "chapter":
            self.chapter = f"{self.chapter} {text}"
        elif kind == "section":
            self.section = f"{self.section} {text}"
        elif kind == "part":
            self.part = f"{self.part} {text}"
        elif kind == "article" and self.current:
            self.current["title"] = f"{self.current['title']} {text}".strip()

    # -- body text
    def on_body(self, item):
        text, page = item["text"], item["page"]
        self.heading = None
        prev = self.prev
        same_page = prev is not None and prev.get("page") == page and prev["kind"] == "line"
        gap = item["y0"] - prev["y1"] if same_page else None
        last = self.current["paragraphs"][-1] if self.current and self.current["paragraphs"] else None

        marker = item["marker"]
        if marker is None and text.startswith("- ") and item["x0"] < 270:
            marker, text = "-", text[2:]
        elif marker is None and re.match(r"^[o•] \S", text):  # bullet typed as "o " in the source
            marker, text = text[0], text[2:]
        elif marker is not None:
            text = text[len(marker):].strip()

        if marker:
            # The source sets "o" and "-" bullets at the same indent and uses them
            # inconsistently for nesting, so the marker is kept, not interpreted.
            self.add_par(text, page, "bullet", BULLETS[marker])
        elif RE_LETTER.match(text):
            self.add_par(text, page, "item")
            self.list_parent = False
        else:
            if last is None or last["type"] in ("table", "figure", "subheading"):
                new = True
            elif gap is not None:
                short_prev = prev.get("x1", 999) < SHORT_LINE_X and not prev["text"].endswith("-")
                new = (gap > PARA_GAP or short_prev
                       or (item["x0"] < NUM_COL_MAX_X and self.appendix == "APPENDIX 1"))
            else:  # first line on a new page: continue unless the sentence ended
                new = bool(re.search(r"[.:;!?]$", last["text"]))
            if new:
                self.list_parent = False
            self.add_par(text, page, "p", new=new)
        self.prev = item

    def on_table(self, item):
        self.ensure_current(item["page"])
        intro = f"[Table p.{item['page']}, one line per row:]"
        self.current["paragraphs"].append({"type": "table", "text": "\n".join([intro] + item["sentences"]),
                                           "level": 0, "page": item["page"]})
        self.current["tables"].append({"page": item["page"], "markdown": item["markdown"]})
        self.heading = None
        self.prev = item

    def on_figure(self, item):
        """A figure becomes a record of its own (so it can be retrieved by its
        description) and leaves a pointer in the text where it appears."""
        self.ensure_current(item["page"])
        fig = self.figures.get(str(item["page"]), {})
        fid = fig.get("figure_id") or f"p{item['page']}"
        if fid in self.figure_ids:
            return  # one figure drawn as several images
        self.figure_ids.add(fid)
        title = fig.get("title", f"figure on page {item['page']}")
        rid = self.appendix if self.appendix and self.appendix.startswith("DRAWING") else \
            f"{self.appendix or 'DOC'}-FIG {fid}"
        self.current["paragraphs"].append({"type": "figure", "level": 0, "page": item["page"],
                                           "text": f"[Figure p.{item['page']}: {title} – see record {rid}]"})
        desc = fig.get("description")
        record = {"id": rid, "article": None, "title": title, "level": "figure",
                  "appendix": self.appendix, "appendix_title": self.appendix_title,
                  "chapter": self.chapter, "part": self.part, "section": self.section,
                  "pages": [item["page"]], "tables": [], "flags": [],
                  "figures": [{"page": item["page"], "figure_id": fid, "verified": fig.get("verified", False)}],
                  "related_articles": fig.get("related", []),
                  "paragraphs": [{"type": "p", "level": 0, "page": item["page"], "text":
                                  (f"Figure (page {item['page']}): {title}. Content transcribed manually from the "
                                   f"graphic: {desc}") if desc else
                                  f"Figure (page {item['page']}): {title}. Graphic not available as text; "
                                  f"refer to page {item['page']} of the PDF."}]}
        if not desc:
            record["flags"].append("figure_without_description")
        self.figure_records.append(record)
        self.heading = None
        self.prev = item


# --------------------------------------------------------------------------- post-processing

def render_block(p):
    if p["type"] == "bullet":
        return ("◦ " if p["level"] else "- ") + p["text"]
    if p["type"] == "subheading":
        return p["text"] if p["text"].endswith(":") else f"{p['text']}:"
    return p["text"]


def render(rule):
    return "\n".join(render_block(p) for p in rule["paragraphs"])


def references(rule):
    refs, external = set(), set()
    text = rule["text"]
    for m in RE_REF.finditer(text):
        nums = [m.group(1)] + re.findall(r"\d{1,2}(?:\.\d{1,2}){0,3}", m.group(2) or "")
        scope = (m.group(3) or "").lower()
        for n in nums:
            if any(k in scope for k in ("code", "technical", " tr")) or re.search(r"appendix\s+[a-z]\b", scope):
                external.add(f"{n} ({m.group(3).strip()})")
            elif "appendix" in scope:
                num = re.search(r"\d+", scope)
                appx = f"APPENDIX {num.group(0)}" if num else rule["appendix"]
                refs.add(f"{appx}-{n}")
            else:
                refs.add(n)
    for m in RE_APPX_REF.finditer(text):
        refs.add(f"APPENDIX {int(m.group(1))}")
    return sorted(refs), sorted(external)


def source_anomalies(text):
    """Patterns that look like unresolved tracked changes in the published PDF."""
    found = []
    for m in re.finditer(r"\b(\d+)\s+(\d+)\s+(minute|minutes|second|seconds|hour|hours|laps?|km|kph|%)\b", text):
        found.append(m.group(0))
    for m in re.finditer(r"\b(will|may|must|shall|can|should)\s+(will|may|must|shall|can|should)\b", text):
        found.append(m.group(0))
    return found


def extract(pdf_path, figures_path=None):
    doc = pymupdf.open(pdf_path)
    plumber = pdfplumber.open(pdf_path)
    vocab = build_vocab(doc)
    figures = json.loads(Path(figures_path).read_text(encoding="utf-8")) if figures_path else {}
    b = Builder(vocab, figures)
    for page_no in range(1, LAST_BODY_PAGE + 1):
        for item in page_items(doc, plumber, page_no, vocab):
            {"line": b.on_line, "table": b.on_table, "figure": b.on_figure}[item["kind"]](item)
    b.flush()
    # figure records go right after the record that contains them
    for fig in reversed(b.figure_records):
        host = next((i for i, r in enumerate(b.rules)
                     if any(f"see record {fig['id']}]" in p["text"] for p in r["paragraphs"])), len(b.rules) - 1)
        if b.rules[host]["id"] == fig["id"]:  # DRAWING 1: the record *is* the figure
            b.rules[host].update({k: fig[k] for k in ("title", "level", "figures", "related_articles", "flags")})
            b.rules[host]["paragraphs"] = fig["paragraphs"]
        else:
            b.rules.insert(host + 1, fig)

    seen = Counter()
    for rule in b.rules:
        seen[rule["id"]] += 1
        if seen[rule["id"]] > 1:
            rule["flags"].append(f"duplicate_id_renamed_from:{rule['id']}")
            rule["id"] = f"{rule['id']}#{seen[rule['id']]}"
        rule["text"] = render(rule)
        crumbs = [rule["appendix_title"] or rule["chapter"], rule["part"], rule["section"]]
        if rule["level"] == "article":
            crumbs.append(f"{rule['article']} {rule['title']}".strip())
        rule["breadcrumb"] = " > ".join(c for c in crumbs if c)
        rule["references"], rule["external_references"] = references(rule)
        anomalies = source_anomalies(rule["text"])
        if anomalies:
            rule["flags"].append("source_ambiguity:" + " | ".join(anomalies))
        if re.search(r"\bXX\b|\bxx[:’']", rule["text"]):
            rule["flags"].append("template_placeholder")
        if rule["tables"]:
            rule["flags"].append("contains_table")
        rule.setdefault("related_articles", [])
        rule["blocks"] = [{"type": p["type"], "page": p["page"], "text": render_block(p)}
                          for p in rule.pop("paragraphs")]

    ids = {r["id"] for r in b.rules}

    def exists(ref):
        return ref in ids or any(i.startswith(ref + ".") or i.startswith(ref + "-") for i in ids)

    for rule in b.rules:  # inside an appendix, a bare "Article 1.18" may be local to it
        if rule["appendix"]:
            rule["references"] = sorted({f"{rule['appendix']}-{r}" if not exists(r) and exists(f"{rule['appendix']}-{r}")
                                         else r for r in rule["references"]})
    for rule in b.rules:
        rule["unresolved_references"] = [r for r in rule["references"] if not exists(r)]
    return {
        "source": Path(pdf_path).name,
        "document": DOC_TITLE,
        "language": "en",
        "authoritative_language": "fr",
        "published": "2025-10-16",
        "applicable_from": "2026-01-01",
        "extractor": "extract_rules_v2.py",
        "rule_count": len(b.rules),
        "rules": b.rules,
    }


def main():
    pdf = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/pdf/2026_WEC.pdf")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "output/2026_WEC_rules_en.v2.json")
    figs = sys.argv[3] if len(sys.argv) > 3 else None
    data = extract(pdf, figs)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{data['rule_count']} rules -> {out}")


if __name__ == "__main__":
    main()
