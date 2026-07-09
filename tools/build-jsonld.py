#!/usr/bin/env python3
"""Regenerate the JSON-LD blocks for the list pages from their own markup.

The pages are hand-edited HTML. Rather than maintaining a parallel copy of every
talk, episode, article, and project inside a <script type="application/ld+json">
block, this reads the rendered markup and emits the structured data from it, so
the two cannot drift.

Run from the repository root after editing any of the list pages:

    python3 tools/build-jsonld.py            # rewrite the pages in place
    python3 tools/build-jsonld.py --check    # exit 1 if a page is out of date
    python3 tools/build-jsonld.py --print talks.html

Requires: beautifulsoup4
"""

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

SITE = "https://simonharrer.com"
PERSON = {"@id": f"{SITE}/#person"}
WEBSITE = {"@type": "WebSite", "name": "Simon Harrer", "url": f"{SITE}/"}

MONTHS = {
    "januar": 1, "january": 1,
    "februar": 2, "february": 2,
    "märz": 3, "march": 3,
    "april": 4,
    "mai": 5, "may": 5,
    "juni": 6, "june": 6,
    "juli": 7, "july": 7,
    "august": 8,
    "september": 9,
    "oktober": 10, "october": 10,
    "november": 11,
    "dezember": 12, "december": 12,
}
MON = "|".join(sorted(MONTHS, key=len, reverse=True))
LANGS = {"English": "en", "German": "de"}


def parse_date(s):
    """Parse the German/English date prefixes used across the site.

    Returns an ISO string at whatever precision the source gives us
    (2026-09-17, 2026-09, or 2026), or None.
    """
    s = s.strip()
    # "11–12 June 2026" / "22–24 September 2025": a range starts on its first day
    m = re.match(rf"^(\d{{1,2}})\s*[–—-]\s*\d{{1,2}}\.?\s+({MON})\s+(\d{{4}})$", s, re.I)
    if not m:
        # "17 September 2026" / "23. Juni 2026"
        m = re.match(rf"^(\d{{1,2}})\.?\s+({MON})\s+(\d{{4}})$", s, re.I)
    if m:
        return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    # "Issue 05/2022 (May 2022)" -> the parenthetical is the real date
    m = re.search(rf"\(({MON})\s+(\d{{4}})\)$", s, re.I)
    if not m:
        # "Dezember 2025" / "July 2023"
        m = re.match(rf"^({MON})\s+(\d{{4}})$", s, re.I)
    if m:
        return f"{int(m.group(2)):04d}-{MONTHS[m.group(1).lower()]:02d}"
    m = re.match(r"^(\d{4})$", s)
    return m.group(1) if m else None


def text_of(el, drop=()):
    """Visible text of an element, with the given selectors removed first."""
    if el is None:
        return ""
    clone = BeautifulSoup(str(el), "html.parser")
    for sel in drop:
        for node in clone.select(sel):
            node.decompose()
    return re.sub(r"\s+", " ", clone.get_text(" ", strip=True)).strip()


def collection_page(name, url, description, about, items):
    """A CollectionPage whose mainEntity is a positioned ItemList."""
    return {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": name,
        "url": url,
        "description": description,
        "about": about,
        "author": PERSON,
        "isPartOf": WEBSITE,
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{SITE}/"},
                {"@type": "ListItem", "position": 2, "name": name.split(" — ")[0], "item": url},
            ],
        },
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(items),
            "itemListElement": [
                {"@type": "ListItem", "position": i, "item": it}
                for i, it in enumerate(items, 1)
            ],
        },
    }


def cards(soup):
    """Collapsible cards on talks.html / podcasts.html, in document order."""
    for card in soup.select("div.card"):
        header = card.select_one(".talk-header")
        if header is None:
            continue
        anchor = (header.get("data-bs-target") or "").lstrip("#")
        body = soup.select_one(f"#{anchor}") if anchor else None
        paragraphs = body.select(".card-body > p") if body else []
        yield card, header, anchor, paragraphs


def header_fields(header):
    badges = [b.get_text(strip=True) for b in header.select(".badge")]
    flag = header.select_one(".flag")
    meta_el = header.select_one(".talk-meta")
    return {
        "badges": badges,
        "lang": LANGS.get(flag.get("title")) if flag else None,
        # the title carries an inline "Upcoming" badge on future entries
        "title": text_of(header.select_one(".talk-title"), drop=[".badge"]),
        "meta": text_of(meta_el),
    }


def build_talks(soup):
    items = []
    for card, header, anchor, paragraphs in cards(soup):
        f = header_fields(header)
        segments = [s.strip() for s in f["meta"].split("·")]
        start = parse_date(segments[0])
        if not start:
            raise ValueError(f"talks.html: unparsed date {segments[0]!r}")
        venue = segments[1] if len(segments) > 1 else ""
        venue = re.sub(r"\s*\([^)]*\)\s*$", "", venue).strip()  # drop room/time
        online = "Online" in f["badges"]

        event = {
            "@type": "Event",
            "@id": f"{SITE}/talks.html#{anchor}",
            "url": f"{SITE}/talks.html#{anchor}",
            "name": f["title"],
            "startDate": start,
            "performer": PERSON,
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": (
                "https://schema.org/OnlineEventAttendanceMode" if online
                else "https://schema.org/OfflineEventAttendanceMode"
            ),
        }
        if online:
            event["location"] = {"@type": "VirtualLocation", "url": f"{SITE}/talks.html#{anchor}"}
        elif venue:
            event["location"] = {"@type": "Place", "name": venue}
        if venue:
            conference = venue.split(",")[0].strip()
            if conference and conference != venue:
                event["superEvent"] = {"@type": "Event", "name": conference}
        if f["lang"]:
            event["inLanguage"] = f["lang"]
        if paragraphs:
            event["description"] = text_of(paragraphs[0])
        # "Talk" is the unmarked default; only the distinctive formats are worth stating
        kinds = [b for b in f["badges"] if b in ("Workshop", "Keynote")]
        if kinds:
            event["keywords"] = kinds
        items.append(event)
    return items


def build_podcasts(soup):
    items = []
    for card, header, anchor, paragraphs in cards(soup):
        f = header_fields(header)
        segments = [s.strip() for s in f["meta"].split("·")]
        published = parse_date(segments[0])
        series = segments[1] if len(segments) > 1 else ""
        # the trailing paragraph holds the listen/watch links
        links = [a.get("href") for a in (paragraphs[-1].select("a") if paragraphs else [])]
        external = [h for h in links if h and h.startswith("http")]

        written = "Article" in f["badges"]
        node = {
            "@type": "Article" if written else "PodcastEpisode",
            "@id": f"{SITE}/podcasts.html#{anchor}",
            "name": f["title"],
            "author": PERSON,
        }
        if written:
            node["headline"] = f["title"]
            if series:
                node["publisher"] = {"@type": "Organization", "name": series}
        elif series:
            node["partOfSeries"] = {"@type": "PodcastSeries", "name": series}
        # a recorded-but-unreleased episode has no publication date yet
        if published and "Upcoming" not in f["badges"]:
            node["datePublished"] = published
        if external:
            node["url"] = external[0]
        if f["lang"]:
            node["inLanguage"] = f["lang"]
        if paragraphs:
            node["description"] = text_of(paragraphs[0])
        items.append(node)
    return items


def build_articles(soup):
    items = []
    for li in soup.select("ul.list-unstyled > li"):
        title_link = li.select_one("a")
        strong = li.select_one("strong")
        small = li.select_one("small")
        if not (title_link and strong and small):
            continue
        segments = [s.strip() for s in text_of(small).split("·")]
        publisher = segments[0] if segments else ""
        published = parse_date(segments[1]) if len(segments) > 1 else None
        flag = li.select_one("span[title]")
        lang = LANGS.get(flag.get("title")) if flag else None

        node = {
            "@type": "Article",
            "headline": strong.get_text(" ", strip=True),
            "url": title_link.get("href"),
            "author": PERSON,
        }
        if publisher:
            node["publisher"] = {"@type": "Organization", "name": publisher}
        if published:
            node["datePublished"] = published
        if lang:
            node["inLanguage"] = lang
        # a sibling link labelled "German" is a translation of the same piece
        german = next((a for a in li.select("a") if a.get_text(strip=True) == "German"), None)
        if german:
            node["workTranslation"] = {
                "@type": "Article",
                "url": german.get("href"),
                "inLanguage": "de",
            }
        blurb = li.select_one("span.text-muted")
        if blurb:
            node["description"] = text_of(blurb)
        items.append(node)
    return items


def build_open_source(soup):
    items = []
    for card in soup.select("div.card"):
        title_el = card.select_one(".card-title")
        if title_el is None:
            continue
        name = text_of(title_el, drop=[".badge"])
        repo = next(
            (a.get("href") for a in card.select("a[href]")
             if "github.com" in (a.get("href") or "") and "/stargazers" not in a.get("href")),
            None,
        )
        blurb = card.select_one("p.card-text")
        credits = " ".join(text_of(s) for s in card.select("small"))

        node = {"@type": "SoftwareSourceCode", "name": name}
        # The page states authorship explicitly; JabRef is flagged "(not by Simon)".
        # Never assert he authored something he only helped maintain.
        if re.search(r"not by Simon", credits, re.I):
            node["contributor"] = PERSON
        else:
            node["author"] = PERSON
        created = re.search(r"Created (?:by Simon )?in (\d{4})", credits)
        if created:
            node["dateCreated"] = created.group(1)
        if repo:
            node["codeRepository"] = repo
            node["url"] = repo
        if blurb:
            node["description"] = text_of(blurb)
        items.append(node)
    return items


PAGES = {
    "talks.html": dict(
        builder=build_talks,
        name="Talks — Simon Harrer",
        about=["Data Contracts", "Data Mesh", "Data Products", "GitOps", "Remote Mob Programming"],
    ),
    "podcasts.html": dict(
        builder=build_podcasts,
        name="Podcasts — Simon Harrer",
        about=["Data Contracts", "Data Mesh", "Data Governance", "Remote Mob Programming"],
    ),
    "articles.html": dict(
        builder=build_articles,
        name="Articles — Simon Harrer",
        about=["Data Products", "Data Contracts", "Data Mesh", "Remote Mob Programming"],
    ),
    "open-source.html": dict(
        builder=build_open_source,
        name="Open Source — Simon Harrer",
        about=["Data Contracts", "Data Products", "Open Source", "Remote Mob Programming"],
    ),
}

BLOCK = re.compile(
    r'(<script type="application/ld\+json">)(.*?)(</script>)', re.S
)


def render(path):
    cfg = PAGES[path.name]
    soup = BeautifulSoup(path.read_text(), "html.parser")
    description = soup.find("meta", attrs={"name": "description"})["content"]
    doc = collection_page(
        name=cfg["name"],
        url=f"{SITE}/{path.name}",
        description=description,
        about=cfg["about"],
        items=cfg["builder"](soup),
    )
    return json.dumps(doc, indent=2, ensure_ascii=False)


def rewrite(path, payload):
    src = path.read_text()
    if not BLOCK.search(src):
        raise SystemExit(f"{path.name}: no JSON-LD block to replace")
    body = "\n" + "\n".join("    " + ln for ln in payload.splitlines()) + "\n    "
    return BLOCK.sub(lambda m: m.group(1) + body + m.group(3), src, count=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if any page is stale")
    ap.add_argument("--print", dest="show", metavar="PAGE", help="print JSON-LD for one page")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    if args.show:
        print(render(root / args.show))
        return

    stale = []
    for name in PAGES:
        path = root / name
        updated = rewrite(path, render(path))
        if updated == path.read_text():
            print(f"{name}: unchanged")
            continue
        if args.check:
            stale.append(name)
            continue
        path.write_text(updated)
        count = json.loads(render(path))["mainEntity"]["numberOfItems"]
        print(f"{name}: wrote {count} items")

    if stale:
        print("stale (run without --check to fix): " + ", ".join(stale), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
