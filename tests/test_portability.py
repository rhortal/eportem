"""Keep install-specific values out of the repository (docs/refactor/PLAN.md,
section 6; decision D-012).

Fails when a tracked file holds an email address outside the example domains,
a private IPv4 address, or a URL whose host is not on ALLOWED_HOSTS. Names that
are personal to one maintainer (a host name, a home domain) can't be listed
here without publishing them, so they go in the untracked, gitignored
`.portability-denylist` (one per line, matched as whole words, any case).
"""
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DENYLIST_FILE = REPO / ".portability-denylist"

# The maintainer's own operational notes about their host; not shipped as docs.
SKIPPED_FILES = {"CLAUDE.md", "TODO.md", "docs/http-api-investigation.md", "LICENSE",
                 "tests/test_portability.py"}  # its own made-up bad examples

ALLOWED_HOSTS = {
    "eportem.es", "www.eportem.es",            # the site this project automates
    "slack.com", "hooks.slack.com",            # notification APIs
    "api.telegram.org",
    "www.google.com",                          # reCAPTCHA script, in docs
    "github.com",                              # the public repository
    "python-poetry.org", "pdm.fming.dev",      # comments in the stock Python .gitignore
    "fake-eportem", "glitchtip",               # service names in docker-compose.yml
    "localhost", "127.0.0.1", "0.0.0.0",  # noqa: S104 (a string, not a bind)
}
ALLOWED_HOST_SUFFIXES = (".example.com", ".example.org", ".example.net", ".test", ".invalid", ".localhost")
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "users.noreply.github.com"}

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
URL_HOST = re.compile(r"\bhttps?://(?:[^@/\s]+@)?([A-Za-z0-9.-]+)")  # skips user:password@
PRIVATE_IP = re.compile(r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b")


def tracked_text_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    for name in out.decode().split("\0"):
        if not name or name in SKIPPED_FILES:
            continue
        path = REPO / name
        try:
            yield name, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue  # binary, or deleted but not yet committed


def host_allowed(host):
    host = host.lower().rstrip(".")
    return (host in ALLOWED_HOSTS or host in {"example.com", "example.org", "example.net"}
            or host.endswith(ALLOWED_HOST_SUFFIXES))


def find_problems(name, text, denylist=()):
    problems = []
    for lineno, line in enumerate(text.splitlines(), 1):
        where = f"{name}:{lineno}"
        for m in EMAIL.finditer(line):
            domain = m.group(1).lower()
            if not any(domain == d or domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS):
                problems.append(f"{where}: email address {m.group(0)!r}")
        for m in URL_HOST.finditer(line):
            if not host_allowed(m.group(1)):
                problems.append(f"{where}: URL host {m.group(1)!r} is not on the allow-list")
        for m in PRIVATE_IP.finditer(line):
            problems.append(f"{where}: private IP address {m.group(0)!r}")
        for word in denylist:
            if re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", line, re.IGNORECASE):
                problems.append(f"{where}: {word!r} from .portability-denylist")
    return problems


def load_denylist():
    try:
        lines = DENYLIST_FILE.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [w.strip() for w in lines if w.strip() and not w.strip().startswith("#")]


class PortabilityTest(unittest.TestCase):
    def test_no_install_specific_values_in_tracked_files(self):
        denylist = load_denylist()
        problems = [p for name, text in tracked_text_files() for p in find_problems(name, text, denylist)]
        self.assertEqual(problems, [], "Install-specific values found; move them to settings or an "
                                       "untracked .env (docs/refactor/PLAN.md, section 6):\n  "
                                       + "\n  ".join(problems))

    def test_the_denylist_is_not_tracked(self):
        out = subprocess.run(["git", "ls-files", "--error-unmatch", DENYLIST_FILE.name],
                             cwd=REPO, capture_output=True)
        self.assertNotEqual(out.returncode, 0, ".portability-denylist must never be committed")


class FindProblemsTest(unittest.TestCase):
    """The scanner itself, on made-up input."""

    def test_flags_a_personal_email(self):
        self.assertEqual(len(find_problems("f", "mail me at someone@personal-domain.net")), 1)

    def test_allows_example_emails(self):
        self.assertEqual(find_problems("f", "admin@example.com, a@b.example.org"), [])

    def test_flags_an_unknown_url_host(self):
        self.assertIn("not on the allow-list", find_problems("f", "https://git.my-home.lan/repo")[0])

    def test_the_user_part_of_a_url_is_not_the_host(self):
        self.assertEqual(find_problems("f", "https://key@errors.example.com/1"), [])
        self.assertIn("URL host 'git.my-home.lan'", " ".join(find_problems("f", "https://key@git.my-home.lan/x")))

    def test_allows_known_and_example_hosts(self):
        text = "https://eportem.es/x https://hooks.slack.com/y https://eportem.example.com http://localhost:8080"
        self.assertEqual(find_problems("f", text), [])

    def test_flags_private_ips_but_not_versions(self):
        self.assertEqual(len(find_problems("f", "ssh 192.168.1.20 or 10.0.0.5")), 2)
        self.assertEqual(find_problems("f", "chromium 150.0.7871.181 and 172.32.0.1"), [])

    def test_denylist_matches_whole_words_in_any_case(self):
        self.assertEqual(len(find_problems("f", "deploy to MyBox now", ["mybox"])), 1)
        self.assertEqual(find_problems("f", "mybox2 and notmybox", ["mybox"]), [])

    def test_denylist_domain_matches_after_a_subdomain(self):
        self.assertEqual(len(find_problems("f", "git.myhome.example-dns.net", ["example-dns.net"])), 1)


if __name__ == "__main__":
    unittest.main()
