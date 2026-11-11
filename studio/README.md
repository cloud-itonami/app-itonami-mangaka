# mangaka studio — 原稿スタジオ

**https://app.itonami.cloud/mangaka/**

The reader (`../reader`, `mangaka.itonami.cloud`) shows a finished work. This
shows the same work as something you can still work on: the published page goes
under the paper as a traced underlay, and コマ割り / ふきだし / トーン / 文字 go
on top. What you assemble exports as storyboard EDN — the same shape mangaka's
own pipeline takes as input, so a work can go back in.

## There is almost no code here

The editor is [`kotoba-lang/kami-genko`](https://github.com/kotoba-lang/kami-genko),
consumed as a library and pinned in `deps.edn`. This directory owns *where it is
published*, not what it is:

| file | what it decides |
|---|---|
| `deps.edn` | which commit of the editor |
| `shadow-cljs.edn` | the bundle, from the library's own `genko-app` entry point |
| `scripts/gen-page.cljs` | **which catalog the page declares** — the one real decision |
| `wrangler.jsonc` | the script name, which is the path segment |

The page itself is `kami.mangaka.genko-theme/->page-html`, the same function
kami-genko's own published page calls. Two repos rendering the same page from
two copies of a generator is how the two surfaces drift.

## Why the editor becomes a studio

`<meta name="genko-catalog">` — that is the whole difference. `genko-app` reads
it at boot; where it is absent it never asks for a work list at all, which is
right for kami-genko's own page. Probing `api/works` and giving up on a 404
cannot tell "the catalog is down" from "there is no catalog", and would warn on
every load of a page that is working exactly as intended.

## Why the catalog is absolute and there is no proxy

The studio is served from `app.itonami.cloud`, the works and their images from
`mangaka.itonami.cloud`. Both `/api/` and `/img/` there send
`access-control-allow-origin: *`, so the browser reads them directly.

This matters for correctness, not just for simplicity: the reader returns page
`src` values like `/img/<key>`, absolute on **its** origin, and
`genko-work/with-base` resolves them against the declared catalog. Left as-is
they would resolve against `app.itonami.cloud` and 404 into a placeholder frame
with nothing on screen to say why.

## Nothing is written from here

No D1, no R2, no secrets. What a person assembles lives in their own browser
(localStorage, keyed per work) until they export it. Publishing back into the
pipeline is the reader's authenticated `POST /api/work/:rkey`, and is
deliberately not wired into a page anyone can open.

## Build and deploy

```bash
npm install
npm run build      # bundle, from the pinned kami-genko
npm run page       # dist/index.html, with the catalog declared
npm run deploy     # → dispatch namespace ai-gftd-repository-dispatch, as `mangaka`
```

The Worker has no URL of its own. `itonami-fleet-dispatch` reaches it as the
first path segment and strips it, so `app.itonami.cloud/mangaka/js/…` arrives
here as `/js/…`. The script name must stay `mangaka`: the router dispatches on
the repository name and there is no mapping table to edit.

## Verified

Driven in a real browser against the live catalog — the deployed surface, not a
local copy (2026-08-06, 9/9): the work list arrives, a cover resolves to an
absolute URL on the reader's origin, clicking a work opens all of its pages with
the underlay as an `ai-image` under a locked layer, the page image is fetched
cross-origin (200), and it is actually painted.

That last one is an A/B against the eye toggle rather than a pixel read: the
WebGL drawing buffer is not preserved between frames, so `readPixels` after the
draw returns `0,0,0,0` no matter what is on screen — measured, and it is what
the first version of that check wrongly reported.
