#!/usr/bin/env python3
"""Wrap an Artifact-style HTML fragment into a standalone HTML document.

Pages written for the Artifact tool start at <title>/<style> and omit <!doctype>,
<html>, <head> and <body>, because the artifact runtime supplies them. Static hosts
like Surge do not, so the fragment loses its charset and viewport declarations —
which garbles non-Latin text and breaks mobile layout.

This splits the fragment at its first top-level content element: everything before
it is head material (title, link, style, meta), everything from it on is body.

Usage:
    python3 wrap_html.py <fragment.html> <outdir>/index.html [--lang XX] [--allow-indexing]

    --lang XX         Value for <html lang>. Defaults to "ja"; set it to match the page's
                      actual language, since screen readers and hyphenation rely on it.
    --allow-indexing  Omit the noindex robots meta tag (included by default).

Parent directories of the output path are created automatically, so there is no need to
mkdir first.
"""

import argparse
import re
import sys
from pathlib import Path

# First top-level element that belongs in <body>. Ordered so that a wrapper element
# (<article>, <main>, <div>) wins over a heading nested inside it.
BODY_START = re.compile(
    r"<(article|main|section|div|header|nav|body|h1)\b", re.IGNORECASE
)

HEAD_TEMPLATE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
{robots}{head}
</head>
<body>
{body}
</body>
</html>
"""


def wrap(content: str, lang: str = "ja", allow_indexing: bool = False) -> str:
    match = BODY_START.search(content)
    if match:
        head, body = content[: match.start()].strip(), content[match.start() :].strip()
    else:
        # No recognizable body element — treat the whole fragment as body content and
        # let the template supply the head. Better than guessing wrong and dropping markup.
        head, body = "", content.strip()

    robots = "" if allow_indexing else '<meta name="robots" content="noindex, nofollow">\n'
    return HEAD_TEMPLATE.format(lang=lang, robots=robots, head=head, body=body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="HTML fragment to wrap")
    parser.add_argument("output", type=Path, help="output file, e.g. <outdir>/index.html")
    parser.add_argument("--lang", default="ja", help="value for <html lang> (default: ja)")
    parser.add_argument("--allow-indexing", action="store_true", help="omit the noindex tag")
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"error: no such file: {args.source}", file=sys.stderr)
        return 1

    content = args.source.read_text(encoding="utf-8")
    if "<!doctype" in content[:200].lower() or "<html" in content[:200].lower():
        print(
            f"note: {args.source} already looks like a complete document; copying as-is",
            file=sys.stderr,
        )
        result = content
    else:
        result = wrap(content, lang=args.lang, allow_indexing=args.allow_indexing)

    dest = args.output / "index.html" if args.output.is_dir() else args.output
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result, encoding="utf-8")
    # Report encoded length, not len(str): CJK characters are multibyte, and this number is
    # meant to be compared against the size_download from the post-deploy curl check.
    print(f"wrote {dest} ({len(result.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
