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
import importlib.util
import json
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from bs4 import BeautifulSoup

_spec = importlib.util.spec_from_file_location(
    "build_index", Path(__file__).resolve().parent / "build-index.py")
build_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_index)

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


# --- index.html restates facts from other pages --------------------------
#
# The front page repeats counts from the list pages, shows the newest talks
# and podcasts, and summarises now.html. In November 2026 it still advertised
# four talks from September and October as upcoming. The feed is generated by
# build-index.py and checked here against a fresh rendering; the rest is prose
# and is compared with its source.
#
# The "Speaking next" check depends on today's date: once the named talk has
# happened, the next push fails until index.html and now.html name the next
# one (or stop saying "Next up"). That is the point -- the front page must not
# advertise past events. --today pins the date for testing.

# Which list page each number on the index counts, and how to count it.
COUNTS = {
    "talks.html": "main .talk-header",
    "podcasts.html": "main .talk-header",
    "books.html": "main .card",
    "articles.html": "main ul.list-unstyled > li",
    "research.html": "main .card",
    "open-source.html": "main .card",
}
# Index tiles are matched to a page by a word in their label.
TILE_LABELS = {"talks": "talks.html", "podcast": "podcasts.html",
               "books": "books.html", "papers": "research.html",
               "open-source": "open-source.html"}


def upcoming_talks(site):
    """Talks on talks.html dated today or later, soonest first."""
    today = site["today"].isoformat()
    talks = []
    for card in site["soups"]["talks.html"].select("main .card[data-date]"):
        if card["data-date"] < today:
            continue
        target = card.select_one(".collapse[id]")
        title = card.select_one(".talk-title")
        talks.append({
            "date": card["data-date"],
            "anchor": target["id"] if target else None,
            "title": title.get_text(" ", strip=True) if title else "",
        })
    return sorted(talks, key=lambda t: t["date"])


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def as_of_month(soup):
    """The yyyy-mm of the first <time> in a sentence containing 'as of'."""
    for t in soup.select("time[datetime]"):
        if "as of" in (t.parent.get_text(" ", strip=True) if t.parent else ""):
            return t["datetime"][:7]
    return None


def check_index_sync(path, soup, site):
    if path.name != "index.html":
        return []
    out = []
    soups = site["soups"]

    # 1. Numbers restated from the list pages.
    actual = {page: len(soups[page].select(sel))
              for page, sel in COUNTS.items() if page in soups}
    numbers = soup.select_one('section[aria-labelledby="numbers-heading"]')
    if numbers:
        for link in numbers.select("a[href]"):
            m = re.match(r"(\d+)\b", link.get_text(strip=True))
            page = link["href"]
            if m and page in actual and int(m.group(1)) != actual[page]:
                out.append(f"numbers: link says {m.group(0)} for {page}, "
                           f"which has {actual[page]}")
        for tile in numbers.select(".col"):
            value = tile.select_one(".display-6")
            label = tile.get_text(" ", strip=True).lower()
            page = next((p for word, p in TILE_LABELS.items() if word in label), None)
            if not (value and page and value.get_text(strip=True).isdigit()):
                continue
            if int(value.get_text(strip=True)) != actual[page]:
                out.append(f"numbers: tile says {value.get_text(strip=True)} "
                           f"for {page}, which has {actual[page]}")

    # 2. The "Recent & upcoming" feed is generated from talks.html and
    #    podcasts.html by build-index.py; it must match a fresh rendering.
    upcoming = upcoming_talks(site)
    feed = re.search(re.escape(build_index.BEGIN) + r".*?" + re.escape(build_index.END),
                     path.read_text(), re.S)
    if not feed:
        out.append("feed: generated block missing; run tools/build-index.py")
    elif feed.group(0) != build_index.render():
        out.append("feed: stale against talks.html/podcasts.html; run tools/build-index.py")

    # 3. "Speaking next" here and the Speaking paragraph on now.html name the
    #    next talk -- or, with nothing scheduled, do not claim a next one.
    blurbs = []
    for h3 in soup.select("h3"):
        if h3.get_text(strip=True) == "Speaking next":
            body = h3.find_next_sibling("p")
            blurbs.append(("index.html Speaking next", body))
    now = soups.get("now.html")
    if now:
        h2 = next((h for h in now.select("h2") if h.get_text(strip=True) == "Speaking"), None)
        blurbs.append(("now.html Speaking", h2.find_next_sibling("p") if h2 else None))
    for where, body in blurbs:
        text = norm(body.get_text(" ", strip=True)) if body else ""
        if upcoming and norm(upcoming[0]["title"]) not in text:
            out.append(f"{where}: does not name the next talk, "
                       f"{upcoming[0]['title']!r} on {upcoming[0]['date']}")
        if not upcoming and "Next up" in text:
            out.append(f"{where}: says 'Next up' but talks.html has nothing upcoming")

    # 4. The "What I'm doing now" snapshot is as current as now.html.
    if now:
        here, there = as_of_month(soup), as_of_month(now)
        if here != there:
            out.append(f"now snapshot: index says as of {here}, now.html says {there}")
    return out


# 404.html is served for unknown URLs, not linked to.
UNLINKED_OK = {"404.html", "index.html"}


def check_reachable(path, soup, site):
    """Every page is linked from the front page. The top navigation lists only
    some of them (Bio, Articles, and Now were dropped from it in November
    2026), so the index body has to carry the rest."""
    if path.name != "index.html":
        return []
    linked = {a["href"].lstrip("/").partition("#")[0] for a in soup.select("a[href]")}
    missing = sorted(site["pages"] - UNLINKED_OK - linked)
    return [f"{page} is not linked from the front page" for page in missing]


CHECKS = [
    ("nesting", check_nesting),
    ("headings", check_one_h1),
    ("ids", check_unique_ids),
    ("links", check_links),
    ("json-ld", check_jsonld),
    ("head", check_head),
    ("index-sync", check_index_sync),
    ("reachable", check_reachable),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="only print failures")
    ap.add_argument("--today", metavar="YYYY-MM-DD",
                    help="date that decides which talks are upcoming (default: today)")
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
        "soups": {},
        "today": date.fromisoformat(args.today) if args.today else date.today(),
    }
    soups = {}
    for p in pages:
        soups[p] = BeautifulSoup(p.read_text(), "html.parser")
        site["soups"][p.name] = soups[p]
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
