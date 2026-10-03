---
title: "【メモ】Claude Code プラグイン pstack のスタック構成とオーケストレーションを読む"
emoji: "🥔"
type: "tech"
topics: ["claudecode", "ai", "agent", "pstack"]
published: false
---

:::message
本記事は筆者個人の見解であり、所属する組織の公式見解ではありません。

また、ここで扱う pstack はコミュニティによる移植版のプラグインで、更新が頻繁です。本文の記述は執筆時点(2026年10月, pstack v0.9.53 / Claude Code v2.1.287 で確認)のものなので、最新の構成は[リポジトリ](https://github.com/michael-denyer/pstack-claude)をご確認ください。
:::

## はじめに

pstack は、Lauren Tan (poteto) さんが Cursor 向けに作ったスキル群を、Claude Code 向けに移植したプラグインです(出典: [pstack-claude の README](https://github.com/michael-denyer/pstack-claude))。元の pstack は [cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack) にあります。

スキルやハーネスエンジニアリングに関心がある立場から、インストールしたプラグインの中身を読みました。どう組み立てられているかを、オーケストレーションの仕組みを中心にまとめたメモです。動作を確かめたものと推測とは分けて書きます。

## TL;DR

- pstack はほぼすべて Markdown です。実行コードは補助の CLI だけです。
- 構成は5層です。SessionStart フック、振り分け役のスキル(poteto-mode)、プレイブック、原則の葉スキル、子エージェント定義です。
- プレイブックはタスクの種類ごとの手順書で、22本あります。Claude Code のスキルではなく、poteto-mode の索引からだけ辿られます。
- オーケストレーションは pstack 全体の基本の動き方です。専用のエンジンは持たず、メインのエージェントが Agent ツールで子を呼びます。スキル内に Claude Code の Workflow ツールを使う記述はありませんでした。
- orchestrate プレイブックが違うのは、状態をチャットの外のファイルに書き出す点です。その管理に orch CLI (bun) を使います。
- bun は pstack 全体には必須ではありません。orchestrate、PR 監視、作業の中断と再開を使うときに必要です。

## 全体の構成

プラグインの中身は次のとおりです(v0.9.53 のインストール先で確認)。

- スキル 54 本。poteto-mode、architect、arena、swarm、tdd、unslop などと、`principle-*` 系 21 本です。
- エージェント 12 本。poteto-agent、comment-sicko と、reasoning effort 別の版です。
- SessionStart フック 1 本。
- `models.json`。役割ごとの既定モデルを書いたファイルです。

以下、外側から順に層を足していきます。

### 1. 入口は SessionStart フック

```
SessionStart フック ──(テキストを注入)──> メインエージェント
  hooks/session-start.sh
```

`hooks.json` の matcher は `startup|resume|clear|compact` なので、新規起動でも動きます。`session-start.sh` の処理は `session-start-context.md` を cat するだけです。中身は「複数ファイルにまたがる変更、設計判断、原因不明のバグなら poteto-mode を呼べ」という振り分け指示です。

止め方も用意されています。`pstack-models.md` (Claude Code の設定ディレクトリ直下)に `session hook: off` の1行を書くと、スクリプトは何も出力せずに終わります。

### 2. 振り分け役のスキルがプレイブックを選ぶ

```
SessionStart フック ──> メインエージェント
                          │ Skill("pstack:poteto-mode")
                          v
                     poteto-mode/SKILL.md(振り分け役)
                          │ タスクの種類で1つ選ぶ
                          v
                     playbooks/*.md(22本: bug-fix, feature, orchestrate …)
```

poteto-mode 自身は作業をしません。中身はほぼ索引で、タスクの種類からプレイブックへの対応表になっています。「Bug fix なら `playbooks/bug-fix.md`」という形です。

選んだプレイブックの手順は、TODO リストに一字一句写させます。やらない手順も消させず、`skip: <理由>` を付けて残させます。手順を飛ばしたことが、後から見えるようにする工夫です。

### 3. 原則は葉のスキルに分ける

```
poteto-mode/SKILL.md
  ├─ playbooks/*.md
  └─ Principles 索引(1行ずつ「いつ効くか」だけ)
        └─> principle-*/SKILL.md(21本。適用するときだけ全文を読む)
```

振り分け役には原則の本文を載せていません。索引には名前と適用条件が1行ずつあるだけで、全文は葉のスキルにあります。

そのうえで、返答で原則を名指しするよう求めます。ただし名指しできるのは、そのセッションで葉を読んだ原則だけです。コンテキストを節約しつつ、読んだかどうかを出力から確かめられる作りです。

### 4. 子エージェントの定義は中身を持たない

```
メインエージェント
  │ Agent(subagent_type="pstack:poteto-agent[-<effort>]", model=..., run_in_background)
  v
poteto-agent.md ──「poteto-mode の SKILL.md を全文読め」──> 2 と同じ振り分け役
```

`agents/poteto-agent.md` の本文は数行です。「poteto-mode の SKILL.md を全文読め」と書いてあるだけです。こうしておけば、作法の正本は SKILL.md の1か所で済みます。

effort 別の10本も、違うのは frontmatter の `effort: high` などだけで、本文は同じです。Agent ツールの呼び出しには effort を渡す引数が無く、エージェント定義の frontmatter でしか変えられないためだと筆者は推測しています。設計の経緯は確かめていません。

モデルは呼び出しのたびに `model` 引数で渡します。役割ごとの既定値は `models.json` にあり、`tools/generate.mjs` が各 SKILL.md の Models 節に書き込みます。実行時は `pstack-models.md` の行が優先され、`opus @xhigh` のようにモデルと effort を一緒に指定できます。

arena、architect、interrogate の3つは `panel` という役割を使います。`panel` は opus / fable / sonnet の3モデルの組です。別々のモデルに同じ問題を解かせ、互いの穴を突かせるためです。

## プレイブックとは

プレイブックは、タスクの種類ごとの作業手順書です。中身は番号付きの手順と、最後の返答に何を書くかの指定だけです。ほとんどは 11〜33 行で、置き場所は `skills/poteto-mode/playbooks/` です。

プレイブックは Claude Code のスキルではありません。frontmatter が無いので、Claude Code が自動で見つけて呼ぶことはありません。poteto-mode の索引に「Feature なら `playbooks/feature.md`」と書いてあり、エージェントがそれを開く、という1本の道だけで辿られます。

たとえば `feature.md` の手順は次のとおりです(筆者による要約)。

1. `how` で対象のサブシステムを調べる。
2. `architect` で設計案を並行して出す。
3. 並列化できるかの点検を4項目書く。
4. 実装は子エージェントに任せる。
5. 実際の画面や CLI で確かめる。
6. 小さなコミットに分けて積む。
7. 設計に異論があれば `interrogate` にかける。
8. PR を開く。

各手順が別のスキルを呼んでいます。プレイブックは、スキルを組み合わせる順番を決める台本です。

### どんなプレイブックがあるか

22本あります。分類は筆者によるものです。

| 分類 | プレイブック |
|---|---|
| 調べる | investigation, runtime-forensics, trace-forensics |
| 直す・作る | bug-fix, perf-issue, hillclimb, feature, refactoring, prototype, visual-parity |
| スキル自体 | authoring-a-skill, eval |
| PR・リリース | babysit, shipping, opening-a-pr |
| 長時間・大規模 | autonomous-run, orchestrate, autopilot-full, autopilot-stack, multi-phase-plan |
| 中断と再開 | pause-safely, session-pickup |
| 掃除 | worktree-cleanup |

長いのは multi-phase-plan(158行)と orchestrate(113行)の2本だけです。

### プレイブックは増やせるか

ユーザーが自分のプレイブックを足すための置き場所は、pstack には用意されていません。プレイブックはプラグインのキャッシュ(`.../pstack/0.9.53/`)の中にあります。ここを書き換えても、プラグインを更新すると別のバージョンのディレクトリに切り替わり、変更は残りません。代わりの手は3つあります。

- figure-it-out を使う。当てはまるプレイブックが無いときに、そのタスク専用の手順をその場で設計するスキルです。ただし使い捨てで、`playbooks/` には保存されません。
- 自分のスキルとして書く。`~/.claude/skills/` に置けば Claude Code がそのまま拾います。automate-me は、自分の作業スタイルを `<名前>-mode` というスキルにまとめる手伝いをします。poteto-mode の個人版を作るイメージです。
- フォークして直す。移植元のリポジトリに PR を出す道もあります。

### 「同じことを2回書いたら仕組みにせよ」との関係

`principle-encode-lessons-in-structure` は、同じ指示を2回書いたら、文章を足さずに仕組みに置き換えよ、という原則です。置き換え先は lint、メタデータのフラグ、実行時のチェック、スクリプトです。選べるなら強いものを使えとも書かれています。強い順に、型で不正な状態を作れなくする、lint で CI を落とす、共通ヘルパー、実行時チェックです。文章で残してよいのは、判断が要って仕組みにできないときだけです。

学びの振り分け先も決めてあります。

- 1回限りのこと → メモ
- 繰り返し起きる修正 → スキルか lint
- 根の深い問題 → 原則

この原則で測ると、プレイブックは「文章で残す」側です。繰り返す手順をまとめたものですが、守るかどうかはエージェント次第です。そのため pstack は、プレイブックの文章を仕組みで補っています。手順を TODO に一字一句写させ、飛ばした手順は `skip:` 付きで残させます。orchestrate では、状態の管理を文章ではなく orch CLI に任せています(後述)。

学びを実際に書き残すスキルは reflect です。会話を3体の子エージェントに読ませ、学びを既存スキルの具体的な修正に振り分けます。新しいプレイブックを作るのではなく、今あるスキルを直す方向です。figure-it-out も最後の手順で、繰り返し起きた修正をゲート、lint、チェック、スクリプトにせよと指示しています。

## オーケストレーションは pstack 全体の動き方

オーケストレーションを「メインのエージェントが子エージェントに仕事を割り振り、結果を集めて判断すること」とすると、pstack のあちこちで起きています。子を起動する手順を持つスキルを grep すると、architect、arena、how、interrogate、no-comments、poteto-mode、reflect、swarm、why が見つかりました。

たとえば why は、複数の調査役に分担させ、まとめ役がそれを統合します。interrogate は複数のモデルにレビューさせます。poteto-mode 本体にも、子を呼ぶときの決まりがあります。バックグラウンドで動かす、役割ごとにモデルを明示する、子の報告を鵜呑みにせず差分を自分で確かめる、といったものです。

orchestrate プレイブックが特別なのは、オーケストレーションをすることではありません。状態をどこに置くかです。

| | 状態の置き場所 | 寿命 |
|---|---|---|
| swarm、arena、why など | 親エージェントのコンテキスト | 1セッション内 |
| orchestrate | チャットの外のディレクトリ(orch CLI) | 何日でも。セッションが変わっても続く |

```
swarm        N体を一斉に起動 → 全員の終了を待つ → 1本の報告(PASS / ISSUES / BLOCKED)
arena        同じ課題でN体を競わせる → 土台を1つ選ぶ → 他の案の良い部分を移植
orchestrate  調整役チャット ─ 依頼書 ─> 作業担当(worktree ごとに隔離)
                │                         │
                └── orch CLI(bun)────────┘
                    状態ディレクトリ: units.tsv / ledger.tsv / frontier.json / inbox/
```

### 1セッションで終わるものはプロンプトだけ

swarm や arena は、プロンプトの指示だけでできています。子を1回のメッセージでまとめて起動し、全員の終了を待ってから結果を集約します。子の結果は親が自分のコンテキストに覚えておくので、コードは要りません。

swarm の決まりは2つです。結果の形式を `PASS` / `ISSUES` / `BLOCKED` に固定すること。そして、依頼書で指定した SHA と計測方法が書かれていない結果は捨てて、もう一度やらせることです。

### orchestrate は状態を外に書き出す

orchestrate は、何日もかかり、PR を何本も積み、子エージェントが数十から数百体になる案件向けのプレイブックです。この規模になると、子の結果はコンテキストに収まりません。圧縮や再起動も避けられません。要点は3つあります。

1つ目に、調整役はコードを書きません。調整役の成果物は作業担当への依頼書(brief)です。依頼書には決まった項目があります。GOAL / SCOPE / CONTEXT / ACCEPTANCE / VERIFY / TIMEBOX / FORBIDDEN / REPORT / STANDING です。STANDING は人間が決めた常設ルールをそのまま貼る欄です。項目を埋められない作業は起動しません。作業担当は調整役に質問できないので、依頼書が曖昧だと黙って失敗するからです。

2つ目に、子の完了を割り込みとして扱いません。プレイブックには次の一文があります。

> "Completions are queue events, not interrupts."
> (仮訳: 完了はキューのイベントであって、割り込みではない。)
>
> 出典: [pstack-claude](https://github.com/michael-denyer/pstack-claude) v0.9.53 の `skills/poteto-mode/playbooks/orchestrate.md`

完了の知らせは `inbox/` に積み、調整役が決まった時点でまとめて処理(ドレイン)します。

3つ目に、状態をセッションの外のディレクトリに置きます。orch CLI がこれを TSV と JSON で管理します(`orch.ts` と `store.ts` で約2200行)。セッションが再起動しても、コンテキストが圧縮されても、処理を再開できます。後で振り返るときの記録にもなります。

Claude Code の子エージェントは全部同じマシンで動きます。そのため、作業担当どうしの隔離は worktree かブランチを分けて行います。

## orch CLI (bun) は必須か

pstack 全体としては必須ではありません。orch を呼ぶ記述は、grep した範囲では `playbooks/orchestrate.md` にしかありませんでした。poteto-mode の振り分け、swarm、arena、architect、tdd などは、Markdown の指示と Agent ツールだけで動きます。

ただし orchestrate を使うなら orch は欠かせません。手順の中に orch のコマンドが組み込まれているからです。

- 開始時に `orch init` を実行します。
- 子が終わるたびに `orch inbox push` を実行します。
- ドレインは `orch inbox drain` で始めます。
- 処理の最後は、`orch status` が出す3行で報告を締めます。

orch が使えない場合の代わりの手順は、プレイブックに書かれていません。

bun が要るスクリプトはほかにもあります。どのプレイブックから参照されているかは grep で確かめました。

| スクリプト | 使う場面 |
|---|---|
| `watch-pr/` | babysit、Shipping(PR の監視とマージ) |
| `check-plan.mjs` | Multi-phase plan |
| `resume.mjs` | Pause safely、Session pickup(作業の中断と再開) |
| `worktree-audit.mjs` | Worktree cleanup |

watch-pr は GitHub と `gh` を前提にしています。GitLab ではそのままでは動かないと筆者は見ていますが、中身を読んだうえでの推測です。

node で代わりに動かすことはできません。`bootstrap.ts` は、bun 以外で起動されると「requires bun」と表示してすぐ終了します。

筆者の環境(Linux)では、`mise use -g bun@latest` で bun 1.4.2 を入れました。その後 `bun orch/orch.ts --help` でヘルプが表示されることを確認しています。初回の起動時に、`bootstrap.ts` が依存パッケージ(commander)を自動で入れました。

```
$ bun orch/orch.ts --help
Usage: orch [--store <dir>] [--json] [--force] <command>

Plain-file orchestrate bookkeeping
...
Commands:
  init           initialize the store
  unit           manage work units
  ledger         manage verification records
  inbox          manage agent pointers
  gate           manage decision gates
  frontier       manage the Graphite stack frontier
  status         render status.md and print a summary
  standing       manage standing orders
```

(`skills/poteto-mode/scripts` で実行。一部を省略しています。)

状態ディレクトリの既定は、プレイブックの記述では `~/.claude/orchestrate/<project-slug>/` です。`CLAUDE_CONFIG_DIR` で設定ディレクトリを変えている環境では、`--store` か環境変数 `ORCH_STORE` で場所を指定します。

## ハーネスエンジニアリングとして読むと

参考になったのは、プロンプトだけでは守らせきれない部分を、構造で縛っている点です。

- 手順を TODO に写させ、飛ばした手順を見えるようにする。
- 読んでいない原則は名指しさせない。
- 子の結果の形式を固定し、必要な項目が無い結果は捨てる。
- 長期の状態はチャットの外のファイルに置く。

前述の `principle-encode-lessons-in-structure` の方針が、pstack 自身の作りにも通っています。

一方で、自分の運用と合わせるときに注意する点もあります。poteto-mode の Autonomy 節には、元に戻せる作業は確認せずに進めるという方針があります。CLAUDE.md で確認を求めるルールを置いている場合は、どちらが優先されるかを決めておく必要があります。
