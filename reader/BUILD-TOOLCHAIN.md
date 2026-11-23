# reader ビルドツールチェーン（実測記録）

**結論（2026-11-24 更新）**: **ビルドは不要になりました**。Reader は plain JS の Worker
（`src/worker.js`、依存ゼロ）がそのままデプロイされ、`wrangler.jsonc` の `main` は
`src/worker.js` を指します。`dist/` は生成されません（`npm run build` は
`node --check src/worker.js` の構文チェックのみ）。以下に残る 2026-11-23 の実測は
旧 `.cljk` 経路（shadow-cljs / amu が通らなかった経緯）の履歴です。
テストは `npm test`（`node --test test/worker.test.js`、ネットワーク不要・fetch スタブ）で通ります。

---

（以下、2026-11-23 実測の履歴）

**旧結論（2026-11-23 実測）**: `npm run build`（= `amu compile --target wasm32-browser worker redirect`）は
**この機械では通らない**。`amu` が無くても、有っても同じ（用法エラー exit 2）。
`reader/dist/worker.js` は**生成されなかった**（sha256 なし）。`npm test` も同じ。
実際に `dist/worker.js` を作れるのは **shadow-cljs**（`devDependencies` + `shadow-cljs.edn`）だが、
現リポジトリのままでは下記 blocker より先へ進めない。

## 1. `amu` の入手方法（一次情報）

**`git clone https://github.com/kotoba-lang/amu`** が唯一の入手経路。GitHub Releases は無い
（`gh api repos/kotoba-lang/amu/releases` → `[]`）。バイナリはリポジトリ内にチェックインされている:

| 項目 | 値 |
|---|---|
| ローカルクローン | `~/github/kotoba-lang/amu` @ `87ec570aff47a0a21b4876fcda4fa9d4e3b934fb` (2026-11-22) |
| エントリ | `bin/amu` → `seed/bootstrap/aarch64-macos/amu-cli.macho` (Mach-O arm64, dylib 依存なし) |
| `bin/amu` sha256 | `016aaefcac44eff3408fb30283aa5ab1125fb0ff0298d56ea23df621d67fc837`（`seed/bootstrap/aarch64-macos/cli.json` の pin と一致） |
| フルコンパイラ | `seed/bootstrap/aarch64-macos/amu-full-root.macho` sha256 `2cf49c2346437a9c3bd85f29cd72b7947d3280c98bed091ef99a552707d22370`（同 pin と一致） |
| 根拠 | amu README「`bin/amu` is an Amu-built, self-rebuilt native **macOS ARM64** executable」、docs/native-public-entry.md、no Makefile |

`PATH` にクローンの `bin/` を入れれば `which amu` は通る（実測）。ただし下記の通りビルドは失敗する。

## 2. なぜ `npm run build` が通らないか（実測）

`amu` を用意した状態で実行（0.14s で exit 2）:

```sh
$ npm run build
> amu compile --target wasm32-browser worker redirect
amu: usage: amu check FILE.kotoba|FILE.cljk | ... | compile FILE.kotoba [--runtime-profile ...] [-o OUTPUT] | ...
```

理由（一次情報 + 実測の3点）:

1. **public CLI は位置引数の build id を受け付けない**。`compile` は
   `FILE.kotoba`（または `--source-lock` / `--source-path`）のみ。`worker` / `redirect` を
   ソースファイルとして拒否。`--target` も public CLI では用法エラー（host 固定: aarch64-macos）。
2. **public CLI の出力はネイティブ Mach-O**（single file, exported `main [] :i64`、1 MiB まで）。
   `dist/worker.js`（ESM バンドル）は作れない。`.cljk` への `compile` も拒否（`check FILE.cljk` のみ可）。
3. **full-root も別物**。`amu-full-root.macho compile <file> --target wasm32-browser --output <out.wasm>`
   （FD3 でソースディレクトリを渡す）で wasm は実測可能だが、対象は単一の正規 `.kotoba` のみ。
   reader の本体 `src/mangaka_reader/worker.cljk`（`js/Response`、D1/R2 バインド）は対象外。

この build スクリプトは ADR-2609112000（commit `c35dd3d`, 「kbb: rewrite … shadow-cljs invocation(s)
… to kbb/amu」）による機械置換で、`shadow-cljs release …` → `amu compile --target wasm32-browser …`
と書き換えられたもの。amu 側の自己記録にも「`amu compile --target wasm32-browser worker` は
amu が positional build id を source file として拒否 (exit 64)。ADR-2609112000 既知
『shadow→amu は 1:1 でない、別 wave』の実例」とある。**`amu` は shadow-cljs の代替実装ではない。**

`npm test`（`amu compile --target wasm32-browser test && node out/node-tests.js`）も同様に
exit 2 の用法エラーで回らない。

## 3. 実際に `dist/worker.js` を作れる経路: shadow-cljs

`shadow-cljs.edn` の builds（`worker` / `redirect` / `test`）と `deps.edn` の
`thheller/shadow-cljs 2.28.20` が実際の生産者。実測した前提バージョン:

| ツール | 版本（実測） |
|---|---|
| node | v26.3.0 |
| npm | 11.16.0 |
| Java | **`/usr/bin/java` はスタブ**（Unable to locate a Java Runtime）。`JAVA_HOME=/opt/homebrew/opt/openjdk` で openjdk 27.0.1.0.3 |
| Rust | 1.98.1（Homebrew）（amu ビルドには不要。binaries はチェックイン済み） |
| bb | v1.12.218（mirror には nbb が要る。bb は node:fs が無い） |
| git | 2.50.1 |

門番（`~/.orca/bots/organizer/memory/disk/signal.tsv`）: verdict **GO**（min 13.93 GiB）。

ここまでの実測手順:

```sh
cd reader
export JAVA_HOME=/opt/homebrew/opt/openjdk PATH="$JAVA_HOME/bin:$PATH"
npm install --no-audit --no-fund            # 124 packages、exit 0
./node_modules/.bin/shadow-cljs release worker
# → "The required namespace \"mangaka-reader.worker\" is not available." exit 1
```

## 4. 現在の blocker（実測順）

1. **`.cljk` ソースが shadow-cljs に見えない**。reader の本体は全て `.cljk`
   （`src/mangaka_reader/*.cljk`）、shadow は `.cljs/.cljc/.clj` のみ見る。
   **mirror スクリプト（`.cljk` → ビルド用 `.cljc`）がリポジトリに無い**（`scripts/cljk-mirror.cljk` 不在。
   kotoba-cljk-build の nbb+mirror パターンを追加すること）。
2. **west sibling ソースが存在しない**。`deps.edn` の
   `../../../kotoba-lang/{manga-viewer,shitsuke,html}/src` は `~/orca/workspaces/kotoba-lang/` を指すが同ディレクトリは空。
   `kotoba-lang/manga-viewer` / `shitsuke` / `html` としての GitHub リポジトリも 404（後継は
   kotoba monorepo の `lib/kotoba.mangaViewer` / `lib/kotoba.shitsuke` / `lib/kotoba.html` だが
   layout が異なる）。monorepo から vendor しても次で止まる:
3. **後継 shitsuke は cljs 実行不可**。monorepo 版 `shitsuke.hiccup/->html` は
   RAWTEXT 判定を Kotoba-guest oracle（`kotoba.kir` + `shitsuke/oracle/*.kir.edn` +
   `kotoba.lang.edn`/`kotoba.io`）へ委譲する。`kotoba.kir` は `:cljs` 分岐で `./kir/js_host.mjs` を
   require するが **shadow-cljs は `.mjs` を cljs リソースとして識別できず** compile で止まる
   （`cannot identify as cljs resource`）。回避しても oracle の resource 読みは `:clj` 専用で、
   workerd 上では実行時に失敗する。**すなわち现 monorepo 版 shitsuke では worker 自体が作れない。**
4. **git 依存は解決済み**。`io.github.kotoba-lang/text` (sha `7e1dbe0a…`, root `lib/kotoba.text`) は
   shadow 実行時に `~/.gitlibs` へ clone 済み（ネットワーク初回のみ）。
5. **`shadow-cljs compile test && node out/node-tests.js` は exit 0 だが 0 tests**
   （50 files, 2.36s）。`.cljk` のテストはロードされず、false green。CI にしないこと。

## 5. 次の一手（推奨順）

- **A.** reader の mirror スクリプトを追加し、shitsuke の cljs 経路が直るまで worker ビルドは
  ブロックされたままであることを `package.json` に明記（現状の `amu` スクリプトは壊れている）。
- **B.** shitsuke に cljs 実行可能な `hiercup/->html`（oracle 無し）を戻す、または旧 shitsuke の復元。
  これが直って初めて shadow `release worker` → `dist/worker.js` が出る。
- **C.** `npm test` の実質化: img_test（cljs.test）+ render_test（clojure.test）を
  mirror 経由で node-test として回す。0-tests false green を避けるため、
  `Ran N tests` の行をアサートすること。

## 6. 生成物

`dist/` は生成されなかった（上記 blocker）。sha256 / bytes の記録対象は無い。
`npm install` で作られた `node_modules/` は `.gitignore` 済みでリポジトリに含まれない。
