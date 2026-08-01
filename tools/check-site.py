#!/usr/bin/env python3
"""Structural checks for the hand-edited HTML pages.

The pages are written by hand, so the failures worth catching are the ones a
browser hides. An unbalanced <div> still renders — Chrome silently repairs the
tree — but the row and column boundaries are wrong, and a card ends up twice as
wide as its neighbours. That shipped twice before this existed.

Run from the repository root:

    python3 tools/check-site.py            # report problems, exit 1 if any
    python3 tools/check-site.py --quiet    # only print failures

Pairs with the two generators, which check their own output:

    python3 tools/build-jsonld.py --check
    python3 tools/build-llms-full.py --check

Requires: beautifulsoup4
"""

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

from bs4 import BeautifulSoup

# Elements whose end tag is mandatory in HTML. Anything with an optional end
# tag (p, li, td) would produce false positives, so it is deliberately absent.
TRACKED = {
    "div", "section", "main", "header", "footer", "nav", "article", "aside",
    "ul", "ol", "table", "picture", "button", "form", "label", "select",
}
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
# 404.html is served for unknown URLs, so it is noindex and carries no canonical
NO_CANONICAL = {"404.html"}


class Nesting(HTMLParser):
    """Tracks the elements that must be closed explicitly, and reports on any
    that are left open, closed twice, or closed out of order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.problems = []
        self.in_svg = 0

    def handle_starttag(self, tag, attrs):
        if tag == "svg":
            self.in_svg += 1
        if self.in_svg or tag in VOID or tag not in TRACKED:
            return
        self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        pass  # self-closing, nothing to track

    def handle_endtag(self, tag):
        if tag == "svg":
            self.in_svg = max(0, self.in_svg - 1)
            return
        if self.in_svg or tag not in TRACKED:
            return
        line = self.getpos()[0]
        if not self.stack:
            self.problems.append(f"line {line}: stray </{tag}>")
            return
        if self.stack[-1][0] == tag:
            self.stack.pop()
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for orphan, opened in self.stack[i + 1:]:
                    self.problems.append(
                        f"line {opened}: <{orphan}> never closed "
                        f"(</{tag}> on line {line} closed past it)")
                del self.stack[i:]
                return
        self.problems.append(f"line {line}: stray </{tag}>")

    def finish(self):
        for tag, line in self.stack:
            self.problems.append(f"line {line}: <{tag}> never closed")
        return self.problems


def check_nesting(path, soup, site):
    p = Nesting()
    p.feed(path.read_text())
    return p.finish()


def check_one_h1(path, soup, site):
    h1s = soup.select("h1")
    if len(h1s) == 1:
        return []
    if not h1s:
        return ["no <h1>"]
    return [f"{len(h1s)} <h1> elements: " + ", ".join(
        repr(h.get_text(" ", strip=True)[:40]) for h in h1s)]


def check_unique_ids(path, soup, site):
    seen, dupes = set(), []
    for el in soup.select("[id]"):
        if el["id"] in seen:
            dupes.append(el["id"])
        seen.add(el["id"])
    return [f"duplicate id {d!r}" for d in sorted(set(dupes))]


def check_links(path, soup, site):
    """Every relative href/src resolves, and every #fragment exists."""
    out = []
    ids = {el["id"] for el in soup.select("[id]")}
    refs = []
    for el in soup.select("[href], [src], [srcset]"):
        refs += [el.get("href"), el.get("src")]
        refs += [part.strip().split()[0]
                 for part in (el.get("srcset") or "").split(",") if part.strip()]
    for ref in filter(None, refs):
        ref = ref.strip()
        if ref.startswith(("http://", "https://", "mailto:", "tel:", "data:")):
            continue
        if ref.startswith("#"):
            if ref != "#" and ref[1:] not in ids:
                out.append(f"dead anchor {ref}")
            continue
        target, _, frag = ref.lstrip("/").partition("#")
        if target and target not in site["files"]:
            out.append(f"missing {target}")
        elif frag and target in site["pages"]:
            if frag not in site["ids"][target]:
                out.append(f"dead link {target}#{frag}")
    return sorted(set(out))


def check_jsonld(path, soup, site):
    out = []
    for i, block in enumerate(soup.select('script[type="application/ld+json"]')):
        try:
            json.loads(block.string or "")
        except Exception as e:
            out.append(f"JSON-LD block {i} does not parse: {e}")
    return out


def check_head(path, soup, site):
    out = []
    title = soup.select_one("title")
    if not (title and title.get_text(strip=True)):
        out.append("missing or empty <title>")
    desc = soup.find("meta", attrs={"name": "description"})
    if path.name not in NO_CANONICAL and not (desc and desc.get("content", "").strip()):
        out.append("missing meta description")

    canonical = soup.find("link", attrs={"rel": "canonical"})
    og_url = soup.find("meta", attrs={"property": "og:url"})
    if path.name in NO_CANONICAL:
        return out
    if not canonical:
        out.append("missing canonical")
    elif og_url and canonical["href"] != og_url.get("content"):
        out.append(f"canonical {canonical['href']} != og:url {og_url.get('content')}")
    return out


CHECKS = [
    ("nesting", check_nesting),
    ("headings", check_one_h1),
    ("ids", check_unique_ids),
    ("links", check_links),
    ("json-ld", check_jsonld),
    ("head", check_head),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="only print failures")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    pages = sorted(root.glob("*.html"))
    site = {
        "pages": {p.name for p in pages},
        "files": {
            str(f.relative_to(root).as_posix())
            for f in root.rglob("*")
            if f.is_file() and not str(f.relative_to(root)).startswith(".git/")
        } | {""},
        "ids": {},
    }
    soups = {}
    for p in pages:
        soups[p] = BeautifulSoup(p.read_text(), "html.parser")
        site["ids"][p.name] = {el["id"] for el in soups[p].select("[id]")}

    # titles and descriptions should be unique, which is a cross-page property
    titles, descs = {}, {}
    failures = 0
    for p in pages:
        problems = []
        for name, check in CHECKS:
            for msg in check(p, soups[p], site):
                problems.append(f"{name}: {msg}")

        t = soups[p].select_one("title")
        t = t.get_text(strip=True) if t else ""
        d = soups[p].find("meta", attrs={"name": "description"})
        d = d.get("content", "").strip() if d else ""
        if t:
            titles.setdefault(t, []).append(p.name)
        if d:
            descs.setdefault(d, []).append(p.name)

        if problems:
            failures += len(problems)
            print(f"✗ {p.name}")
            for msg in problems:
                print(f"    {msg}")
        elif not args.quiet:
            print(f"✓ {p.name}")

    for label, table in (("title", titles), ("meta description", descs)):
        for value, owners in sorted(table.items()):
            if len(owners) > 1:
                failures += 1
                print(f"✗ duplicate {label} across {', '.join(owners)}: {value[:60]!r}")

    if failures:
        print(f"\n{failures} problem(s) found", file=sys.stderr)
        raise SystemExit(1)
    if not args.quiet:
        print(f"\n{len(pages)} pages checked, no problems")


if __name__ == "__main__":
    main()
