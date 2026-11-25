"""Every instance setting, in one place (docs/refactor/PLAN.md section 6, D-012).

Values come from, highest first: environment variables `CHECKIN_<NAME>`, then a
TOML file named by `CHECKIN_CONFIG_FILE` (keys are the lower-case names), then
the defaults below. Every secret can also be read from a file:
`CHECKIN_<NAME>_FILE=/run/secrets/...` (Docker and Kubernetes secrets).

The project was called ePortem until 2026-11-21 (D-025). The old names
`EPORTEM_<NAME>`, `EPORTEM_<NAME>_FILE` and `EPORTEM_CONFIG_FILE` are still read
when the new one isn't set, with a warning naming the variable to rename.

This is the only module of the service that reads the environment. The field
descriptions are also the documentation: `.env.example` and the settings table
in README.md are generated from them (`python -m checkin config docs`), and a
test fails when they drift.

Per-user values (ePortem credentials, activity IDs, notification tokens,
timezone, schedule) are not settings: they live in the database.
"""
import logging
import os
import tomllib
import zoneinfo
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from checkin.core.schedule import jitter_problems
from checkin.core.templates import BUILTIN_TEMPLATES
from checkin.i18n import LANGUAGES

ENV_PREFIX = "CHECKIN_"
CONFIG_FILE_VAR = "CHECKIN_CONFIG_FILE"
OLD_ENV_PREFIX = "EPORTEM_"  # before the rename to CheckIn (D-025)

log = logging.getLogger(__name__)

# Groups for the docs, in order.
GROUPS = ("Server", "Storage", "Target site", "Defaults for new users", "Scheduling", "Accounts",
          "Email", "Observability")


def _f(default, group, description, **kw):
    return Field(default, description=description, json_schema_extra={"group": group}, **kw)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", validate_default=True)

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings,
                                   file_secret_settings):
        # load_settings() gathers every source itself, from the environment it is
        # given; nothing is read behind its back.
        return (init_settings,)

    # --- Server
    public_url: str | None = _f(None, "Server", "The address people use to reach this instance, e.g. "
                                "https://checkin.example.com. Used in links and emails. Default: "
                                "http://localhost:<port>.")
    host: str = _f("0.0.0.0", "Server", "Address to listen on inside the container.")  # noqa: S104
    port: int = _f(8080, "Server", "Port to listen on (web UI, API, admin, health, metrics).", ge=1, le=65535)
    trusted_proxies: list[str] = _f([], "Server", "Reverse proxies whose X-Forwarded-* headers are believed "
                                    "(comma-separated IPs or CIDRs).")
    secure_cookies: bool | None = _f(None, "Server", "Send cookies only over HTTPS. Default: on when the "
                                     "public URL is https.")
    root_path: str = _f("", "Server", "Serve under a sub-path, e.g. /checkin, behind a proxy.")

    # --- Storage
    data_dir: Path = _f(Path("/data"), "Storage", "Where the database, backups and diagnostics live.")
    database_url: str | None = _f(None, "Storage", "SQLAlchemy URL. Default: SQLite in the data dir. "
                                  "Postgres (postgresql+psycopg://...) is needed for more than one replica.")
    secret_key: SecretStr = _f(..., "Storage", "Required. Encrypts stored credentials and tokens (a Fernet "
                               "key: `python -m checkin config new-key`). Losing it means everyone re-enters "
                               "their credentials.")
    old_secret_keys: list[SecretStr] = _f([], "Storage", "Previous secret keys, still accepted for "
                                          "reading while rotating (comma-separated).")

    # --- Target site
    target_url: str = _f("https://eportem.es", "Target site", "The ePortem site to automate. Point it at "
                         "the fake ePortem for trying things out.")
    browser_user_agent: str | None = _f(None, "Target site", "Override the browser's User-Agent. Default: "
                                        "a desktop Chrome matching the installed version.")
    chromium_path: str | None = _f(None, "Target site", "Chromium binary, if not on the PATH.")
    chromedriver_path: str | None = _f(None, "Target site", "chromedriver binary, if not on the PATH.")
    browser_concurrency: int = _f(1, "Target site", "Browser logins allowed at the same time.", ge=1, le=16)
    headless: bool = _f(True, "Target site", "Run the browser without a window.")
    browser_sandbox: bool = _f(True, "Target site", "Use Chromium's own sandbox. The Docker image turns it off "
                               "(it can't start as a non-root user there; the container isolates it instead).")

    # --- Defaults for new users
    default_timezone: str = _f("Europe/Madrid", "Defaults for new users", "Time zone for new users.")
    default_locale: str = _f("es", "Defaults for new users", "Language for new users: a code with a catalogue "
                              "in checkin/locales (en, es, ca...).")
    default_holiday_country: str | None = _f("ES", "Defaults for new users", "Country for public holidays "
                                             "(ISO code); empty for none.")
    default_holiday_region: str | None = _f(None, "Defaults for new users", "Region for public holidays, "
                                            "e.g. MD (Madrid), CT (Catalonia).")
    default_template: str = _f("european-9-18", "Defaults for new users", "Working-day template for new "
                               "users (a built-in key).")
    default_jitter_before_minutes: int = _f(5, "Defaults for new users", "Random offset for new users: "
                                            "start up to this many minutes before an action's time. The "
                                            "clock-in and clock-out never fall inside the working day: "
                                            "they go only before the start or after the stop, spread over "
                                            "before + after minutes. Each person changes their own in "
                                            "their profile.", ge=0, le=60)
    default_jitter_after_minutes: int = _f(4, "Defaults for new users", "Random offset for new users: "
                                           "start up to this many minutes after an action's time.", ge=0, le=60)

    # --- Scheduling
    window_minutes: int = _f(15, "Scheduling", "An action may run this many minutes either side of its "
                             "time, never later. Everyone's random offset must fit inside it.", ge=1, le=60)
    verify_after_minutes: int = _f(40, "Scheduling", "The end-of-day check runs this long after a user's "
                                   "last action.", ge=1, le=240)
    dry_run: bool = _f(False, "Scheduling", "Plan and log, but never send a clock action.")

    # --- Accounts
    registration: Literal["closed", "invite", "open"] = _f("closed", "Accounts", "Who can create an "
                                                           "account: closed (admins only), invite, open.")
    require_email_verification: bool = _f(True, "Accounts", "New accounts must confirm their email.")
    admin_username: str | None = _f(None, "Accounts", "Creates this admin on first start, if no admin exists.")
    admin_email: str | None = _f(None, "Accounts", "Email of that first admin.")
    admin_password: SecretStr | None = _f(None, "Accounts", "Password of that first admin.")

    # --- Email
    smtp_host: str | None = _f(None, "Email", "SMTP server for verification, password reset and alerts. "
                               "Empty: no email.")
    smtp_port: int = _f(587, "Email", "SMTP port.", ge=1, le=65535)
    smtp_security: Literal["starttls", "tls", "none"] = _f("starttls", "Email", "starttls, tls (implicit, "
                                                           "usually port 465) or none.")
    smtp_username: str | None = _f(None, "Email", "SMTP login.")
    smtp_password: SecretStr | None = _f(None, "Email", "SMTP password.")
    smtp_from: str | None = _f(None, "Email", "From address for the emails this instance sends.")

    # --- Observability
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = _f("INFO", "Observability", "Log level.")
    log_format: Literal["json", "text"] = _f("json", "Observability", "Log lines as JSON or plain text.")
    metrics_token: SecretStr | None = _f(None, "Observability", "Bearer token required on /metrics. "
                                         "Empty: /metrics is off.")
    sentry_dsn: SecretStr | None = _f(None, "Observability", "Report errors to Sentry or GlitchTip. "
                                      "Empty: off.")
    sentry_environment: str = _f("production", "Observability", "Environment name in error reports.")
    heartbeat_url: str | None = _f(None, "Observability", "POSTed to every minute while the scheduler is "
                                   "healthy (a GlitchTip heartbeat monitor, healthchecks.io...), so a dead "
                                   "instance gets noticed.")
    admin_alert_channel: str | None = _f(None, "Observability", "Where admin alerts go, e.g. "
                                         "telegram:<chat id> or slack:<channel id>.")

    @field_validator("trusted_proxies", "old_secret_keys", mode="before")
    @classmethod
    def _comma_list(cls, value):
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @field_validator("public_url", "database_url", "smtp_host", "default_holiday_country",
                     "default_holiday_region", "heartbeat_url", "admin_alert_channel", mode="before")
    @classmethod
    def _empty_is_none(cls, value):
        return None if value == "" else value

    @field_validator("default_timezone")
    @classmethod
    def _timezone(cls, value):
        try:
            zoneinfo.ZoneInfo(value)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown time zone {value!r}") from e
        return value

    @field_validator("default_locale")
    @classmethod
    def _locale(cls, value):
        if value not in LANGUAGES:
            raise ValueError(f"must be one of {', '.join(LANGUAGES)}")
        return value

    @field_validator("default_template")
    @classmethod
    def _template(cls, value):
        if value not in BUILTIN_TEMPLATES:
            raise ValueError(f"must be one of {', '.join(BUILTIN_TEMPLATES)}")
        return value

    @field_validator("target_url", "public_url")
    @classmethod
    def _url(cls, value):
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value.rstrip("/") if value else value

    @field_validator("secret_key", "old_secret_keys")
    @classmethod
    def _fernet_key(cls, value):
        from cryptography.fernet import Fernet
        for key in (value if isinstance(value, list) else [value]):
            try:
                Fernet(key.get_secret_value())
            except Exception as e:
                raise ValueError("must be a Fernet key (32 url-safe base64 bytes); make one with "
                                 "`python -m checkin config new-key`") from e
        return value

    @model_validator(mode="after")
    def _consistency(self):
        problems = []
        problems += [f"default {p}" for p in jitter_problems(
            self.default_jitter_before_minutes, self.default_jitter_after_minutes, self.window_minutes)]
        if self.smtp_host and not self.smtp_from:
            problems.append("smtp_from is required when smtp_host is set")
        if self.require_email_verification and self.registration == "open" and not self.smtp_host:
            problems.append("open registration with email verification needs smtp_host")
        if bool(self.admin_username) != bool(self.admin_password):
            problems.append("admin_username and admin_password go together")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    # --- derived values
    @property
    def effective_public_url(self):
        return self.public_url or f"http://localhost:{self.port}"

    @property
    def effective_database_url(self):
        if self.database_url:
            return self.database_url
        path = self.data_dir / "checkin.db"
        old = self.data_dir / "eportem.db"  # the default before the rename (D-025)
        if not path.exists() and old.exists():
            path = old
        return f"sqlite:///{path}"

    @property
    def effective_secure_cookies(self):
        if self.secure_cookies is not None:
            return self.secure_cookies
        return self.effective_public_url.startswith("https://")


SECRET_FIELDS = tuple(name for name, f in Settings.model_fields.items()
                      if "SecretStr" in str(f.annotation))


class SettingsError(Exception):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def env_name(field):
    return f"{ENV_PREFIX}{field.upper()}"


def _known_names():
    names = {CONFIG_FILE_VAR}
    for field in Settings.model_fields:
        names.add(env_name(field))
        if field in SECRET_FIELDS:
            names.add(env_name(field) + "_FILE")
    return names


def with_old_names(environ, warn=False):
    """A copy of `environ` where each setting only set under its pre-rename
    name (EPORTEM_...) is also set under its CHECKIN_ name. A new name always
    wins. With `warn`, logs one warning per old name in use."""
    environ = dict(environ)
    for new in sorted(_known_names()):
        old = OLD_ENV_PREFIX + new.removeprefix(ENV_PREFIX)
        if old in environ and new not in environ:
            environ[new] = environ[old]
            if warn:
                log.warning("%s is the old name of %s (the project is now CheckIn); rename it", old, new)
    return environ


def _read_secret_files(environ):
    """{field: value} for CHECKIN_<SECRET>_FILE variables."""
    values, problems = {}, []
    for name in SECRET_FIELDS:
        file_var = env_name(name) + "_FILE"
        path = environ.get(file_var)
        if not path:
            continue
        if environ.get(env_name(name)):
            problems.append(f"{env_name(name)}: set either it or {file_var}, not both")
            continue
        try:
            values[name] = Path(path).read_text(encoding="utf-8").strip()
        except OSError as e:
            problems.append(f"{file_var}: cannot read {path} ({e.strerror or e})")
    return values, problems


def _read_config_file(environ):
    path = environ.get(CONFIG_FILE_VAR)
    if not path:
        return {}, [], None
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        return {}, [f"{CONFIG_FILE_VAR}: cannot read {path} ({e.strerror or e})"], path
    except tomllib.TOMLDecodeError as e:
        return {}, [f"{CONFIG_FILE_VAR}: {path} is not valid TOML ({e})"], path
    unknown = sorted(set(data) - set(Settings.model_fields))
    problems = [f"{CONFIG_FILE_VAR}: unknown setting {k!r} in {path}" for k in unknown]
    return {k: v for k, v in data.items() if k in Settings.model_fields}, problems, path


def load_settings(environ=None):
    """Read, check and return the settings. Raises SettingsError listing every
    problem (by its environment variable name) so a bad deploy fails at start-up
    with a readable message."""
    environ = with_old_names(os.environ if environ is None else environ, warn=True)
    secrets_from_files, problems = _read_secret_files(environ)
    from_config, config_problems, _ = _read_config_file(environ)
    problems += config_problems
    if problems:
        raise SettingsError(problems)
    # Priority: secret files and env > config file > defaults.
    values = dict(from_config)
    for name in Settings.model_fields:
        if env_name(name) in environ:
            values[name] = environ[env_name(name)]
    values.update(secrets_from_files)
    try:
        return Settings(**values)
    except ValidationError as e:
        raise SettingsError(_describe_validation(e)) from None


def _describe_validation(error):
    problems = []
    for err in error.errors():
        loc = [str(x) for x in err["loc"] if not isinstance(x, int)]
        name = env_name(loc[0]) if loc else "settings"
        message = err["msg"].removeprefix("Value error, ")
        if err["type"] == "missing":
            message = "required"
        problems.append(f"{name}: {message}")
    return problems


def describe(settings, environ=None):
    """[(env name, value shown, source)] with secrets hidden, for `config show`."""
    environ = with_old_names(os.environ if environ is None else environ)
    from_config, _, config_path = _read_config_file(environ)
    rows = []
    for name in Settings.model_fields:
        value = getattr(settings, name)
        if name in SECRET_FIELDS:
            shown = "(set)" if value else "(not set)"
        elif isinstance(value, list):
            shown = ", ".join(str(v) for v in value) or "(none)"
        else:
            shown = "(not set)" if value is None else str(value)
        if environ.get(env_name(name) + "_FILE"):
            source = f"file {environ[env_name(name) + '_FILE']}"
        elif env_name(name) in environ:
            source = "environment"
        elif name in from_config:
            source = f"config file {config_path}"
        else:
            source = "default"
        rows.append((env_name(name), shown, source))
    return rows


# --- generated documentation ---------------------------------------------------
def _default_text(field):
    if field.is_required():
        return ""
    d = field.default
    if d is None or d == [] or d == "":
        return ""
    if isinstance(d, bool):
        return "true" if d else "false"
    return str(d)


def _by_group():
    for group in GROUPS:
        yield group, [(n, f) for n, f in Settings.model_fields.items()
                      if (f.json_schema_extra or {}).get("group") == group]


def env_example():
    """The text of .env.example."""
    lines = ["# CheckIn service settings. Copy to .env and fill in; every line is optional",
             "# except CHECKIN_SECRET_KEY. Generated by `python -m checkin config docs`:",
             "# don't edit by hand. Secrets can also come from files: CHECKIN_<NAME>_FILE.",
             "# Settings can also live in a TOML file named by CHECKIN_CONFIG_FILE.", ""]
    for group, fields in _by_group():
        lines.append(f"# --- {group}")
        for name, f in fields:
            lines.append(f"# {f.description}")
            lines.append(f"{env_name(name)}={_default_text(f)}")
        lines.append("")
    lines += ["# --- Docker Compose only (not read by the service)",
              "# Where the published port listens on the host. The default keeps it local;",
              "# put a reverse proxy in front for HTTPS, or use 0.0.0.0:8080 on a trusted LAN.",
              "CHECKIN_PUBLISH=127.0.0.1:8080", "",
              "# --- GlitchTip (docker compose --profile errors; not read by the service)",
              "# GLITCHTIP_SECRET_KEY: `openssl rand -hex 32`. GLITCHTIP_DOMAIN: its public address.",
              "GLITCHTIP_SECRET_KEY=", "GLITCHTIP_DOMAIN=http://127.0.0.1:8000", "GLITCHTIP_PUBLISH=127.0.0.1:8000",
              "GLITCHTIP_FROM_EMAIL=glitchtip@example.com", "GLITCHTIP_EMAIL_URL=consolemail://", ""]
    return "\n".join(lines)


def markdown_table():
    """The settings table for README.md."""
    rows = ["| Setting | Default | What it does |", "|---|---|---|"]
    for group, fields in _by_group():
        rows.append(f"| **{group}** | | |")
        for name, f in fields:
            default = _default_text(f)
            secret = " Secret: also `_FILE`." if name in SECRET_FIELDS else ""
            rows.append(f"| `{env_name(name)}` | {f'`{default}`' if default else ''} | "
                        f"{f.description.replace('|', '/')}{secret} |")
    return "\n".join(rows)
