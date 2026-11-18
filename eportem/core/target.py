"""The ePortem site being automated: every URL is derived from one base URL,
so the service can point at the real site or at the fake used in tests."""
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://eportem.es"
LOGIN_PATH = "/Usuario/Login"


@dataclass(frozen=True)
class Target:
    base_url: str = DEFAULT_BASE_URL

    def __post_init__(self):
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    @property
    def login_url(self):
        return f"{self.base_url}{LOGIN_PATH}?ReturnUrl=%2faplicaciones"

    @property
    def dashboard_url(self):
        return f"{self.base_url}/aplicaciones/e-portem/registro/"

    @property
    def clock_url(self):
        return f"{self.dashboard_url}reghorario.cshtml"

    @staticmethod
    def is_login_page(url):
        return LOGIN_PATH in (url or "")
