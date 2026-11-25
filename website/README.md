# CheckIn's public website

A static site that presents CheckIn while it is in final testing: what it is, how it
works, terms of use, privacy and a legal notice, in English (`/`) and Spanish (`/es/`).
No public sign-up (early access is asked for by email), no cookies, and nothing loaded from other sites in the source (fonts are the system's,
pictures are drawn in HTML and CSS). Visits are counted by Cloudflare Web Analytics,
which Cloudflare injects at its edge (the zone's automatic install), so the source
stays free of third-party scripts; the privacy page and footer say so. Keep the Pages
project's own Web Analytics toggle off while the zone injects it, or every visit is
counted twice.

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

Links are root-absolute and extensionless (`/privacy`, `/es/legal`, `/es/`), the way
Cloudflare Pages serves `privacy.html` and friends, and `404.html` / `es/404.html` are
the not-found pages (Pages serves the nearest one; without them it would answer every
unknown path with the home page and a 200). So opening the files from disk won't
follow links: preview with `npx wrangler pages dev website/dist`. Another host needs
the same two behaviours (`.html` optional, a 404 page).

## Hosting

The site runs on Cloudflare Pages at the product's main address, with the app on its
own hostname (D-027). Pages can't pull from Gitea, so each deploy uploads the built
folder:

```
python3 website/build.py
npx wrangler whoami                      # the account that owns the domain, not another one
npx wrangler pages deploy website/dist --project-name checkin --branch main
```

Setting it up again elsewhere: `npx wrangler pages project create checkin`, a first
deploy, then the custom domain in the Pages project (its DNS record becomes a CNAME to
the project's `pages.dev` address). The privacy page names
`HOSTING_PROVIDER` as the host that sees visitors' IP addresses and says we keep no
access logs of our own, which fits Pages; reword it if the site moves to a server
you run.

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

## Legal pages

The terms of use and privacy policy are a careful first draft, not legal advice. Have
them reviewed before the service takes users beyond early access, and check
`HOSTING_PROVIDER` against the host that serves the site.
