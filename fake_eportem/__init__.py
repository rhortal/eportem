"""A fake ePortem for development and tests (docs/refactor/PLAN.md, section 7).

It serves the parts of eportem.es the clock engine uses: the login form, the
clock dashboard and the clock endpoint, for several accounts at once, each with
its own activity IDs and clock state. Faults can be injected (server errors, a
maintenance page, dropped connections before or after recording, slow answers,
expired sessions, rejected logins). Every recorded clock event is kept, so tests
can check that each account was clocked exactly once.

The markup follows the real pages: the clock button attributes come from the
2026-11-16 captures (the same ones as tests/test_http_clock.py), and the
dashboard layout is what the Selenium XPaths in eportem/core/actions.py click.
`eportem.contract` checks the same structure on the real site.

    from fake_eportem import FakeEportem, Account
    with FakeEportem([Account("ALICE", "pw")]) as fake:
        fake.base_url  # http://127.0.0.1:<port>
"""
from fake_eportem.server import Account, FakeEportem, Fault

__all__ = ["Account", "Fault", "FakeEportem"]
