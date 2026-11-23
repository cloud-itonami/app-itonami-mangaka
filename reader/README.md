# mangaka-reader

Public manga reader Worker (mangaka.itonami.cloud / manga.gftd.ai). Plain-JS
Worker `src/worker.js` (zero deps, deployed directly — no build step) with D1
(`MANGAKA_DB`) for work/page rows and yataverse
(https://yataverse.com/ipfs/<cid>) for page images. The pure `.cljk` render /
host in `src/mangaka_reader/` is kept for reference but is no longer deployed.

## /img/<key> and /ipfs/<cid> image resolution

`GET /ipfs/<cid>` fetches `https://yataverse.com/ipfs/<cid>` and streams the
bytes back with the upstream `Content-Type` and `cache-control: public,
max-age=300`. `GET /img/<key>` treats `key` as a CID (or finds it in the
explicit `IMG_KEY_MAP` table at the top of `src/worker.js`, for legacy slug
keys) and serves it the same way.

This Worker has **no R2 binding** (`r2_buckets` was removed from
`wrangler.jsonc`; the `ai-gftd-cdn` bucket never existed) and never fetches
the R2 path. Anything that cannot be resolved — unknown key, upstream non-OK
or network error — returns **404**
`{"error":"image-unavailable","key":"…","source":"yataverse"}` — never 500.
Keys rejected by the path-traversal guard (blank, `/` anywhere, backslash,
`..`, control chars) get **400** before any fetch runs.

## Tests

`npm test` (`node --test test/worker.test.js`; fetch is stubbed, no network).
