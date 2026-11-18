"""Every instance setting, in one place (docs/refactor/PLAN.md section 6, D-012).

Values come from, highest first: environment variables `EPORTEM_<NAME>`, then a
TOML file named by `EPORTEM_CONFIG_FILE` (keys are the lower-case names), then
the defaults below. Every secret can also be read from a file:
`EPORTEM_<NAME>_FILE=/run/secrets/...` (Docker and Kubernetes secrets).

This is the only module of the service that reads the environment. The field
descriptions are also the documentation: `.env.example` and the settings table
in README.md are generated from them (`python -m eportem config docs`), and a
test fails when they drift.

Per-user values (ePortem credentials, activity IDs, notification tokens,
timezone, schedule) are not settings: they live in the database.
"""
import os
import tomllib
import zoneinfo
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from eportem.core.schedule import jitter_problems
from eportem.core.templates import BUILTIN_TEMPLATES

ENV_PREFIX = "EPORTEM_"
CONFIG_FILE_VAR = "EPORTEM_CONFIG_FILE"

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
                                "https://eportem.example.com. Used in links and emails. Default: "
                                "http://localhost:<port>.")
    host: str = _f("0.0.0.0", "Server", "Address to listen on inside the container.")  # noqa: S104
    port: int = _f(8080, "Server", "Port to listen on (web UI, API, admin, health, metrics).", ge=1, le=65535)
    trusted_proxies: list[str] = _f([], "Server", "Reverse proxies whose X-Forwarded-* headers are believed "
                                    "(comma-separated IPs or CIDRs).")
    secure_cookies: bool | None = _f(None, "Server", "Send cookies only over HTTPS. Default: on when the "
                                     "public URL is https.")
    root_path: str = _f("", "Server", "Serve under a sub-path, e.g. /eportem, behind a proxy.")

    # --- Storage
    data_dir: Path = _f(Path("/data"), "Storage", "Where the database, backups and diagnostics live.")
    database_url: str | None = _f(None, "Storage", "SQLAlchemy URL. Default: SQLite in the data dir. "
                                  "Postgres (postgresql+psycopg://...) is needed for more than one replica.")
    secret_key: SecretStr = _f(..., "Storage", "Required. Encrypts stored credentials and tokens (a Fernet "
                               "key: `python -m eportem config new-key`). Losing it means everyone re-enters "
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

    # --- Defaults for new users
    default_timezone: str = _f("Europe/Madrid", "Defaults for new users", "Time zone for new users.")
    default_locale: Literal["en", "es"] = _f("es", "Defaults for new users", "Language for new users.")
    default_holiday_country: str | None = _f("ES", "Defaults for new users", "Country for public holidays "
                                             "(ISO code); empty for none.")
    default_holiday_region: str | None = _f(None, "Defaults for new users", "Region for public holidays, "
                                            "e.g. MD (Madrid), CT (Catalonia).")
    default_template: str = _f("european-9-18", "Defaults for new users", "Working-day template for new "
                               "users (a built-in key).")
    default_jitter_before_minutes: int = _f(5, "Defaults for new users", "Random offset for new users: "
                                            "start up to this many minutes before an action's time. Each "
                                            "person changes their own in their profile.", ge=0, le=60)
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
    heartbeat_url: str | None = _f(None, "Observability", "Pinged every minute while the scheduler is "
                                   "healthy (healthchecks.io style), so a dead instance gets noticed.")
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
                                 "`python -m eportem config new-key`") from e
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
        return self.database_url or f"sqlite:///{self.data_dir / 'eportem.db'}"

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


def _read_secret_files(environ):
    """{field: value} for EPORTEM_<SECRET>_FILE variables."""
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
    environ = dict(os.environ if environ is None else environ)
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
    environ = dict(os.environ if environ is None else environ)
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
    lines = ["# ePortem service settings. Copy to .env and fill in; every line is optional",
             "# except EPORTEM_SECRET_KEY. Generated by `python -m eportem config docs`:",
             "# don't edit by hand. Secrets can also come from files: EPORTEM_<NAME>_FILE.",
             "# Settings can also live in a TOML file named by EPORTEM_CONFIG_FILE.", ""]
    for group, fields in _by_group():
        lines.append(f"# --- {group}")
        for name, f in fields:
            lines.append(f"# {f.description}")
            lines.append(f"{env_name(name)}={_default_text(f)}")
        lines.append("")
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
