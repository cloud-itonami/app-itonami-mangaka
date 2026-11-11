# mangaka — operator quickstart

**この手順は 2026-08-19 に実際に踏んだ。** 踏めなかった手順は書いていない。
期待する出力（テスト本数・赤の本数）を併記してあるので、違う値が出たら
「環境が違う」ことがその場で分かる。

## 0. 前提 —— 隣の checkout が要る

`clj/deps.edn` の `:dev` alias は依存を **workspace の checkout** に向ける
（ネットワーク無しで開発するため）。したがって superproject の `orgs/` 配下に
隣り合って存在していることが前提で、`mangaka` だけを単独 clone しても動かない。

```bash
cd <superproject>          # orgs/ を持つ root
west update --fetch smart mangaka mangaka-data
```

要るのは 16 の kotoba-lang lib と `network-awai/cloud-murakumo`、そして
**`cloud-itonami/mangaka-data`**。確認:

```bash
cd orgs/cloud-itonami/mangaka/clj
for d in langgraph comfyui langchain langgraph-store kami-engine-sdk \
         kami-mangaka-expression kami-mangaka-qa kami-mangaka-page kami-genko \
         douga shitsuke canvaskit kotobase-client org-ietf-ed25519 \
         jp-go-digital-design-system aiueos; do
  [ -d "../../../kotoba-lang/$d" ] || echo "MISSING $d"
done
[ -d ../../../network-awai/cloud-murakumo ] || echo "MISSING cloud-murakumo"
[ -d ../../mangaka-data ]                   || echo "MISSING mangaka-data"
```

**`mangaka-data` を飛ばさないこと。** 無いと 2 本のテストが余計に赤くなる
（`registry-handlers` は `../../mangaka-data/ghosthacker/resources/asset_graph.json` を、
`seed-present-after-boot` はその seed を読む）。**「入力が無い」と「壊れている」が
同じ赤で出る**ので、先に上の確認を通す。

## 1. テストを走らせる

```bash
cd orgs/cloud-itonami/mangaka/clj
kbb -M:dev:test
```

**期待する出力（2026-08-19 実測）:**

```
Ran 190 tests containing 1203 assertions.
2 failures, 1 errors.
```

`190 tests / 1203 assertions` に届いていなければ、それは「テストが落ちた」のではなく
**classpath か sibling が足りていない**。特に、依存解決が失敗すると
`Error building classpath. Unable to compare versions for ...` と出て
**テストは 1 本も走らない**（合格でも不合格でもない）。

## 2. 今日の時点で赤い —— 既知で、原因が分かっている

報告される `2 failures, 1 errors` は、**相異なる 2 本のテスト**から出る
（片方は runner が同じ namespace を 2 度走査するため 2 回数えられる）。
**どちらも「自分の変更が壊した」ではない。** 手を入れる前にこの状態であることを
確認してから作業を始める。直っていないのは、どちらも過去の移行の取り残しであって、
実行時の欠陥ではないため。

| テスト | 何が起きているか |
|---|---|
| `manifest-matches-registry` (`core_test.clj:757`) ×2 | `clj/langgraph.edn` が **datom + `pr-str` 文字列 blob 形式**（docs-edn-only 移行の結果）になっており、テスト側は生の map を期待している。live registry の 58 NSID に対し manifest 側が空集合として読まれる。**`langgraph.edn` の中身は欠けていない** —— 読み方が古い。同じ失敗が 2 回数えられるのは、runner が `mangaka.core-test` を 2 度走査するため |
| `style-registry-golden` (`py_port_test.clj`) | `../data/style-registry.edn` を読むが、`data/` は **`mangaka-data` sibling へ移動済み**（実体は `../../mangaka-data/style-registry.edn`）。パスが移行に追従していない |

どちらも `axis-test` の仕事であって、この quickstart の範囲ではない。

## 3. サーバを起動する

```bash
cd orgs/cloud-itonami/mangaka/clj
PORT=8000 kbb -M:dev:run
```

**期待する起動ログ（2026-08-19 実測）:**

```
mangaka.gftd.ai (clj) listening on :8000  store=MemStore
  seeded ghosthacker: 5 characters, 6 scenes
  seeded storyboard: gh-arc0-1-p1
```

`store=MemStore` は既定の in-memory backend（`mangaka.store/mem-store`）。
seed 行が出ない場合は `mangaka-data` sibling が見えていない。

生きていることの確認は **POST** で行う。**XRPC の口は GET を受けないので、
`curl` の既定（GET）だと `405` が返る —— これはサーバが落ちている印ではない**:

```bash
curl -s -X POST -H 'content-type: application/json' -d '{}' \
  http://127.0.0.1:8000/xrpc/ai.gftd.mangaka.health
# => {"status":"ok","app":"mangaka.gftd.ai","impl":"clj"}
```

graph は 58 NSID が `mangaka.graphs.registry` に登録される
（一覧は `clj/langgraph.edn` の `:clj.langgraph/graphs`）。

描画・publish・fleet の運用（ComfyUI / Tailscale / R2 / D1）は
[`../RUNBOOK.md`](../RUNBOOK.md) が正本。**`RUNBOOK.md` のコマンドは repo が
`orgs/gftdcojp/ai-gftd-mangaka` に在った頃のパスを書いている** —— いまは
`orgs/cloud-itonami/mangaka`。読み替えること。
