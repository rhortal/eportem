"""Build the public website (a static placeholder) into website/dist/.

    python website/build.py            # values from website/site.env
    python website/build.py --example  # values from website/site.env.example, for a preview

The pages in website/src/ hold {{KEY}} placeholders for the values that name the
person behind the site (name, contact email, address). Those are personal, so
they live in the untracked website/site.env and never in the repository; the
build refuses to run while a required one is missing or a placeholder is left.

Other markers:
  <!--include:_footer.en.html-->   the partial's text (it may hold placeholders too)
  <!--if:KEY--> ... <!--endif:KEY-->  kept only when KEY has a value
  {{ROOT}}   the site root, "/": links are root-absolute and extensionless
             ("/privacy", "/es/"), as Cloudflare Pages serves them, so a 404 page
             works at any depth
  {{ALT}}    the same page in the other language (the other home page for 404.html)
Standard library only: the site has no build dependencies.
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC, DIST = HERE / "src", HERE / "dist"
REQUIRED = ("SITE_URL", "OWNER_NAME", "CONTACT_EMAIL", "HOSTING_PROVIDER")
OPTIONAL = ("OWNER_TAX_ID", "OWNER_ADDRESS")
LANGS = {"": "es/", "es/": ""}  # page directory -> the other language's directory

PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
INCLUDE = re.compile(r"<!--include:\s*([^>]*?)\s*-->")
IF_BLOCK = re.compile(r"<!--if:([A-Z_]+)-->(.*?)<!--endif:\1-->", re.S)


class BuildError(Exception):
    pass


def read_env(path):
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _partial(src_dir, name):
    path = src_dir / name
    if not re.fullmatch(r"_[\w.-]+\.html", name) or not path.is_file():
        raise BuildError(f"include not found: {name}")
    return path.read_text(encoding="utf-8")


def render(text, values, src_dir):
    for _ in range(5):  # partials may include partials
        text = INCLUDE.sub(lambda m: _partial(src_dir, m.group(1)), text)
    if INCLUDE.search(text):
        raise BuildError("includes nested too deep")
    text = IF_BLOCK.sub(lambda m: m.group(2) if values.get(m.group(1)) else "", text)
    left = set()

    def fill(match):
        key = match.group(1)
        if values.get(key) or (key in values and key in ("ROOT",)):
            return values[key]
        left.add(key)
        return match.group(0)

    text = PLACEHOLDER.sub(fill, text)
    if left:
        raise BuildError(f"no value for {', '.join(sorted(left))}")
    return text


def page_url(page_dir, file_name):
    """The address a page is served at: "/es/" for es/index.html, "/terms" for
    terms.html. A 404 page links to its language's home page instead."""
    stem = file_name.removesuffix(".html")
    return f"/{page_dir}" + ("" if stem in ("index", "404") else stem)


def build(values, src=SRC, dist=DIST):
    missing = [k for k in REQUIRED if not values.get(k)]
    if missing:
        raise BuildError(f"missing in site.env: {', '.join(missing)}")
    values = dict(values, SITE_URL=values["SITE_URL"].rstrip("/"))
    if dist.exists():
        shutil.rmtree(dist)
    shutil.copytree(src / "assets", dist / "assets")
    pages = []
    for page_dir, other in LANGS.items():
        for page in sorted((src / page_dir).glob("*.html")):
            if page.name.startswith("_"):
                continue
            name = f"{page_dir}{page.name}"
            page_values = dict(values, ROOT="/", ALT=page_url(other, page.name), PAGE=page.name)
            try:
                html = render(page.read_text(encoding="utf-8"), page_values, src)
            except BuildError as e:
                raise BuildError(f"{name}: {e}") from None
            out = dist / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")
            pages.append(name)
    return pages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--example", action="store_true", help="use site.env.example (a preview)")
    parser.add_argument("--out", type=Path, default=DIST)
    args = parser.parse_args(argv)
    env = HERE / ("site.env.example" if args.example else "site.env")
    if not env.exists():
        print(f"{env.name} not found: copy site.env.example to site.env and fill it in", file=sys.stderr)
        return 2
    try:
        pages = build(read_env(env), dist=args.out)
    except BuildError as e:
        print(f"build failed: {e}", file=sys.stderr)
        return 1
    print(f"Built {len(pages)} pages into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
