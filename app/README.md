# Companion app frontend

The web app that `fo serve` serves. Node is needed only to change it: the
production build is committed under `src/fo/data/app/` and ships in the wheel,
so installing family-office from a git tag gives a working UI without Node.

## Build

```sh
cd app
npm ci
npm run build
```

The build writes straight into `src/fo/data/app/`, emptying it first, and is
reproducible: CI rebuilds it and fails if the committed copy differs. Commit the
rebuilt directory with every change under `app/`. Use the Node version in
`.nvmrc`.

## Develop

Start `fo serve` from an office, open the link it prints once (that sets the
session cookie for 127.0.0.1), then run `npm run dev` and open
http://127.0.0.1:5173. The dev server proxies `/api` to http://127.0.0.1:4790,
or to `FO_SERVE_URL`, and presents itself with that origin so `fo serve`'s Host
and Origin checks pass. Never point it at a server you do not own.

Numbers arrive from the API as decimal strings and are parsed once in
`src/api/office.ts`. Unknown values stay `null` and render as "unknown", never 0.

## Components and licenses

Components are shadcn/ui (MIT) on Base UI (MIT), added with the shadcn CLI
(`components.json`, style `base-nova`) and restyled to follow the reviewed
prototype's layout. coss ui is used as a visual reference only, not as code: its
source repository (cosscom/coss) is licensed AGPL-3.0, its registry items declare
no other terms, and this package is MIT. Decided 2026-10-15.

Fonts are redistributed under the SIL Open Font License 1.1, unmodified, with
their license texts in `public/licenses/` (copied into the build):

| Font | Use | Source | License |
|---|---|---|---|
| Cal Sans | headings | npm `cal-sans` 2.1.0 (github.com/calcom/sans) | OFL-1.1 |
| Paper Mono | code and figures | github.com/paper-design/paper-mono | OFL-1.1 |
| Geist | body text | npm `@fontsource-variable/geist` | OFL-1.1 |

Every stack falls back to system fonts. Dependency licenses at the time of the
first build were MIT, ISC (lucide-react), and Apache-2.0 (TypeScript,
class-variance-authority); check new dependencies before adding them.
