# simonharrer.com

Personal site of Dr. Simon Harrer. Hand-written HTML, Bootstrap 5 and a small
`album.css` on top, served by GitHub Pages from `main`. No build step, no
framework — the `.html` files in the repository root *are* the site.

Jekyll runs only because GitHub Pages runs it. Nothing has front matter, so it
copies the files verbatim. There is no `_posts`, `_layouts`, or `_includes`, and
no plugins.

## Generated files — regenerate before committing

Four things are derived from the pages rather than maintained alongside them, so
that a talk, episode, or paper exists in exactly one place. **Edit a page, then
run the generator that covers it.** All of them are idempotent and have a
`--check` mode; CI runs every `--check` on push and pull request.

| Run this | After editing | Produces |
|---|---|---|
| `python3 tools/build-jsonld.py` | `talks.html`, `podcasts.html`, `articles.html`, `open-source.html` | the `<script type="application/ld+json">` block in each of those pages |
| `python3 tools/build-llms-full.py` | any page | `llms-full.txt` |
| `python3 tools/build-sitemap.py` | adding or removing a page or a `papers/*.pdf` | `sitemap.xml` |
| `python3 tools/check-site.py` | any page | nothing — it only reports |

The safe habit is to run all four before committing:

```sh
python3 tools/build-jsonld.py && \
python3 tools/build-llms-full.py && \
python3 tools/build-sitemap.py && \
python3 tools/check-site.py
```

They need `beautifulsoup4`. Each also takes `--check` (exit 1 instead of
rewriting) and `--print`.

### Keeping sitemap.xml up to date

`sitemap.xml` is committed, not generated at deploy time. `jekyll-sitemap` used
to produce it, but it took `lastmod` from file mtime and GitHub Pages checks out
fresh on every build — so all sixteen URLs claimed the same build timestamp, and
`articles.html`, untouched since 2023, appeared to change on every unrelated
push. The plugin is gone; `tools/build-sitemap.py` reads `git log` per file
instead, so each page carries the date its content actually changed.

Consequences worth knowing:

- **Run it after adding or deleting a page**, or after adding a paper PDF. That
  is the change CI actually enforces — `--check` compares the URL set.
- **`lastmod` trails by one commit.** The sitemap is generated *before* the
  commit that contains it, so pages changed in that same commit pick up their
  new dates on the next regeneration. This is deliberate: a crawler hint that is
  a commit stale costs nothing, whereas making CI demand exact timestamps would
  fail every commit that touches a page. Do not "fix" this by comparing dates
  in `--check`.
- `404.html` is deliberately excluded — it is `noindex` and served for arbitrary
  URLs. The six `papers/*.pdf` are deliberately included; they are linked from
  `research.html` and worth finding on their own.
- If you ever want exact dates with no lag, the fix is to generate the sitemap
  in a Pages deploy workflow rather than committing it — not to change `--check`.

## Conventions

- **Structured data is generated, never hand-written**, for the four list pages
  above. `books.html`, `research.html`, `index.html`, and the rest carry
  hand-written JSON-LD; if you edit those, update the block in the same commit.
  `index.html` keeps its FAQ in two places — the visible markup and a mirrored
  `FAQPage` block — and both must be changed together.
- **Person data lives in one node**: `https://simonharrer.com/#person`, defined
  in `index.html`. Other pages reference it by `@id` rather than restating it.
- **Attribution matters.** `build-jsonld.py` emits `contributor` instead of
  `author` when a project's credit line says "(not by Simon)". That is how
  JabRef and the ODCS/ODPS card avoid claiming authorship. Keep the wording.
- **Dark mode is not optional.** `album.css` overrides Bootstrap variables under
  `prefers-color-scheme: dark`; check both schemes after any visual change.
- **Images**: ship a `.webp` beside the `.png`/`.jpg` and reference both through
  `<picture>`. Give `<img>` a class that constrains it — Bootstrap's
  `.card-img-top` sets only `width`, and an unconstrained `height` attribute
  will stretch the image.
- `legal.md` is the source for the hand-maintained `legal.html`; both are
  excluded from what Jekyll publishes, along with `tools/`.
