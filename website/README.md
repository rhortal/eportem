# CheckIn's public website

A static placeholder that presents CheckIn: what it is, how it works, terms of use,
privacy and a legal notice, in English (`/`) and Spanish (`/es/`). No sign-up, no
cookies, no analytics, and nothing loaded from other sites (fonts are the system's,
pictures are drawn in HTML and CSS).

## Build

```
cp website/site.env.example website/site.env   # then fill in your values (untracked)
python3 website/build.py                       # writes website/dist/
python3 website/build.py --example             # a preview with made-up values
```

`site.env` holds the values that name the person behind the site (name, contact email,
site address, and later a tax ID and address). They stay out of the repository, like
every personal value (the portability test enforces it), and the build refuses to run
while one is missing. Standard library only.

Publish `website/dist/` on any static host or web server.

## Hosting

The site is static, so any static host works. The plan (D-027) is Cloudflare Pages
for the site at the product's main address, with the app on its own hostname. Pages
can't pull from Gitea, so publish the built folder directly:

```
python3 website/build.py
npx wrangler whoami                      # the account that owns the domain, not another one
npx wrangler pages project create checkin
npx wrangler pages deploy website/dist --project-name checkin
```

Then add the custom domain in the Pages project. Before publishing, make the privacy
page match the host: it describes server logs kept for `LOG_RETENTION_DAYS` days,
which fits a server you run, not Pages (where you keep no logs and Cloudflare is
the host).

## Source

- `src/*.html` and `src/es/*.html`: the pages (`index`, `terms`, `privacy`, `legal`),
  the same names in both languages.
- `src/_*.html`: partials (header, footer, logo, and one per picture, `_v-*.html`),
  pulled in with `<!--include:_name.html-->`.
- `src/assets/`: the stylesheet and the favicon.
- Placeholders: `{{OWNER_NAME}}` and the others from `site.env`; `<!--if:KEY-->...
  <!--endif:KEY-->` for optional ones; `{{ROOT}}` and `{{ALT}}` (the same page in the
  other language) are set by the build.

## Pictures

Every picture is a drawing, not a screenshot. [`VISUALS.md`](VISUALS.md) lists each one
with the product screen and files it is drawn from, so they can be redrawn when the UI
changes. Pictures of ePortem are generic illustrations, never its real design.

## Before publishing for real

The terms of use and privacy policy are a careful first draft, not legal advice. Have
them reviewed before anyone uses the service, and check `LOG_RETENTION_DAYS` and
`NETWORK_PROVIDER` against the host that serves the site.
