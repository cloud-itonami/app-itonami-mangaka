# mangaka-reader

Public manga reader Worker (mangaka.itonami.cloud / manga.gftd.ai). Pure cljc
render in `src/mangaka_reader/render.cljk`, thin cljs workerd host in
`src/mangaka_reader/worker.cljk`.

## /img/<key> image resolution

`GET /img/<key>` resolves images two ways, switched by the optional
`IMG_ORIGIN` var (see `wrangler.jsonc`): with `IMG_ORIGIN` set it fetches
`<IMG_ORIGIN>/<key>` and returns the upstream 200 with the upstream
`Content-Type` and `cache-control: public, max-age=300`; unset (or empty) it
keeps the legacy R2 binding path (`ai-gftd-cdn`, key
`blobs/mng4k4x1.gftd.ai/<key>`, immutable cache). In either config a failed
lookup (upstream non-OK/network error, R2 miss or R2 throw such as the missing
bucket) returns **404** `{"error":"image-unavailable","key":"…","source":"origin"|"r2"}`
— never 500 — and keys rejected by the path-traversal guard (`..`, leading `/`,
backslash, blank, control chars) get 400 before either route runs; with
`IMG_ORIGIN` unset and the R2 bucket still absent, every `/img/<key>` is that
404 until the origin is set.

## Tests

`npm test` (shadow-cljs `:test` node-test → `node out/node-tests.js`).
