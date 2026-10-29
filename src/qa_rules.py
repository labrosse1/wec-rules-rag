"""Quality gate for the extracted WEC rules.

Checks the extraction against the PDF's own table of contents (pages 86-90),
numbering continuity, empty/short records, residual hyphenation, references,
and flags. Exits with status 1 when a blocking check fails, so it can run in CI.

Usage: python qa_rules.py 2026_WEC.pdf output/2026_WEC_rules_en.v2.json [report.md]
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pymupdf

TOC_PAGES = range(85, 90)
RE_TOC = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(.+)$")


def norm(s):
    s = s.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"-\s+", "-", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def parse_toc(doc):
    """(number, title) for every main-body entry of the English index."""
    entries, lines = [], []
    for i in TOC_PAGES:
        page = doc[i]
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                if l["bbox"][0] < 235:
                    continue
                t = "".join(s["text"] for s in l["spans"]).replace("\t", " ").strip()
                if t:
                    lines.append((i, round(l["bbox"][1]), l["bbox"][0], t))
    lines.sort()
    rows = defaultdict(list)
    for p, y, x, t in lines:
        rows[(p, y)].append((x, t))
    for key in sorted(rows):
        text = re.sub(r"\s+", " ", " ".join(t for _, t in sorted(rows[key]))).strip()
        text = re.sub(r"\s+\d{1,2}$", "", text)  # page number
        text = re.sub(r"(\))\d{1,2}$", r"\1", text)
        if text.upper().startswith(("APPENDIX", "DRAWING")):
            break  # appendices are listed without article numbers
        m = RE_TOC.match(text)
        if m:
            entries.append([m.group(1), m.group(2).strip()])
        elif entries and not text.isdigit() and text not in ("INDEX",):
            entries[-1][1] += " " + text  # wrapped title
    for e in entries:
        e[1] = re.sub(r"(\))\d{1,2}$", r"\1", e[1])
    return entries


def main():
    pdf, data_path = sys.argv[1], sys.argv[2]
    report_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    doc = pymupdf.open(pdf)
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    rules = data["rules"]
    by_id = {r["id"]: r for r in rules}
    out, blocking = [], 0

    def section(title):
        out.append(f"\n## {title}\n")

    # 1. TOC coverage -----------------------------------------------------------------
    toc = parse_toc(doc)
    main_rules = {r["article"]: r for r in rules if not r["appendix"] and r["article"]}
    section_titles = {}
    for r in rules:
        if not r["appendix"] and r["section"]:
            num, _, t = r["section"].partition(" ")
            section_titles[num.rstrip(".")] = t
    chapters = {r["chapter"].split(".")[0]: r["chapter"] for r in rules if r["chapter"] and not r["appendix"]}
    missing, title_mismatch = [], []
    for num, title in toc:
        depth = num.count(".")
        if depth == 0:
            got = chapters.get(num)
            got_title = got.split(". ", 1)[1] if got else None
        elif depth == 1:
            got_title = section_titles.get(num)
            if got_title is None and num in main_rules:
                got_title = main_rules[num]["title"]
        else:
            got_title = main_rules[num]["title"] if num in main_rules else None
        if got_title is None:
            missing.append(f"{num} {title}")
        elif norm(got_title) != norm(title):
            title_mismatch.append(f"{num}: TOC «{title}» vs extracted «{got_title}»")
    toc_nums = {n for n, _ in toc}
    extra = sorted((n for n in main_rules if n not in toc_nums), key=lambda s: [int(x) for x in s.split(".")])
    section("1. Coverage against the PDF table of contents (main body)")
    out.append(f"- TOC entries: {len(toc)}; missing in extraction: **{len(missing)}**; "
               f"title differences: {len(title_mismatch)}; articles not listed in TOC: {len(extra)}")
    for m in missing:
        out.append(f"  - MISSING: {m}")
    for m in title_mismatch:
        out.append(f"  - title: {m}")
    for m in extra:
        out.append(f"  - not in TOC: {m} {main_rules[m]['title']}")
    blocking += len(missing)

    # 2. numbering continuity ----------------------------------------------------------
    section("2. Numbering gaps (all parts, incl. appendices)")
    groups = defaultdict(list)
    for r in rules:
        if r["article"] and re.fullmatch(r"\d+(\.\d+)*", r["article"]):
            parts = r["article"].split(".")
            groups[(r["appendix"], ".".join(parts[:-1]))].append(int(parts[-1]))
    gaps = []
    for (appx, parent), nums in sorted(groups.items(), key=lambda kv: str(kv[0])):
        nums = sorted(set(nums))
        for a, b in zip(nums, nums[1:]):
            if b - a > 1:
                gaps.append(f"{appx or 'main'} {parent + '.' if parent else ''}{a} → {b}")
    out.append(f"- gaps: **{len(gaps)}**")
    out += [f"  - {g}" for g in gaps]

    # 3. record hygiene ----------------------------------------------------------------
    section("3. Record hygiene")
    empty = [r["id"] for r in rules if not r["text"].strip()]
    short = [f"{r['id']} ({len(r['text'].split())} words): {r['text'][:70]}" for r in rules
             if 0 < len(r["text"].split()) < 12]
    dup = [r["id"] for r in rules if "#" in r["id"]]
    hyph = sorted({m.group(0) for r in rules for m in re.finditer(r"\b[A-Za-z]+- [a-z]+\b", r["text"])})
    words = [len(r["text"].split()) for r in rules]
    out.append(f"- records: {len(rules)}; empty: **{len(empty)}**; duplicate ids: **{len(dup)}** {dup}")
    out.append(f"- words per record: min {min(words)}, median {sorted(words)[len(words)//2]}, max {max(words)}")
    out.append(f"- residual 'word- word' splits: {len(hyph)} {hyph}")
    out.append(f"- very short records (<12 words, keep but embed with breadcrumb): {len(short)}")
    out += [f"  - {s}" for s in short]
    blocking += len(empty) + len(dup)

    # 4. references ---------------------------------------------------------------------
    section("4. Cross-references")
    unresolved = [(r["id"], u) for r in rules for u in r["unresolved_references"]]
    out.append(f"- internal references: {sum(len(r['references']) for r in rules)}; "
               f"external (Code / Technical Regulations): {sum(len(r['external_references']) for r in rules)}; "
               f"unresolved: {len(unresolved)}")
    out += [f"  - {rid} → {u}" for rid, u in unresolved]

    # 5. flags requiring a human ---------------------------------------------------------
    section("5. Items that need a human decision")
    for flag in ("source_ambiguity", "figure_without_description", "template_placeholder", "contains_table"):
        hits = [r for r in rules if any(f.startswith(flag) for f in r["flags"])]
        out.append(f"- **{flag}**: {len(hits)}")
        for r in hits:
            detail = "; ".join(f.split(":", 1)[1] for f in r["flags"] if f.startswith(flag) and ":" in f)
            out.append(f"  - {r['id']} (p. {','.join(map(str, r['pages']))}){' – ' + detail if detail else ''}")
    unverified = [(r["id"], f["page"]) for r in rules if r["level"] == "figure" for f in r["figures"] if not f.get("verified")]
    out.append(f"- figure descriptions not yet human-verified: {len(unverified)} {unverified}")

    # 6. word coverage ----------------------------------------------------------------
    section("6. Word coverage (English column of the PDF vs extracted text)")
    import pdfplumber
    import wec_tables
    from collections import Counter
    got = Counter()
    for r in rules:
        if r["level"] == "figure":
            continue
        t = " ".join(filter(None, [r["text"], r["title"], r["article"], r["chapter"], r["section"],
                                   r["part"], r["appendix_title"]]))
        got.update(w.lower() for w in re.findall(r"[A-Za-z0-9€]+", t))
    src, where = Counter(), defaultdict(set)
    plumber = pdfplumber.open(pdf)
    for i in range(85):
        boxes = [t.bbox for t in wec_tables.find_tables(plumber.pages[i], i + 1)]
        for blk in doc[i].get_text("dict")["blocks"]:
            for l in blk.get("lines", []):
                x0, y0, x1, y1 = l["bbox"]
                if not (20 < y0 < 598):
                    continue
                inside = any(b[0] - 2 <= x0 and x1 <= b[2] + 2 and b[1] - 2 <= y0 <= b[3] + 2 for b in boxes)
                if x0 < 235 and not inside:
                    continue
                t = "".join(s["text"] for s in l["spans"])
                if "published on" in t:
                    continue
                for w in re.findall(r"[A-Za-z0-9€]+", t.replace("\u00ad", "")):
                    src[w.lower()] += 1
                    where[w.lower()].add(i + 1)
    lost = src - got
    lost.pop("o", None)  # bullet marker, rendered as "◦"
    total, n_lost = sum(src.values()), sum(lost.values())
    out.append(f"- source words: {total}; not found in output: {n_lost} ({100 * n_lost / total:.2f} %)")
    out += [f"  - «{w}» ×{c} (p. {', '.join(map(str, sorted(where[w])[:8]))})" for w, c in lost.most_common(25)]
    if n_lost / total > 0.005:
        blocking += 1
        out.append("  - **BLOCKING: more than 0.5 % of the source words are missing**")

    status = "FAIL" if blocking else "PASS"
    header = [f"# QA report – {data['source']} → {Path(data_path).name}", "",
              f"Blocking checks: **{status}** ({blocking} blocking issue(s))"]
    text = "\n".join(header + out) + "\n"
    if report_path:
        report_path.write_text(text, encoding="utf-8")
    print(text)
    sys.exit(1 if blocking else 0)


if __name__ == "__main__":
    main()
