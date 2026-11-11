# mangaka（漫画家）

**AI が描いた manga を公開し、公開済みのページを下絵にして人が原稿を組み直す。**
組んだ原稿は storyboard EDN として書き出され、mangaka 自身のパイプラインの入力に戻る。

`mangaka` は「漫画家」であってメタファ名なので、名前だけでは機能を示さない。
入口をここ 1 本にするために、この README が名乗る（AGENTS.md の命名規則）。
機械可読の正本は `manifest.edn`（`:actor/purpose` / `:app/surface` / `:app/reads`）。

- actor id `mangaka` / mount `/mangaka` / host `app.itonami.cloud`
- 公開 reader: `mangaka.itonami.cloud`（Worker。D1 の work 行 + R2 のページ画像）
- 原稿スタジオ: `app.itonami.cloud/mangaka/`（静的資産のみ。書き込みをしない）

## 最近接 repo との境界

| repo | 境界 |
|---|---|
| `kotoba-lang/kami-genko` | **原稿 (genko) の doc モデルと編集 UI はあちら。** ここは呼ぶだけで、doc モデルを持たない |
| `cloud-itonami/mangaka-data` | **素材と golden fixture はあちら**（`style-registry.edn` / `recipe-ledger.jsonl` / ghosthacker asset graph）。west sibling として隣に checkout される |
| `network-awai/cloud-murakumo` | **GPU fleet への実 ComfyUI 経路はあちら。** ここの `mangaka.comfy` は gateway 前提の別経路 |
| `kotoba-lang/kami-mangaka-page` | **コマ割りの幾何はあちら。** ここの `mangaka.layout.komawari` は再 export であって独立実装ではない |
| `kotoba-lang/kami-mangaka-qa` | **QA/知覚の軸レジストリはあちら。** `mangaka.perception` は委譲 facade |

## 樹形図

| path | 何か | 規模 |
|---|---|---|
| `clj/` | **JVM サーバ + langgraph-clj グラフ（58 NSID）。ここが実行時の正本** | 93 files |
| `clj-edge/` | CF-Worker edge の cljs SSoT（`clj/` とは別物。pod 形ではない） | 7 files |
| `reader/` | 公開 reader Worker（`mangaka.itonami.cloud`） | 160 files |
| `studio/` | 原稿スタジオ（静的。reader の公開 API をブラウザから読むだけ） | 8 files |
| `comfy/` | ComfyUI / Modal の host 境界資産。**移植ではないので Python のまま残す** | 208 files |
| `fabric/` | guardian（`.kotoba` + `.wasm`）と host policy | 5 files |
| `appview/` `redirect/` | Worker 設定 | 8 files |
| `lg/` | legacy 非 Python サンプル資産のみ。**ここに新しいものを置かない** | 33 files |

新しいロジックは `.cljc`（`clj/` か `clj-edge/`）に着地させる。`lg/` を復活させない。

## 動かす

**まず [`docs/operator-quickstart.md`](docs/operator-quickstart.md)** —— 実際に踏んだ手順と、
今日の時点で赤いテストが何本でなぜかを書いてある。運用（描画から publish まで）は
[`RUNBOOK.md`](RUNBOOK.md)、agent 向けの注意は [`AGENTS.md`](AGENTS.md)。
