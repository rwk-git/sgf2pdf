#!/usr/bin/env python3
"""Convert .sgf files into .gnos board diagrams for the gnos LaTeX font.

Reads AB/AW/LB/CR/TR/SQ/MA plus two extended attributes carried inside the
standard SGF comment property C[...]:

    VSZ[w:h]   viewport: show only w columns by h rows, anchored at the
               bottom-left corner of the board. Default: the whole board.
    CPT[text]  caption for the diagram. Default: empty.

So a corner problem on a 19x19 board might carry

    C[VSZ[11:9\\] CPT[Black to play\\] Digitized from page_023_fig_2]

Note the \\] escapes: per SGF a ']' inside a property value is backslash
escaped, which is what lets the attribute brackets nest inside C[...]
without closing it early.

Usage:
    sgf2gnos.py                          # sgf/ -> gnos/
    sgf2gnos.py --indir IN --outdir OUT  # directory mode
    sgf2gnos.py FILE.sgf -o FILE.gnos    # single file (used by the Makefile)
"""

import argparse
import glob
import os
import re
import sys

DEFAULT_BOARD_SIZE = 19

# Board template glyphs, indexed by which real board edges a point sits on.
GLYPH_INTERIOR = "+"
GLYPH_HOSHI = "*"
GLYPH_BLACK = "@"
GLYPH_WHITE = "!"

# Mark on a stone: uppercase for black, lowercase for white.
STONE_SYMBOL_CHAR = {
    ("B", "CR"): "C", ("W", "CR"): "c",
    ("B", "TR"): "T", ("W", "TR"): "t",
    ("B", "SQ"): "S", ("W", "SQ"): "s",
    ("B", "MA"): "X", ("W", "MA"): "x",
}
# Mark on an empty intersection.
EMPTY_SYMBOL_CHAR = {"CR": "1", "SQ": "2", "TR": "3", "MA": "4"}

MARK_PROPS = ("CR", "TR", "SQ", "MA")


# --------------------------------------------------------------------------
# SGF parsing
# --------------------------------------------------------------------------

def scan_value(text, i):
    """Scan one bracketed SGF property value starting at text[i] == '['.

    Returns (raw_value, index_after_closing_bracket). The value is returned
    still escaped -- backslash escapes are preserved so that callers can tell
    a literal ']' from a value terminator. Use unescape() to resolve them.
    """
    assert text[i] == "[", text[i:i + 10]
    i += 1
    out = []
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            # Backslash escapes the next character, whatever it is.
            out.append(c)
            i += 1
            if i < n:
                out.append(text[i])
                i += 1
            continue
        if c == "]":
            return "".join(out), i + 1
        out.append(c)
        i += 1
    # Unterminated value: take what we have.
    return "".join(out), i


def unescape(value):
    """Resolve SGF backslash escapes in a property value."""
    out = []
    i = 0
    n = len(value)
    while i < n:
        c = value[i]
        if c == "\\" and i + 1 < n:
            nxt = value[i + 1]
            if nxt == "\n":
                # Soft line break: removed entirely.
                i += 2
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_properties(text):
    """Parse an SGF into {property: [raw value, ...]}.

    A real scanner rather than a regex: property values are skipped over with
    scan_value, so bracket characters *inside* a value (an escaped ']', or the
    nested VSZ[...]/CPT[...] attributes in a comment) can never be mistaken for
    structure. All occurrences of a property are collected, not just the first.
    """
    props = {}
    i = 0
    n = len(text)
    while i < n:
        if not text[i].isupper():
            i += 1
            continue
        j = i
        while j < n and text[j].isupper():
            j += 1
        ident = text[i:j]
        values = []
        k = j
        while True:
            while k < n and text[k].isspace():
                k += 1
            if k >= n or text[k] != "[":
                break
            value, k = scan_value(text, k)
            values.append(value)
        if values:
            props.setdefault(ident, []).extend(values)
            i = k
        else:
            i = j
    return props


def extract_attribute(comment, name):
    """Pull NAME[...] out of an already-unescaped SGF comment value.

    The comment must be unescaped first: inside C[...] the attribute's own
    closing bracket has to be written '\\]' so it doesn't terminate the comment
    property, so it is only once those escapes are resolved that ']' means
    "end of attribute". Nesting is tracked by depth, so a caption may itself
    contain a balanced pair of brackets.
    """
    m = re.search(r"(?<![A-Za-z])" + name + r"\[", comment)
    if not m:
        return None
    depth = 1
    out = []
    for c in comment[m.end():]:
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                break
        out.append(c)
    return "".join(out)


def point_to_colrow(pt):
    """SGF point 'xy' -> (col, row), both 0-indexed, row 0 at the top."""
    return ord(pt[0]) - ord("a"), ord(pt[1]) - ord("a")


def parse_sgf(text):
    """Return (size, blacks, whites, labels, marks, viewport, caption)."""
    props = parse_properties(text)

    size = DEFAULT_BOARD_SIZE
    if props.get("SZ"):
        raw = unescape(props["SZ"][0]).strip()
        # SZ can be 'N' or 'W:H'; only square boards are supported here.
        m = re.match(r"^(\d+)(?::(\d+))?$", raw)
        if m:
            size = int(m.group(1))
            if m.group(2) and int(m.group(2)) != size:
                raise ValueError(f"non-square board SZ[{raw}] is not supported")

    def points(prop):
        return [unescape(v) for v in props.get(prop, []) if len(unescape(v)) == 2]

    blacks = points("AB")
    whites = points("AW")

    labels = {}
    for entry in props.get("LB", []):
        pt, _, value = unescape(entry).partition(":")
        if len(pt) == 2:
            labels[pt] = value

    marks = {prop: points(prop) for prop in MARK_PROPS}

    comment = unescape(props.get("C", [""])[0])
    viewport = parse_viewport(extract_attribute(comment, "VSZ"), size)
    caption = extract_attribute(comment, "CPT") or ""

    return size, blacks, whites, labels, marks, viewport, caption


def parse_viewport(raw, size):
    """'w:h' -> (width, height), clamped to the board. None/junk -> full board."""
    if raw:
        m = re.match(r"^\s*(\d+)\s*:\s*(\d+)\s*$", raw)
        if m:
            width = min(max(int(m.group(1)), 1), size)
            height = min(max(int(m.group(2)), 1), size)
            return width, height
    return size, size


# --------------------------------------------------------------------------
# Board rendering
# --------------------------------------------------------------------------

def hoshi_points(size):
    """Star points as a set of (col, row), following the usual conventions."""
    if size < 7:
        return set()
    edge = 3 if size >= 13 else 2
    far = size - 1 - edge
    pts = {(edge, edge), (edge, far), (far, edge), (far, far)}
    if size % 2 == 1:
        mid = size // 2
        pts.add((mid, mid))
        if size >= 19:
            pts |= {(edge, mid), (mid, edge), (far, mid), (mid, far)}
    return pts


def build_window_template(col0, col1, row0, row1, size):
    """Board template for the window [row0,row1) x [col0,col1).

    Edge and corner glyphs are used only where the window touches a real board
    boundary; the sides the window cuts through render as ordinary interior
    points, so a crop reads as a piece of a larger board rather than a tiny
    complete one.
    """
    last = size - 1
    hoshi = hoshi_points(size)
    board = []
    for row in range(row0, row1):
        top, bottom = row == 0, row == last
        line = []
        for col in range(col0, col1):
            left, right = col == 0, col == last
            if top and left:
                ch = "<"
            elif top and right:
                ch = ">"
            elif bottom and left:
                ch = ","
            elif bottom and right:
                ch = "."
            elif top:
                ch = "("
            elif bottom:
                ch = ")"
            elif left:
                ch = "["
            elif right:
                ch = "]"
            elif (col, row) in hoshi:
                ch = GLYPH_HOSHI
            else:
                ch = GLYPH_INTERIOR
            line.append(ch)
        board.append(line)
    return board


LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text):
    return "".join(LATEX_ESCAPES.get(c, c) for c in text)


def render_label(text, color):
    """Render an LB label, on a stone of `color` ('B'/'W') or on empty space."""
    if color is None:
        return r"{\gnosEmptyLbl{\small " + latex_escape(text) + "}}"

    font = "gnosb" if color == "B" else "gnosw"

    # Numbered stones: the gnos/gnosw fonts carry 1-99 as single glyphs.
    if text.isdigit() and 1 <= int(text) <= 99:
        return f"{{\\{font}\\char{int(text)}}}"

    # Lettered stones: gnosbl/gnoswl are italic a-z *on a stone*, indexed
    # \char1..26 (the literal letters in those fonts are bare, stoneless
    # italics, and there are no uppercase glyphs at all).
    if len(text) == 1 and "a" <= text <= "z":
        return f"{{\\{font}l\\char{ord(text) - ord('a') + 1}}}"

    # Anything else -- uppercase letters, multi-character text, numbers above
    # 99 -- is overlaid on a plain stone so the label survives verbatim.
    stone = GLYPH_BLACK if color == "B" else GLYPH_WHITE
    body = r"\small " + latex_escape(text)
    if color == "B":
        body = r"\color{white}" + body
    return rf"\gnosOverlap{{{stone}}}{{{body}}}"


def build_gnos(size, blacks, whites, labels, marks, viewport, caption):
    """Render one diagram as the body of a .gnos file."""
    width, height = viewport
    # The viewport is anchored at the bottom-left corner of the board.
    col0, col1 = 0, width
    row0, row1 = size - height, size

    board = build_window_template(col0, col1, row0, row1, size)

    def in_window(col, row):
        return col0 <= col < col1 and row0 <= row < row1

    color_at = {}
    for pt in blacks:
        color_at[pt] = "B"
    for pt in whites:
        color_at[pt] = "W"

    for pt, color in color_at.items():
        col, row = point_to_colrow(pt)
        if in_window(col, row):
            board[row - row0][col - col0] = GLYPH_BLACK if color == "B" else GLYPH_WHITE

    for prop, pts in marks.items():
        for pt in pts:
            col, row = point_to_colrow(pt)
            if not in_window(col, row):
                continue
            color = color_at.get(pt)
            board[row - row0][col - col0] = (
                STONE_SYMBOL_CHAR[(color, prop)] if color else EMPTY_SYMBOL_CHAR[prop]
            )

    for pt, text in labels.items():
        col, row = point_to_colrow(pt)
        if not in_window(col, row):
            continue
        board[row - row0][col - col0] = render_label(text, color_at.get(pt))

    lines = []
    for row in board:
        # A bare '[' would be read as the start of an optional argument.
        cells = ["{\\char91}" if c == "[" else c for c in row]
        lines.append("\\line{" + "".join(cells) + "}")

    # \gnoscols lets the consuming document size its box from the file alone,
    # and \gnoscaption carries the caption along with the position -- both are
    # read by sgf2pdf.sty before the board itself is typeset.
    header = f"\\gnoscols{{{width}}}%\n"
    header += f"\\gnoscaption{{{latex_escape(caption)}}}%\n"
    return header + "{\\gnos%\n" + "\n".join(lines) + "\n}%\n"


def convert(text):
    return build_gnos(*parse_sgf(text))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def convert_file(src, dst):
    with open(src, encoding="utf-8") as f:
        text = f.read()
    gnos = convert(text)
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(gnos)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", nargs="?", help="a .sgf file, or a directory of them")
    parser.add_argument("-o", "--output", help="output .gnos file (single-file mode)")
    parser.add_argument("--indir", default="sgf", help="input directory (default: sgf)")
    parser.add_argument("--outdir", default="gnos", help="output directory (default: gnos)")
    args = parser.parse_args()

    if args.input and os.path.isfile(args.input):
        dst = args.output or os.path.join(
            args.outdir, os.path.splitext(os.path.basename(args.input))[0] + ".gnos"
        )
        convert_file(args.input, dst)
        return 0

    if args.output:
        parser.error("-o/--output only applies when the input is a single .sgf file")

    indir = args.input or args.indir
    paths = sorted(glob.glob(os.path.join(indir, "*.sgf")))
    if not paths:
        print(f"No .sgf files found in {indir}/", file=sys.stderr)
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    for path in paths:
        stem = os.path.splitext(os.path.basename(path))[0]
        convert_file(path, os.path.join(args.outdir, stem + ".gnos"))
    print(f"Wrote {len(paths)} .gnos files to {args.outdir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
