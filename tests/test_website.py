"""The public website builds, and keeps its promises: no placeholders left, the
ePortem disclaimer on every page, nothing loaded from other sites, and every
internal link pointing at a page that exists."""
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "website"
spec = importlib.util.spec_from_file_location("website_build", SITE / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

LINK = re.compile(r'(?:href|src)="([^"]+)"')


class TestWebsite(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.values = build.read_env(SITE / "site.env.example")
        self.pages = build.build(self.values, dist=self.tmp / "dist")
        self.dist = self.tmp / "dist"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def html(self, name):
        return (self.dist / name).read_text(encoding="utf-8")

    def test_every_page_in_every_language(self):
        self.assertEqual(list(build.LANGUAGES), ["en", "es", "ca"])
        for code, (folder, _) in build.LANGUAGES.items():
            for name in ("index.html", "terms.html", "privacy.html", "legal.html", "agents.html", "404.html"):
                self.assertIn(f"{folder}{name}", self.pages)
                self.assertIn(f'<html lang="{code}">', self.html(f"{folder}{name}"))
        per_language = {code: sorted(p.name for p in (SITE / "src" / folder).glob("[!_]*.html"))
                        for code, (folder, _) in build.LANGUAGES.items()}
        self.assertEqual(len({tuple(v) for v in per_language.values()}), 1, per_language)

    def test_every_page_links_to_itself_in_the_other_languages(self):
        site = self.values["SITE_URL"]
        for code, (folder, _) in build.LANGUAGES.items():
            html = self.html(f"{folder}privacy.html")
            for other, (other_folder, name) in build.LANGUAGES.items():
                self.assertIn(f'<link rel="alternate" hreflang="{other}" href="{site}/{other_folder}privacy">', html)
                if other != code:
                    self.assertIn(f'href="/{other_folder}privacy" hreflang="{other}" lang="{other}">{name}</a>', html)
            self.assertIn('hreflang="x-default" href="' + site + '/privacy"', html)

    def test_nothing_left_unfilled(self):
        for name in self.pages:
            html = self.html(name)
            self.assertNotIn("{{", html, name)
            self.assertNotIn("<!--include:", html, name)
            self.assertNotIn("<!--if:", html, name)
            self.assertNotIn("<!--", html, f"{name}: source comments (they name repository files) must not ship")
            self.assertIn(self.values["CONTACT_EMAIL"], html, name)

    def test_the_eportem_disclaimer_is_on_every_page(self):
        for name in self.pages:
            html = re.sub(r"\s+", " ", self.html(name))
            said = ("not affiliated with", "no está afiliado", "no està afiliat")
            self.assertTrue(any(s in html for s in said), name)

    def test_loads_nothing_from_other_sites(self):
        for name in self.pages:
            html = self.html(name)
            for tag in re.findall(r"<(?:script|link|img|iframe|source|video|audio)\b[^>]*>", html):
                if re.search(r'rel="(?:canonical|alternate)"', tag):
                    continue  # the site's own address, not something loaded
                self.assertNotRegex(tag, r'(?:src|href)="(?:https?:)?//', f"{name}: {tag}")
            self.assertNotIn("@import", html)
        self.assertNotRegex((self.dist / "assets/site.css").read_text(), r"url\(\s*['\"]?(?:https?:)?//")

    def served_file(self, url):
        """The file Cloudflare Pages serves for a root-absolute URL: "/" and "/es/"
        are index.html, "/terms" is terms.html, assets keep their names."""
        path = url.split("#")[0].lstrip("/")
        if path == "" or path.endswith("/"):
            path += "index.html"
        elif "." not in Path(path).name:
            path += ".html"
        return self.dist / path

    def internal_links(self, name):
        site = self.values["SITE_URL"]
        for target in LINK.findall(self.html(name)):
            if target.startswith(site):
                yield target[len(site):] or "/"
            elif not target.startswith(("http://", "https://", "mailto:", "#")):
                yield target

    def test_internal_links_resolve(self):
        for name in self.pages:
            for url in self.internal_links(name):
                self.assertTrue(url.startswith("/"), f"{name}: {url} is not root-absolute")
                self.assertTrue(self.served_file(url).is_file(), f"{name}: {url}")

    def test_links_and_canonicals_have_no_html_extension(self):
        # Pages answers /x.html with a redirect to /x, so link to /x directly.
        for name in self.pages:
            for url in self.internal_links(name):
                self.assertNotRegex(url.split("#")[0], r"\.html$", f"{name}: {url}")

    def test_a_not_found_page_in_each_language(self):
        for code, (folder, _) in build.LANGUAGES.items():
            html = self.html(f"{folder}404.html")
            self.assertIn('name="robots" content="noindex"', html)
            self.assertNotIn('rel="canonical"', html)
            for other, (home, _) in build.LANGUAGES.items():
                if other != code:  # the language links go to the other home pages
                    self.assertIn(f'href="/{home}" hreflang="{other}"', html)

    def test_every_picture_is_catalogued(self):
        catalogue = (SITE / "VISUALS.md").read_text(encoding="utf-8")
        for partial in (SITE / "src").glob("_v-*.en.html"):
            text = partial.read_text(encoding="utf-8")
            match = re.match(r"<!-- visual: ([\w-]+)\. Source: ", text)
            self.assertIsNotNone(match, f"{partial.name} has no visual/source comment")
            self.assertIn(f"`{match.group(1)}`", catalogue, partial.name)
            self.assertIn(partial.name.replace(".en.html", ".*.html"), catalogue)
            for code in build.LANGUAGES:
                self.assertTrue(partial.with_name(partial.name.replace(".en.", f".{code}.")).is_file(), code)

    def test_refuses_to_build_without_a_required_value(self):
        with self.assertRaisesRegex(build.BuildError, "OWNER_NAME"):
            build.build(dict(self.values, OWNER_NAME=""), dist=self.tmp / "x")

    def test_optional_blocks_appear_only_with_a_value(self):
        self.assertNotIn("NIF", self.html("es/legal.html"))
        build.build(dict(self.values, OWNER_TAX_ID="00000000T"), dist=self.tmp / "y")
        self.assertIn("00000000T", (self.tmp / "y/es/legal.html").read_text(encoding="utf-8"))

    def test_a_missing_include_fails(self):
        with self.assertRaisesRegex(build.BuildError, "include not found"):
            build.render("<!--include:_nope.html-->", {}, SITE / "src")

    def test_main_builds_the_example(self):
        self.assertEqual(build.main(["--example", "--out", str(self.tmp / "z")]), 0)

    def test_the_skill_for_agents_is_presented_but_never_published(self):
        # The skill is only for people with an account: the app serves it (D-028).
        self.assertFalse((self.dist / "skill").exists())
        for folder, _ in build.LANGUAGES.values():
            page, home, link = f"{folder}agents.html", f"{folder}index.html", f'href="/{folder}agents"'
            html = self.html(page)
            for leak in ("install.sh", "checkin.zip", "curl ", "/skill/"):
                self.assertNotIn(leak, html, f"{page}: {leak}")
            self.assertIn('id="agents"', self.html(home))
            self.assertIn(link, self.html(home))
