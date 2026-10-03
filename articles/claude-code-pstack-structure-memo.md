---
title: "【メモ】pstack (Claude Code 移植版pstack-claude) のスタック構成とオーケストレーションを読む"
emoji: "🥔"
type: "tech"
topics: ["claudecode", "ai", "agent", "pstack"]
published: false
---

:::message
本記事は筆者個人の見解であり、所属する組織の公式見解ではありません。

また、ここで扱う pstack はコミュニティによる移植版のプラグインで、更新が頻繁です。本文の記述は執筆時点(2026年10月, pstack-claude v0.9.63 / Claude Code v2.1.288 で確認)のものなので、最新の構成は[リポジトリ](https://github.com/michael-denyer/pstack-claude)をご確認ください。
:::

## はじめに

[pstack-claude](https://github.com/michael-denyer/pstack-claude) は、Claude Code に「仕事の進め方」を教えるプラグインです。Lauren Tan (poteto) さんが Cursor 向けに作ったスキル群 pstack を、Claude Code 向けに移植したものです(出典: [pstack-claude の README](https://github.com/michael-denyer/pstack-claude))。元の pstack は [cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack) にあります。

たとえば「このバグを直して」と頼むと、Claude Code はいきなりコードを書き換えがちです。pstack を入れると、まず再現し、原因を突き止め、直し、実際に動かして確かめる、という手順を踏むようになります。その手順を Markdown で書いて Claude Code に読ませているのが pstack です。

この記事では、pstack がどんな部品でできていて、依頼を受けたときにどう動くのかを、中身を読んで調べた範囲でまとめます。

読みながら、もう1つの問いも追いかけます。pstack は、なぜ「スタック」という名前なのか。積み重ねるものは何なのか。名前の由来は、移植版と元の pstack のどちらの README にも説明がありません(2026年10月に筆者が確認)。そこで、中身から答えを探します。Claude Code のスキルやフックを自分で書いている人に向けたメモです。細かい話は折りたたみのコラムに分けたので、最初は読み飛ばしてかまいません。

## TL;DR

- pstack の中身はほぼ Markdown です。プログラムは補助のコマンドだけです。
- 依頼を受けると、pstack は仕事の種類(バグ修正、機能追加など)に合う手順書を選び、その手順どおりに進めます。この手順書を「プレイブック」と呼びます。
- 作業の一部は子エージェントに任せます。子エージェントにも同じ手順書と決まりを読ませて、同じ進め方をさせます。
- 何日もかかる大きな案件だけは、進み具合をファイルに書き出して管理します。そのためのコマンドに bun が必要です。
- 「スタック」が何を積むのかには、2つの読み方があります。指示書を層に積む「スキルのスタック」と、成果を小さな PR にして順に積む「PR のスタック」です。

## 先に用語をそろえる

この記事に出てくる Claude Code の用語です。

| 用語 | 意味 |
|---|---|
| スキル | Claude Code が必要なときに読み込む指示書。`SKILL.md` という Markdown ファイル |
| フック | 決まったタイミングで自動で動くスクリプト。SessionStart フックはセッション開始時に動く |
| 子エージェント | Claude Code が作業の一部を任せるために起動する、別の Claude。親の会話は見えない |
| プラグイン | スキル、フック、エージェント定義などをまとめて配布する単位 |

## 依頼を受けてから何が起きるか

「ログイン画面のバグを直して」と頼んだ場合を例に、pstack の部品が順に出てくる様子を追います。

### 1. セッション開始時に、フックが「poteto-mode を使え」と伝える

```
SessionStart フック ──「poteto-mode を使え」──> Claude Code
```

pstack はセッションの開始時に、短い指示を Claude Code に渡します。中身は「複数のファイルにまたがる変更や、原因が分からないバグなら、poteto-mode スキルを使え」というものです。poteto-mode は pstack の中心になるスキルです。

### 2. poteto-mode が、仕事の種類に合うプレイブックを選ぶ

```
SessionStart フック ──> Claude Code
                          │ poteto-mode スキルを読む
                          v
                     poteto-mode
                          │ 「バグ修正」だと判断
                          v
                     bug-fix プレイブック(手順書)
```

poteto-mode の中身の多くは、仕事の種類ごとにどのプレイブックを使うかの一覧です。「バグ修正なら bug-fix」「機能追加なら feature」のように、合うプレイブックを1つ選びます。

Claude Code は、選んだプレイブックの手順を TODO リストにそのまま写します。やらないと決めた手順も消さず、「skip: 理由」を付けて残します。後から見た人が、どの手順を飛ばしたかを確かめられるようにするためです。

### 3. 必要になった原則だけを読む

```
poteto-mode
  ├─ プレイブック(手順書)
  └─ 原則の一覧(名前と「いつ使うか」を1行ずつ)
        └─> 原則ごとのスキル(使うときだけ全文を読む)
```

pstack には、「根本原因を直せ」「作ったら実物で確かめよ」のような原則が23個あります。poteto-mode には原則の名前と、いつ使うかの1行だけが載っています。本文は原則ごとに別のスキルに分けてあり、使うときだけ読みます。全部を最初から読ませると、Claude Code が一度に扱える文章の量(コンテキスト)を無駄に使うからです。

返答では、どの原則に従ったかを書かせます。ただし書いてよいのは、そのセッションで本文を読んだ原則だけです。読んでいない原則をもっともらしく持ち出すのを防ぐ決まりです。

### 4. 作業の一部を子エージェントに任せる

```
Claude Code(親)
  │ 「この修正を実装して」
  v
子エージェント ──「まず poteto-mode を読め」──> poteto-mode
```

プレイブックには「実装は子エージェントに任せる」のような手順があります。ところが子エージェントは親の会話を見ないまま起動するので、親が読んだ poteto-mode のことも知りません。そこで pstack は、子エージェントの定義ファイルに「作業の前に poteto-mode を全文読め」とだけ書いています。進め方を書く場所が poteto-mode の1か所で済み、親と子が同じ進め方で動きます。

ここまでの1から4を振り返ると、指示書が層になっています。セッション開始時の短い指示、poteto-mode、プレイブック、原則、子エージェントの定義です。上の層は下の層を名前で呼び出し、中身は必要になるまで読みません。移植版の README は pstack を "an opinionated skill stack"(仮訳: 考え方のはっきりしたスキルのスタック)と呼んでいます(出典: [pstack-claude の README](https://github.com/michael-denyer/pstack-claude))。これが「スタック」の1つ目の読み方です。

:::details コラム: 子エージェントのモデルと effort の指定
子エージェントを起動するときは、どのモデルを使うかを毎回指定します。役割ごとの既定値は `models.json` にあり、たとえばバグ修正には最も強いモデル(fable)、機能追加には標準のモデル(opus)を使います。利用者は `pstack-models.md` というファイルで役割ごとに上書きでき、`opus @xhigh` のようにモデルと推論の強さ(effort)を一緒に指定できます。

effort ごとに中身が同じエージェント定義が10本あり、違いは frontmatter の `effort: high` などだけです。Claude Code で子エージェントを起動するときに effort を渡す引数が無く、エージェント定義でしか変えられないためだと筆者は推測しています。設計の経緯は確かめていません。

arena、architect、interrogate の3つは、opus / fable / sonnet の3モデルに同じ問題を解かせます。別々のモデルに互いの見落としを指摘させるためです。
:::

:::details コラム: フックを止める方法
SessionStart フックは、新規起動、再開、`/clear`、圧縮のたびに動きます。止めたいときは、Claude Code の設定ディレクトリにある `pstack-models.md` に `session hook: off` の1行を書きます。フックのスクリプトはこの行を見つけると、何も出力せずに終わります。
:::

## プレイブックとは

プレイブックは、仕事の種類ごとの手順書です。中身は番号付きの手順と、最後の返答に何を書くかの指定だけで、ほとんどが十数行から30行ほどです。

たとえば機能追加用の feature プレイブックの手順は、要約すると次のとおりです。

1. 関係するコードの仕組みを調べる(`how` スキル)。
2. 設計案を複数並行して出す(`architect` スキル)。
3. どの作業を並行できるかを書き出す。
4. 実装を子エージェントに任せる。
5. 実際の画面やコマンドで動作を確かめる。
6. 小さなコミットに分けて積む。
7. 設計に異論があれば、複数のモデルにレビューさせる(`interrogate` スキル)。
8. PR を開く。

手順の多くは別のスキルを呼んでいます。プレイブックは、どのスキルをどの順で使うかを決めたものです。

プレイブックは Claude Code のスキルとしては登録されていません。Claude Code が自分で見つけることはなく、poteto-mode の対応表から開かれたときだけ使われます。

:::details コラム: プレイブックの一覧(23本)
分類は筆者によるものです。

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
:::

### 自分のプレイブックを足せる

v0.9.63 では、リポジトリの `.agents/playbooks/` に自分のプレイブックを置けます。一から書くこともできますが、同梱のプレイブックを土台にして、一部の手順だけを差し替える書き方ができます。

たとえば次のファイルは、feature プレイブックを土台に、Zenn の記事を扱うときの手順を変えます(筆者が試しに書いたもの)。

```markdown
---
extends: feature
when: Zenn の記事を追加・更新するとき
---

- **After** "Verify on the matching surface." `npx zenn preview` で表示を確かめる。
- **Replace** "Run **Opening a PR**." `published: false` のまま push して止まる。
```

`extends` に土台のプレイブック、`when` にどんな依頼で使うかを書きます。本文では、土台の手順の文言を `"..."` で引用し、その手順の後に足す(After)、置き換える(Replace)などを指定します。

:::details コラム: 引用した文言を検査するスクリプト
pstack を更新して土台の手順の文言が変わると、引用が合わなくなり、どこを差し替えるのか分からなくなります。そこで v0.9.63 には `check-playbooks.mjs` という検査スクリプトが入っています。poteto-mode は、自分のプレイブックを使う前にこれを実行し、出力をそのまま利用者に報告するよう定めています。node で動きます。

上の例を検査すると、通りました。

```
$ node <plugin>/skills/poteto-mode/scripts/check-playbooks.mjs .
Every project playbook matches this pstack's playbooks.
```

引用を土台に無い文言 `"Verify on the real screen."` に変えると、終了コード1で次の行が出ました。

```
.agents/playbooks/zenn-article.md: "Verify on the real screen." is not in any playbook it extends
```

なお、プラグインに同梱されたプレイブックを直接書き換えても、プラグインを更新すると別のバージョンのディレクトリに切り替わるので、変更は残りません。
:::

:::details コラム: プレイブック以外で手順を足す方法
- figure-it-out スキル。合うプレイブックが無いときに、そのタスク専用の手順をその場で組み立てます。使い捨てで、ファイルとしては残りません。
- 自分のスキルを書く。`~/.claude/skills/` に置けば Claude Code がそのまま読み込みます。automate-me スキルは、自分の作業の進め方を poteto-mode と同じ形の個人用スキルにまとめる手伝いをします。
:::

## 子エージェントへの仕事の割り振り(オーケストレーション)

親の Claude Code が子エージェントに仕事を割り振り、結果を集めて判断することを、ここではオーケストレーションと呼びます。pstack では、これがあちこちで起きています。専用の実行エンジンは無く、親が Claude Code の標準の機能で子エージェントを起動し、手順は Markdown に書いてあります。

代表的なスキルは次の2つです。

```
swarm  N体を一斉に起動 → 全員の終了を待つ → 結果を1本の報告にまとめる
arena  同じ課題をN体に解かせる → いちばん良い案を選ぶ → 他の案の良い部分を取り込む
```

ほかにも、調査を分担させる why、複数のモデルにレビューさせる interrogate などが子エージェントを使います。

### 何日もかかる案件だけは、進み具合をファイルに書き出す

swarm や arena では、子の結果を親が自分の会話の中に覚えておきます。1セッションで終わる規模なら、これで足ります。

何日もかかり、子エージェントが数十から数百体になる案件では、そうはいきません。会話に収まりきらず、途中で圧縮や再起動も起きます。そこで orchestrate プレイブックは、どの作業がどこまで進んだかをセッションの外のファイルに書き出し、`orch` というコマンドで管理します。

| | 進み具合の置き場所 | 続く期間 |
|---|---|---|
| swarm、arena など | 親の会話の中 | 1セッションの間 |
| orchestrate | セッションの外のファイル(orch コマンド) | 何日でも。セッションが変わっても続く |

orchestrate では、親は自分ではコードを書きません。親の仕事は、子に渡す依頼書を書き、子の結果を受け取って次を判断することです。

:::details コラム: orchestrate の決まりごと
依頼書には決まった項目があります。GOAL / SCOPE / CONTEXT / ACCEPTANCE / VERIFY / TIMEBOX / FORBIDDEN / REPORT / STANDING です。STANDING には、人間が決めた常設のルールをそのまま貼ります。項目を埋められない作業は起動しません。子は親に質問できないので、依頼書があいまいだと、黙って間違った方向に進むからです。

子の完了は、届いた順にその場で処理しません。プレイブックには次の一文があります。

> "Completions are queue events, not interrupts."
> (仮訳: 完了はキューのイベントであって、割り込みではない。)
>
> 出典: [pstack-claude](https://github.com/michael-denyer/pstack-claude) v0.9.63 の `skills/poteto-mode/playbooks/orchestrate.md`

完了の知らせはいったんファイルに溜め、親が決まったタイミングでまとめて処理します。

Claude Code の子エージェントはすべて同じマシンで動きます。そのため、子どうしが同じファイルを書き換えないよう、子ごとに git の worktree かブランチを分けます。
:::

## bun は要るか

普段の使い方なら要りません。poteto-mode、プレイブック、swarm、arena などは Markdown の指示だけで動きます。

bun が要るのは、補助のコマンドを使う一部のプレイブックだけです。orchestrate の `orch` コマンド、PR の監視、作業の中断と再開などがこれにあたります。これらは node では動かず、bun 以外で起動すると「requires bun」と表示して終了します。

:::details コラム: bun が要るスクリプトと動作確認
| スクリプト | 使うプレイブック |
|---|---|
| `orch/` | orchestrate |
| `watch-pr/` | babysit、shipping(PR の監視とマージ) |
| `check-plan.mjs` | multi-phase-plan |
| `resume.mjs` | pause-safely、session-pickup(作業の中断と再開) |
| `worktree-audit.mjs` | worktree-cleanup |

watch-pr は GitHub と `gh` コマンドを前提にしています。GitLab ではそのままでは動かないと筆者は見ていますが、中身を読んだうえでの推測です。

筆者は Linux と macOS の両方で `mise use -g bun@latest` により bun 1.4.2 を入れ、`bun orch/orch.ts --help` でヘルプが出ることを確かめました(Linux は v0.9.53、macOS は v0.9.63)。初回の起動時に、依存パッケージが自動で入りました。

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

orch が書き出すファイルの置き場所は、プレイブックの記述では `~/.claude/orchestrate/<project-slug>/` です。Claude Code の設定ディレクトリを `CLAUDE_CONFIG_DIR` で変えている場合は、`--store` オプションか環境変数 `ORCH_STORE` で場所を指定します。
:::

## なぜ「スタック」なのか

1つ目の読み方は、前に書いた「スキルのスタック」です。指示書を層に積み、上から順に必要な分だけ読ませます。

プレイブックを読むと、もう1つの読み方が見えてきます。「PR のスタック」です。

PR のスタックは、大きな変更を1本の PR にまとめず、小さな PR に分けて、前の PR の上に次の PR を積んでいく作り方です。レビューする人は1本ずつ読めます。マージも下から順に進めます。

pstack のプレイブックは、成果をこの形で出すように書かれています。

- feature プレイブックの手順6は、変更を小さく順序のあるコミットに分け、続きの作業は上に積むよう求めています。
- shipping プレイブックは、確かめ終わった PR を下から順にマージします。
- autopilot-stack プレイブックは、確かめた変更を1本の積み重なった PR の列にして、人間に渡します。名前にも stack が入っています。
- orchestrate の `orch` コマンドは、マージを進める境目を「Graphite stack frontier」として管理します。Graphite は PR のスタックを扱うツールです。

この作り方の根には、原則 `principle-sequence-verifiable-units` があります。作業を小さな単位に分け、1つずつ確かめてから次に進み、確かめた順に積む、という原則です。たとえば、まず失敗するテストの PR を置き、その上に修正の PR を積みます。こうすると、積んだ順番そのものが「この修正は効いている」という証拠になります。

2つの読み方は、同じ考え方の表と裏です。エージェントへの指示は層に積み、上の層は下の層を必要なときだけ呼びます。エージェントの成果は小さな単位で積み、下から1つずつ確かめます。どちらも「一度に全部を扱わず、確かめられる単位で積む」という点で共通しています。

名前の由来を作者が説明した文章は、筆者が調べた範囲では見つかっていません。「p」は作者の名前 poteto から取ったものと推測しますが、確かめてはいません。ここに書いた2つの読み方は、中身から筆者が読み取ったものです。

:::details コラム: 「stack」という語の使われ方
v0.9.63 のスキル群を grep すると、"the stack" が19回、"a stack" が9回、"stacked PRs" が4回、"PR stack" が2回出てきました。Graphite という語も16回出てきます。筆者が読んだ箇所では、「stack」はどれも PR のスタックの意味でした。一方、"skill stack" という語はスキル群には1回も出てこず、移植版の README の1文にあるだけでした。
:::

## 読んで参考になったこと

自分でスキルやフックを書く立場で参考になったのは、「指示を書くだけでは守られない」ことを前提に、守らせる工夫を重ねている点です。

- 手順を TODO に写させ、飛ばした手順も理由付きで残させる。
- 本文を読んでいない原則は、返答で名前を出させない。
- 子の報告の形式を決め、必要な項目が欠けた報告はやり直させる。
- 長い案件の進み具合は、会話ではなくファイルに書き出す。
- 自分のプレイブックが引用する手順の文言は、スクリプトで照合する。

pstack 自身も、この考え方を原則として持っています。`principle-encode-lessons-in-structure` は、同じ指示を2回書くことになったら、文章を足すのではなく、lint やスクリプトのような仕組みに置き換えよ、という原則です。

:::details コラム: 「同じことを2回書いたら仕組みにせよ」の中身
この原則は、置き換え先として強い順に、型で間違った状態を作れなくする、lint で CI を落とす、共通の関数にまとめる、実行時にチェックする、を挙げています。文章で残してよいのは、判断が要って仕組みにできないときだけです。

学びの残し先も分けています。

- 1回限りのこと → メモ
- 繰り返し起きる修正 → スキルか lint
- 根の深い問題 → 原則

この原則で見ると、プレイブックは「文章で残す」側です。そのため pstack は、TODO への書き写しや検査スクリプトで、プレイブックの文章を補っています。

会話から学びを拾ってスキルの修正につなげるスキルとして reflect があります。会話を3体の子エージェントに読ませ、見つかった学びを、既存のスキルへの具体的な修正案にします。
:::

最後に注意点を1つ挙げます。poteto-mode には「元に戻せる作業は確認せずに進める」という方針があります。自分の CLAUDE.md に「〜の前には確認を取る」というルールを書いている場合は、どちらを優先させるかを決めておく必要があります。
