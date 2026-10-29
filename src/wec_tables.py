"""Table detection and linearisation for the WEC Sporting Regulations PDF.

Tables are drawn with vector rules, so pdfplumber's line strategy recovers the
cell geometry exactly. Merged cells are resolved geometrically: every slot of
the leaf grid takes the text of the cell that covers it, so column spans in
headers and row spans in data are filled explicitly instead of being lost.
"""

import re

EN_X = 235.0          # English column starts here
MAX_CELL_CHARS = 500  # larger "cells" are layout frames, not tables
ORDINAL = re.compile(r"^(\d+(st|nd|rd|th)\b.*|All times)$", re.I)


def _cluster(values, tol=1.5):
    out = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _cell_text(page, bbox):
    words = page.crop(bbox).extract_words(keep_blank_chars=True, use_text_flow=True,
                                          extra_attrs=["fontname", "size"])
    lines, fonts = [], []
    for w in words:
        if lines and abs(w["top"] - lines[-1][0]) < 2:
            lines[-1][1].append(w["text"])
        else:
            lines.append([w["top"], [w["text"]]])
        fonts.append(w["fontname"])
    text_lines = [" ".join(ws).strip() for _, ws in lines]
    return [t for t in text_lines if t], fonts


def _is_heading_font(fonts):
    return bool(fonts) and all(("Heavy" in f or "Bold" in f) for f in fonts)


def dehyphen_cell(lines, vocab):
    """Join wrapped lines of one cell, removing typographic hyphenation."""
    out = ""
    for ln in lines:
        if out.endswith("-") and len(out) > 1 and out[-2].isalpha() and ln[:1].isalpha():
            left = re.search(r"(\w+)-$", out).group(1)
            right = re.match(r"\w+", ln).group(0)
            if (left + right).lower() in vocab:
                out = out[:-1] + ln
            else:
                out = out + ln
        else:
            out = f"{out} {ln}".strip()
    return out


def find_tables(plumber_page, page_no):
    """Return the tables of the English column (or full-width English tables)."""
    found = []
    for t in plumber_page.find_tables({"vertical_strategy": "lines",
                                       "horizontal_strategy": "lines"}):
        x0, top, x1, bottom = t.bbox
        english = x0 >= EN_X - 8
        full_width = x0 < 200 and x1 > 300
        if not (english or full_width):
            continue  # French column
        texts = [c for row in t.extract() for c in row if c]
        if not texts or max(len(c) for c in texts) > MAX_CELL_CHARS:
            continue  # page frame / layout box, not a data table
        if len(t.cells) < 4:
            continue
        found.append(t)
    return found


def build_grid(plumber_page, table, vocab):
    xs = _cluster([c[0] for c in table.cells] + [c[2] for c in table.cells])
    ys = _cluster([c[1] for c in table.cells] + [c[3] for c in table.cells])
    cells = []
    for c in table.cells:
        lines, fonts = _cell_text(plumber_page, c)
        cells.append({"bbox": c, "lines": lines, "heading": _is_heading_font(fonts)})

    def covering(cx, cy):
        for cell in cells:
            x0, t, x1, b = cell["bbox"]
            if x0 - 0.5 <= cx <= x1 + 0.5 and t - 0.5 <= cy <= b + 0.5:
                return cell
        return None

    grid = []
    for r in range(len(ys) - 1):
        row = []
        for c in range(len(xs) - 1):
            cell = covering((xs[c] + xs[c + 1]) / 2, (ys[r] + ys[r + 1]) / 2)
            row.append(cell)
        grid.append(row)
    # drop degenerate columns/rows (no cell covers them)
    grid = [row for row in grid if any(row)]
    keep = [c for c in range(len(grid[0])) if any(row[c] for row in grid)]
    grid = [[row[c] for c in keep] for row in grid]
    return grid


def linearise(plumber_page, table, vocab):
    """Return (markdown, sentences, n_rows) for a table."""
    grid = build_grid(plumber_page, table, vocab)
    ncol = len(grid[0])

    def txt(cell):
        return dehyphen_cell(cell["lines"], vocab) if cell else ""

    # header rows: leading rows that are set in Heavy/Bold, or whose first slot is
    # empty (top-left blank corner), or whose first slot continues a header cell
    n_head, head_cells = 0, set()
    for row in grid:
        filled = [c for c in row if c and c["lines"]]
        first = row[0]
        corner = first is None or not first["lines"] or id(first) in head_cells
        bold = filled and all(c["heading"] for c in filled) and len({id(c) for c in row}) > 1
        if filled and (bold or corner) and n_head < len(grid) - 1:
            n_head += 1
            head_cells |= {id(c) for c in row if c}
        else:
            break
    headers = []
    for c in range(ncol):
        parts = []
        for r in range(n_head):
            t = txt(grid[r][c])
            if t and (not parts or parts[-1] != t):
                parts.append(t)
        headers.append(" / ".join(parts))

    md_rows, records, group = [], [], None
    for row in grid[n_head:]:
        ids = {id(c) for c in row if c}
        if len(ids) == 1 and ncol > 1:  # one cell spans the whole row
            label = txt(row[0])
            group = label
            md_rows.append([f"**{label}**"] + [""] * (ncol - 1))
            continue
        records.append((group, row))
        md_rows.append([txt(c) for c in row])

    # merge consecutive rows that share every cell but one (row-spanning label)
    merged = []
    for group, row in records:
        if merged and merged[-1][0] == group:
            prev = merged[-1][1]
            diff = [c for c in range(ncol) if prev[c] is not row[c] and
                    not (isinstance(prev[c], list) and row[c] in prev[c])]
            if len(diff) == 1:
                c = diff[0]
                prev[c] = (prev[c] if isinstance(prev[c], list) else [prev[c]]) + [row[c]]
                continue
        merged.append((group, list(row)))

    def val(cell):
        if isinstance(cell, list):
            return " AND ".join(txt(x) for x in cell)
        return txt(cell)

    def lines_of(cell):
        return cell["lines"] if cell and not isinstance(cell, list) else []

    sentences = []
    if all(not val(c) for _, row in merged for c in row):
        sentences.append("- Columns (blank template): " + ", ".join(h for h in headers if h))
        merged = []
    for group, row in merged:
        parts, c, label = [], 0, None
        if not headers[0] and val(row[0]):
            label, c = val(row[0]), 1
        while c < ncol:
            h = headers[c] or f"column {c + 1}"
            lines = lines_of(row[c])
            nxt = row[c + 1] if c + 1 < ncol else None
            if (lines and nxt is not None and nxt is not row[c] and all(ORDINAL.match(l) for l in lines)
                    and (len(lines_of(nxt)) == len(lines) or len(lines) == 1)):
                common = h.split(" / ")[0]
                if len(lines) == 1:
                    pairs = f"{lines[0]} → {val(nxt)}"
                else:
                    pairs = "; ".join(f"{a} → {b}" for a, b in zip(lines, lines_of(nxt)))
                parts.append(f"{common}: {pairs}")
                c += 2
                continue
            span = 1
            while c + span < ncol and row[c + span] is row[c]:
                span += 1
            if span > 1:
                h = " + ".join(dict.fromkeys(headers[c:c + span]))
            v = val(row[c])
            parts.append(f"{h}: {v if v else '(blank)'}")
            c += span
        prefix = f"[{group}] " if group else ""
        lead = f"{label} — " if label else ""
        sentences.append(f"- {prefix}{lead}" + "; ".join(parts))

    def md_line(vals):
        return "| " + " | ".join(v.replace("|", "/") for v in vals) + " |"
    md = [md_line([h or " " for h in headers]), md_line(["---"] * ncol)]
    md += [md_line(r) for r in md_rows]
    return "\n".join(md), sentences, len(grid) - n_head
