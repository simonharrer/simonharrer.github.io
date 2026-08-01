#!/usr/bin/env python3
"""Regenerate llms-full.txt from the site's own pages.

llms.txt is the short index: a summary plus one line per page. llms-full.txt is
its long companion — the readable text of every page in a single Markdown file,
so a model that follows the index can take in the whole site in one fetch
instead of crawling nine HTML pages.

Like tools/build-jsonld.py, this reads the rendered markup rather than keeping a
second copy of every talk, episode, article, and paper, so the two cannot drift.
The hand-written parts — summary, key facts, profiles — come from llms.txt,
which stays their single source.

Run from the repository root after editing any page:

    python3 tools/build-llms-full.py            # rewrite llms-full.txt
    python3 tools/build-llms-full.py --check    # exit 1 if it is out of date
    python3 tools/build-llms-full.py --print    # print instead of writing

Requires: beautifulsoup4
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

SITE = "https://simonharrer.com"

NOTE = (
    "This is the full text of every page on the site, gathered into one file. "
    f"See {SITE}/llms.txt for the short index. Generated from the pages "
    "themselves by tools/build-llms-full.py — edit the pages, not this file."
)


def squeeze(s):
    """Collapse whitespace and repair the gaps get_text(' ') leaves behind."""
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    return s


def linker(page):
    """A Markdown renderer bound to a page, so relative hrefs resolve correctly."""
    base = f"{SITE}/{page}"

    def md(el, drop=()):
        """Readable text of an element: links become [text](url), markup is flattened."""
        if el is None:
            return ""
        clone = BeautifulSoup(str(el), "html.parser")
        for sel in ("svg", "picture", "img") + tuple(drop):
            for node in clone.select(sel):
                node.decompose()
        for a in clone.find_all("a"):
            text = squeeze(a.get_text(" ", strip=True))
            href = a.get("href")
            a.replace_with(f"[{text}]({urljoin(base, href)})" if text and href else text)
        return squeeze(clone.get_text(" ", strip=True))

    return md


def joined(parts, sep=" · "):
    """Join the parts that are actually there."""
    return sep.join(p for p in parts if p)


def badges_of(el, md):
    """Badge labels on a card title or header — Bestseller, star counts, Upcoming."""
    return [md(b) for b in el.select(".badge")] if el else []


def sections(soup):
    """The page's <h2> groupings and the cards under each, in document order.

    Yields the heading element itself so a builder can also reach whatever
    immediately follows it, such as an introductory paragraph.
    """
    groups, current = [], None
    container = soup.select_one("main .container")
    for el in container.find_all(["h2", "div"], recursive=True):
        if el.name == "h2":
            current = (el, [])
            groups.append(current)
        elif "card" in (el.get("class") or []) and el.select_one(".card-body"):
            if current is None:
                current = (None, [])
                groups.append(current)
            current[1].append(el)
    return groups


def page_intro(soup, md):
    """The lead paragraph(s) between the <h1> and the first section."""
    out = []
    h1 = soup.select_one("main h1")
    for sib in h1.find_next_siblings() if h1 else []:
        if sib.name in ("h2", "div", "ul", "hr"):
            break
        if sib.name == "p":
            text = md(sib)
            if text:
                out.append(text)
    return out


# --- per-page builders ------------------------------------------------------


def build_index(soup):
    md = linker("index.html")
    out = [f"Source: {SITE}/"]
    for p in soup.select("main .col-lg-3 p"):
        text = md(p)
        if text:
            out.append(text)
    out.append("")
    out.append("### Frequently asked questions")
    for block in soup.select('section[aria-labelledby="faq-heading"] div.mb-4'):
        question = block.select_one("h3")
        answer = block.select_one("p")
        if question and answer:
            out += ["", f"**{md(question)}**", md(answer)]
    return out


def build_now(soup):
    md = linker("now.html")
    out = [f"Source: {SITE}/now.html", ""]
    container = soup.select_one("main .container")
    for el in container.find_all(["h2", "p", "hr"], recursive=False):
        if el.name == "hr":
            break
        out.append(f"### {md(el)}" if el.name == "h2" else md(el))
    return out


def build_books(soup):
    md = linker("books.html")
    out = [f"Source: {SITE}/books.html"] + page_intro(soup, md)
    for heading_el, cards in sections(soup):
        if heading_el is not None:
            out += ["", f"### {md(heading_el)}"]
        for card in cards:
            title_el = card.select_one(".card-title")
            meta = md(card.select_one("p.card-text.text-muted"))
            body = card.select_one("p.card-text:not(.text-muted):not(.text-center)")
            links = [md(a) for a in card.select(".btn-group a")]

            out += ["", f"#### {md(title_el, drop=['.badge'])}"]
            out.append(joined([meta] + badges_of(title_el, md)))
            if body:
                out.append(md(body))
            for extra in card.select("p.card-text.text-center small"):
                out.append(md(extra))
            if links:
                out.append("Where to get it: " + joined(links))
    return out


def build_open_source(soup):
    md = linker("open-source.html")
    out = [f"Source: {SITE}/open-source.html"] + page_intro(soup, md)
    for heading_el, cards in sections(soup):
        if heading_el is not None:
            out += ["", f"### {md(heading_el)}"]
        for card in cards:
            title_el = card.select_one(".card-title")
            body = card.select_one("p.card-text:not(.text-center)")

            out += ["", f"#### {md(title_el, drop=['.badge'])}"]
            marks = badges_of(title_el, md)
            if marks:
                out.append(joined(marks))
            if body:
                out.append(md(body))
            for extra in card.select("p.card-text.text-center small"):
                out.append(md(extra))
            for link in card.select("div.text-center > a.btn"):
                out.append("Repository: " + md(link))
    return out


def build_research(soup):
    md = linker("research.html")
    out = [f"Source: {SITE}/research.html"] + page_intro(soup, md)
    for heading_el, cards in sections(soup):
        if heading_el is not None:
            out += ["", f"### {md(heading_el)}"]
            # a section may open with a scope note; only the heading's own
            # immediate sibling counts, never the next section's
            note = heading_el.find_next_sibling()
            if note is not None and note.name == "p":
                out.append(md(note))
        for card in cards:
            title_el = card.select_one(".card-title")
            meta_el = card.select_one("p.text-muted")
            body = card.select_one("p.card-text")
            links = [md(a) for a in card.select("a.btn")]

            out += ["", f"#### {md(title_el, drop=['.badge'])}"]
            out.append(joined(badges_of(meta_el, md) + [md(meta_el, drop=[".badge"])]
                              + badges_of(title_el, md)))
            if body:
                out.append(md(body))
            if links:
                out.append(joined(links))
    return out


def build_collapsibles(soup, page, label):
    """talks.html and podcasts.html: collapsible cards keyed by an anchor."""
    md = linker(page)
    out = [f"Source: {SITE}/{page}"] + page_intro(soup, md)
    for card in soup.select("div.card"):
        header = card.select_one(".talk-header")
        if header is None:
            continue
        anchor = (header.get("data-bs-target") or "").lstrip("#")
        title_el = header.select_one(".talk-title")
        flag = header.select_one(".flag")
        language = flag.get("title") if flag else None

        out += ["", f"### {md(title_el, drop=['.badge'])}"]
        out.append(joined([md(header.select_one(".talk-meta")), language]
                          + badges_of(header, md)))
        if anchor:
            out.append(f"{SITE}/{page}#{anchor}")
        body = soup.select_one(f"#{anchor}") if anchor else None
        for p in body.select(".card-body > p") if body else []:
            text = md(p)
            if text:
                out += ["", text]
    if not any(line.startswith("### ") for line in out):
        raise ValueError(f"{page}: no {label} found — has the markup changed?")
    return out


def build_articles(soup):
    md = linker("articles.html")
    out = [f"Source: {SITE}/articles.html"] + page_intro(soup, md)
    for alert in soup.select("main .alert"):
        out += ["", md(alert)]
    for li in soup.select("main ul.list-unstyled > li"):
        title_link = li.select_one("a")
        strong = li.select_one("strong")
        small = li.select_one("small")
        if not (title_link and strong and small):
            continue
        flags = [s.get("title") for s in li.select("span[title]")]
        badges = [md(b) for b in li.select(".badge")]
        blurb = li.select_one("span.text-muted")
        german = next((a for a in li.select("a") if a.get_text(strip=True) == "German"), None)

        out += ["", f"### {strong.get_text(' ', strip=True)}"]
        out.append(joined([md(small)] + badges + [", ".join(f for f in flags if f)]))
        out.append(urljoin(f"{SITE}/articles.html", title_link.get("href")))
        if german:
            out.append("German version: " + german.get("href"))
        if blurb:
            out.append(md(blurb))
    return out


def build_bio(soup):
    md = linker("bio.html")
    out = [
        f"Source: {SITE}/bio.html",
        "Copy-ready bio and press photo for event organizers and journalists, in English (EN) and German (DE).",
        "",
        "### Contact and press details",
    ]
    for group in soup.select("div.input-group"):
        label_el = group.select_one(".input-group-text")
        field = group.select_one("input")
        if field is None:
            continue
        label = md(label_el.select_one('[data-lang="en"]') or label_el) if label_el else ""
        values = [field.get("value")]
        if field.get("data-val-de") and field["data-val-de"] != field.get("value"):
            values.append(f"DE: {field['data-val-de']}")
        out.append(joined([label or field.get("aria-label", ""), " / ".join(values)], sep=": "))

    out += ["", "### Press photo"]
    for link in soup.select("a[download]"):
        # the label already sits next to the URL below, so keep it as plain text
        size = squeeze(link.get_text(" ", strip=True))
        out.append(joined([size, urljoin(f"{SITE}/bio.html", link.get("href"))], sep=" — "))

    for card in soup.select(".bio-card"):
        title_el = card.select_one(".card-title")
        body = card.select_one(".card-text")
        heading = md(title_el.select_one('[data-lang="en"]') or title_el)
        out += ["", f"### {heading}"]
        for lang in ("en", "de"):
            text = " ".join(
                md(el) for el in body.select(f'[data-lang="{lang}"]')
            ).strip()
            if text:
                out.append(f"{lang.upper()}: {text}")
    return out


PAGES = [
    ("About", "index.html", build_index),
    ("Now", "now.html", build_now),
    ("Books", "books.html", build_books),
    ("Open Source", "open-source.html", build_open_source),
    ("Research", "research.html", build_research),
    ("Talks", "talks.html", lambda s: build_collapsibles(s, "talks.html", "talks")),
    ("Podcasts", "podcasts.html", lambda s: build_collapsibles(s, "podcasts.html", "episodes")),
    ("Articles", "articles.html", build_articles),
    ("Bio", "bio.html", build_bio),
]


def preamble(root):
    """Title, summary, key facts, and profiles, taken from llms.txt.

    The "## Pages" index is dropped: llms-full.txt *is* those pages.
    """
    blocks = re.split(r"\n(?=## )", (root / "llms.txt").read_text())
    head, rest = blocks[0], [b for b in blocks[1:] if not b.startswith("## Pages")]
    return head.rstrip(), [b.rstrip() for b in rest]


def render(root):
    head, facts = preamble(root)
    out = [head, "", NOTE, ""] + [b + "\n" for b in facts]
    for title, page, builder in PAGES:
        soup = BeautifulSoup((root / page).read_text(), "html.parser")
        out.append(f"## {title}")
        out += [ln for ln in builder(soup)]
        out.append("")
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if llms-full.txt is stale")
    ap.add_argument("--print", dest="show", action="store_true", help="print instead of writing")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    payload = render(root)

    if args.show:
        print(payload, end="")
        return

    target = root / "llms-full.txt"
    if target.exists() and target.read_text() == payload:
        print("llms-full.txt: unchanged")
        return
    if args.check:
        print("llms-full.txt is stale (run without --check to fix)", file=sys.stderr)
        raise SystemExit(1)

    target.write_text(payload)
    print(f"llms-full.txt: wrote {len(payload.splitlines())} lines, {len(payload)} bytes")


if __name__ == "__main__":
    main()
