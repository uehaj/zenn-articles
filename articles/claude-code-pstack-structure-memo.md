---
title: "【メモ】pstack (Claude Code 移植版pstack-claude) のスタック構成とオーケストレーションを読む"
emoji: "🥔"
type: "tech"
topics: ["claudecode", "agentskills", "aiエージェント", "pstack", "mattpocock"]
published: true
---

:::message
本記事は筆者個人の見解であり、所属する組織の公式見解ではありません。

また、ここで扱う pstack はコミュニティによる移植版のプラグインで、更新が頻繁です。本文の記述は執筆時点(2026年10月, pstack-claude v0.9.63 / Claude Code v2.1.288 で確認)のものなので、最新の構成は[リポジトリ](https://github.com/michael-denyer/pstack-claude)をご確認ください。
:::

## はじめに

[pstack-claude](https://github.com/michael-denyer/pstack-claude) は、Claude Code に「仕事の進め方」を教えるプラグインです。Lauren Tan (poteto) さんが Cursor 向けに作ったスキル群 pstack を、Claude Code 向けに移植したものです(出典: [pstack-claude の README](https://github.com/michael-denyer/pstack-claude))。元の pstack は [cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack) にあります。

pstack が注目されている理由は、その実行力です。何時間も止まらずに動き続け、これまでのエージェントでは手に負えなかった高難度で大規模な修正を、時間をかけてでもやり遂げてしまいます。元の pstack の README も、`/poteto-mode` を Cursor の `/loop` コマンドと組み合わせると、次のように使えると書いています。

> "you can make cursor work for many hours without sacrificing rigor."
> (仮訳: 厳密さを犠牲にせずに、Cursor を何時間も働かせられる。)
>
> 出典: [cursor/plugins の pstack の README](https://github.com/cursor/plugins/tree/main/pstack)

数日がかりで、子エージェントを数十から数百体動かす案件のための手順書(orchestrate)まで入っています。もちろん、普段使いのちょっとした作業でも精度が上がります。

使い方のイメージをつかむために、典型的な頼み方を1つ挙げます。Claude Code では、`/pstack:poteto-mode` に続けてやりたいことを書きます。

```
/pstack:poteto-mode チケット #1、#2、#3 を実装して、それぞれ PR を作り、レビューして問題がなければマージして
```

依頼の中身に合わせて poteto-mode がプレイブックを選び、調査、設計、実装、確認、PR の作成と見張りまでを進めます。マージのように元に戻せない操作は、頼まれたときだけ行います。

この記事では、それを支える pstack の部品と動き方を、中身を読んで調べた範囲でまとめます。

:::message
**Claude Code へのインストール方法**

pstack-claude は、Michael Denyer 氏による pstack の Claude Code での非公式移植版です。元の pstack の更新を定期的に取り込みながら、次のような点について Claude Code 上でも動作するように変更されています。

- ツールの呼び出し方: Cursor の `Task` ツールを Claude Code の `Agent` ツールに、`AskQuestion` を `AskUserQuestion` に置き換え。エージェント名には `pstack:` を付ける。
- 子エージェントの動かし方: Cursor のクラウド上のエージェントの代わりに、手元のバックグラウンドの子エージェントを使い、書き込む子ごとに git の worktree を分ける。
- 設定と記録の置き場所: `~/.cursor/rules/pstack-models.mdc` を Claude Code の設定ディレクトリの `pstack-models.md` に、会話記録の場所を `~/.claude/projects/` に置き換え。
- モデル名: Cursor で選ぶモデル名を、Claude の opus / fable / sonnet などに置き換え。
- Cursor にしかない機能の代わり: Cursor の `/loop` コマンドは Claude Code の loop スキルで、`/goal` は依頼書に目標を書くことで、Cursor 組み込みの babysit やスキル作成機能は同梱のスキルや plugin-dev で置き換え。Claude Code には Cursor の推論量の指定の仕組みも無く、移植版は effort 別のエージェント定義を用意している(両者を結びつけたのは筆者の読み)。
- 移植版独自の方針変更: たとえば autopilot-full では、各 PR をマージするのは人間にしている。

(出典: [pstack-claude](https://github.com/michael-denyer/pstack-claude) の `CONTRIBUTING.md`、置き換え規則を並べた `tools/substitutions.json`、元との違いを記録した `tools/forks.json`)

プラグインのマーケットプレイスとして配布されているので、Claude Code の中で次の2つを実行します。

```
/plugin marketplace add michael-denyer/pstack-claude
/plugin install pstack@pstack-claude
```

インストール後に Claude Code を再起動すると、`/pstack:poteto-mode` などのスキルが使えるようになります。更新は `claude plugin update pstack@pstack-claude` です。役割ごとのモデルを選びたいときは `/pstack:setup-pstack` を実行します。

マーケットプレイス名 `pstack-claude` とプラグイン名 `pstack` は、リポジトリの `.claude-plugin/marketplace.json` で確認しました。
:::

:::message
**動作に必要なもの**

Claude Code があれば、pstack の大半(poteto-mode、ほとんどのプレイブック、swarm、arena など)はそのまま動きます。次のものは、使う機能に応じて追加で入れます(出典: [pstack-claude の docs/reference.md](https://github.com/michael-denyer/pstack-claude/blob/main/docs/reference.md))。

| 必要なもの | 要る場面 |
|---|---|
| Bun | 何日もかかる案件を orchestrate で進めるとき(`orch`)と、GitHub の PR を見張るとき(`watch-pr`) |
| GitHub CLI(`gh`) | PR の見張りとマージ。`gh auth login` で認証しておく |
| Graphite CLI(`gt`) | orchestrate プレイブックで PR の積み重ねを扱うとき |
| `plugin-dev` プラグイン | スキルを書く手伝いをする automate-me、reflect などを使うとき |

bun はいちばん引っかかりやすい依存です。`orch` と `watch-pr` は bun でしか動かず、Node.js では代わりになりません。bun 以外で起動すると「requires bun」と表示して終了します。逆に、この2つを使わないなら bun は要りません。入れ方は [Bun 公式サイト](https://bun.sh) にあります。筆者は `mise use -g bun@latest` で入れました。初回の起動時に、スクリプトが使うパッケージは自動で入ります。

なお、プレイブックの検査や作業の中断・再開に使う補助スクリプトは、Node.js で動きます。
:::

## TL;DR

- pstack は、何時間も動き続けて高難度で大規模な修正をやり遂げてしまう実行力で注目されています。
- pstack で Claude Code の振る舞いを決めているのは、Markdown の指示書です。プログラムもテストを除いて約7,900行あり、行数では指示書より多いほどですが、普段の使い方では呼ばれない補助のコマンドです。
- 依頼を受けると、pstack は仕事の種類(バグ修正、機能追加など)に合う手順書を選び、その手順どおりに進めます。この手順書を「プレイブック」と呼びます。
- 作業の一部は子エージェントに任せます。子エージェントにも同じ手順書と決まりを読ませて、同じ進め方をさせます。
- 何日もかかる大きな案件だけは、進み具合をファイルに書き出して管理します。そのためのコマンドと、GitHub の PR を見張るコマンドには bun が必要です。
- pstack は、エージェントの協調、原則、プレイブック、利用者が呼ぶスキルを層に積んだ設計です。名前の由来は説明されていませんが、この階層化された設計にあるのではないでしょうか。
- 元に戻せる作業は人間に確認せずに進め、勝手に決めたことは記録して最後に報告します。作業の前に計画を詰める grilling とは、扱う段階が違います。

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

poteto-mode には、仕事の種類ごとにどのプレイブックを使うかの対応表があります。「バグ修正なら bug-fix」「機能追加なら feature」のように、合うプレイブックを1つ選びます。

Claude Code は、選んだプレイブックの手順を TODO リストにそのまま写します。やらないと決めた手順も消さず、「skip: 理由」を付けて残します。後から見た人が、どの手順を飛ばしたかを確かめられるようにするためです。

### 3. 必要になった原則だけを読む

```
poteto-mode
  ├─ プレイブック(手順書)
  └─ 原則の一覧(名前と「いつ使うか」を1行ずつ)
        └─> 原則ごとのスキル(使うときだけ全文を読む)
```

pstack には、「根本原因を直せ」「作ったら実物で確かめよ」のような原則が23個あります。poteto-mode には原則の名前と、いつ使うかの1行だけが載っています。本文は原則ごとに別のスキルに分けてあり、使うときだけ読みます。全部を最初から読ませると、Claude Code が一度に扱える文章の量(コンテキスト)を無駄に使うためだと筆者は見ています。

返答では、どの原則に従ったかを書かせます。ただし書いてよいのは、そのセッションで本文を読んだ原則だけです。読んでいない原則をもっともらしく持ち出すのを防ぐ決まりです。

### 4. 作業の一部を子エージェントに任せる

```
Claude Code(親)
  │ 「この修正を実装して」
  v
子エージェント ──「まず poteto-mode を読め」──> poteto-mode
```

プレイブックには「実装は子エージェントに任せる」のような手順があります。ところが子エージェントは親の会話を見ないまま起動するので、親が読んだ poteto-mode のことも知りません。そこで pstack は、子エージェントの定義ファイルに「作業の前に poteto-mode を全文読め」と書いています。定義ファイルの中身は、ほぼこれだけです。進め方を書く場所が poteto-mode の1か所で済み、親と子が同じ進め方で動きます。

ここまでの1から4を振り返ると、指示書が層になっています。セッション開始時の短い指示、poteto-mode、プレイブック、原則、子エージェントの定義です。上の層は下の層を名前で呼び出し、中身は必要になるまで読みません。名前の「スタック」との関係は、後の「なぜ『スタック』なのか」で書きます。

:::details 詳しく: 子エージェントのモデルと effort の指定
子エージェントを起動するときは、どのモデルを使うかを毎回指定します。役割ごとの既定値は `models.json` にあり、たとえばバグ修正には最も強いモデル(fable)、機能追加には標準のモデル(opus)を使います。利用者は `pstack-models.md` というファイルで役割ごとに上書きでき、`opus @xhigh` のようにモデルと推論の強さ(effort)を一緒に指定できます。

effort ごとに中身が同じエージェント定義が10本あり、違いは frontmatter の `effort: high` などだけです。Claude Code で子エージェントを起動するときに effort を渡す引数が無く、エージェント定義でしか変えられないためだと筆者は推測しています。設計の経緯は確かめていません。

arena、architect、interrogate の3つは、opus / fable / sonnet の3モデルを並べて使います。arena と architect は同じ課題に別々の案を出させ、interrogate は設計を別々のモデルにレビューさせます。互いの見落としを拾うためです。
:::

:::message
**寄り道: フックを止める方法**

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

:::details 詳しく: プレイブックの一覧(23本)
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

`"..."` でくくった "Verify on the matching surface." と "Run **Opening a PR**." は、feature プレイブックの手順の文言をそのまま引用したものです(出典: [pstack-claude](https://github.com/michael-denyer/pstack-claude) v0.9.63 の `skills/poteto-mode/playbooks/feature.md` の手順5と手順8)。

`extends` に土台のプレイブック、`when` にどんな依頼で使うかを書きます。本文では、土台の手順の文言を `"..."` で引用し、その手順の後に足す(After)、置き換える(Replace)などを指定します。

:::details 詳しく: 引用した文言を検査するスクリプト
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

:::message
**寄り道: プレイブック以外で手順を足す方法**

- figure-it-out スキル。合うプレイブックが無いときに、そのタスク専用の手順をその場で組み立てます。組み立てた手順と判断の記録は残しますが、次回も使えるプレイブックとして `.agents/playbooks/` に保存されるわけではありません。
- 自分のスキルを書く。`~/.claude/skills/` に置けば Claude Code がそのまま読み込みます。automate-me スキルは、自分の作業の進め方を poteto-mode と同じ形の個人用スキルにまとめる手伝いをします。
:::

## 子エージェントへの仕事の割り振り(オーケストレーション)

親の Claude Code が子エージェントに仕事を割り振り、結果を集めて判断することを、ここではオーケストレーションと呼びます。pstack では、これがあちこちで起きています。プレイブックの手順や poteto-mode の決まりが、子エージェントを使うスキルを呼ぶので、利用者が個々のスキルを指定しなくても、必要なところで子エージェントへの割り振りが起きます。専用の実行エンジンは無く、親が Claude Code の標準の機能で子エージェントを起動し、手順は Markdown に書いてあります。

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

orchestrate では、親は自分ではコードを書きません。自分でするのは、確かめ終わった子の作業を取り込むところまでです。親の仕事は、子に渡す依頼書を書き、子の結果を受け取って次を判断することです。

:::details 詳しく: orchestrate の決まりごと
依頼書には決まった項目があります。GOAL / SCOPE / CONTEXT / ACCEPTANCE / VERIFY / TIMEBOX / FORBIDDEN / REPORT / STANDING です。STANDING には、人間が決めた常設のルールをそのまま貼ります。項目を埋められない作業は起動しません。子は親に質問できないので、依頼書があいまいだと、黙って間違った方向に進むからです。

子の完了は、届いた順にその場で処理しません。プレイブックには次の一文があります。

> "Completions are queue events, not interrupts."
> (仮訳: 完了はキューのイベントであって、割り込みではない。)
>
> 出典: [pstack-claude](https://github.com/michael-denyer/pstack-claude) v0.9.63 の `skills/poteto-mode/playbooks/orchestrate.md`

完了の知らせはいったんファイルに溜め、親が決まったタイミングでまとめて処理します。

Claude Code の子エージェントはすべて同じマシンで動きます。そのため、子どうしが同じファイルを書き換えないよう、子ごとに git の worktree かブランチを分けます。
:::

## 補助のコマンドと bun

ここまで見てきたとおり、pstack で Claude Code の振る舞いを決めているのは Markdown の指示書です。ただし、プログラムも入っています。しかも少なくありません。テストを除いて約7,900行あり、Markdown の指示書(約6,100行)より多いほどです。内訳は次のとおりです(v0.9.63、筆者の集計)。

| 中身 | 行数 | 動かすもの |
|---|---|---|
| PR の状態の見張りとマージ(`watch-pr`) | 3,299 | bun |
| 長い案件の進み具合の管理(`orch`) | 2,214 | bun |
| Pi(Claude Code とは別のエージェント実行環境)向けの拡張 | 1,490 | Pi |
| その他の補助スクリプト(計画の検査、中断と再開、worktree の点検、プレイブックの検査、会話記録の検索、フックなど) | 921 | node、sh |
| 合計 | 7,924 | |

このうち `watch-pr` と `orch` の2つを動かすには、bun が必要です。

bun は、JavaScript や TypeScript のプログラムを動かす実行環境です。Node.js と同じ役割のソフトで、TypeScript のファイルをそのまま実行できます(出典: [Bun 公式サイト](https://bun.sh))。

この2つについては、Node.js が入っていても代わりにはなりません。bun にしかない機能を使って書かれているからです。起動時に読まれる `bootstrap.ts` は、bun 以外で起動されると「requires bun」と表示してすぐ終了します。そのほかの補助スクリプトは node で動きます。

では、bun が要るコマンドはいつ呼ばれるのか。普段の使い方では呼ばれません。poteto-mode、ほとんどのプレイブック、swarm、arena などは、Markdown の指示だけで動きます。呼ばれるのは次の2つの場面だけです。

- 何日もかかる案件を orchestrate で進めるとき(`orch`)
- babysit や shipping で GitHub の PR の状態を見張るとき(`watch-pr`)

つまり、こうした使い方をしないなら bun を入れなくても困りません。使うときになったら入れれば足ります。

:::details 詳しく: 補助スクリプトの一覧と動作確認
| スクリプト | 使うプレイブック | 動かすもの |
|---|---|---|
| `orch/` | orchestrate | bun |
| `watch-pr/` | babysit、shipping(PR の見張りとマージ) | bun |
| `check-plan.mjs` | multi-phase-plan | node |
| `resume.mjs` | pause-safely、session-pickup(作業の中断と再開) | node |
| `worktree-audit.mjs` | worktree-cleanup | node |
| `check-playbooks.mjs` | 自分のプレイブックの検査 | node |

`watch-pr` は GitHub 専用です。babysit プレイブックにも、公開している見張り役は GitHub 専用だと書かれています(`skills/poteto-mode/playbooks/babysit.md`)。

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

orch コマンド自体には、ファイルの置き場所の既定値がありません。毎回 `--store` オプションか環境変数 `ORCH_STORE` で指定します。orchestrate プレイブックは、置き場所を `~/.claude/orchestrate/<project-slug>/` に作るよう指示しています。
:::

## なぜ「スタック」なのか

ここまでの部品を、下から順に並べ直すと次のようになります。

```
4. ユーザーが呼ぶスキル   /pstack:poteto-mode、/pstack:tdd、/pstack:how など
3. プレイブック           bug-fix、feature、orchestrate など23本
2. 原則                   principle-* の23本
1. エージェントの協調     子エージェントの定義、役割ごとのモデル、swarm・arena、orch
```

いちばん下は、エージェントどうしを協調させる層です。子エージェントの定義、役割ごとに使うモデルの表、複数の子を一斉に動かす swarm や arena、長い案件の進み具合を管理する orch が、ここに入ります。

その上に原則が載ります。原則は「根本原因を直せ」「作ったら実物で確かめよ」のような判断の基準です。23本すべてが、frontmatter に `user-invocable: false` と書かれています。利用者がコマンドとして呼ぶものではなく、上の層から読まれるためのものです。

さらにその上にプレイブックが載ります。プレイブックは、原則を引用し、下の層の部品を順に使う手順書です。

いちばん上が、利用者がコマンドとして呼ぶスキルです。`/pstack:poteto-mode` を呼ぶと、仕事に合うプレイブックが選ばれ、プレイブックが原則を読み、子エージェントに仕事を割り振ります。

移植版の README(v0.9.63 に同梱のもの)は pstack を "an opinionated skill stack"(仮訳: 考え方のはっきりしたスキルのスタック)と呼んでいます(出典: [pstack-claude の README](https://github.com/michael-denyer/pstack-claude))。名前の由来は説明されていませんが、このように階層化された設計になっていることにあるのではないでしょうか。

## 読んで参考になったこと

自分でスキルやフックを書く立場で参考になったのは、「指示を書くだけでは守られない」ことを前提に、守らせる工夫を重ねている点です。

- 手順を TODO に写させ、飛ばした手順も理由付きで残させる。
- 本文を読んでいない原則は、返答で名前を出させない。
- 子の報告の形式を決め、必要な項目が欠けた報告はやり直させる。
- 長い案件の進み具合は、会話ではなくファイルに書き出す。
- 自分のプレイブックが引用する手順の文言は、スクリプトで照合する。

pstack 自身も、この考え方を原則として持っています。`principle-encode-lessons-in-structure` は、同じ指示を2回書くことになったら、文章を足すのではなく、lint やスクリプトのような仕組みに置き換えよ、という原則です。

:::details 詳しく: 「同じことを2回書いたら仕組みにせよ」の中身
この原則は、置き換え先として強い順に、型で間違った状態を作れなくする、lint で CI を落とす、共通の関数にまとめる、実行時にチェックする、を挙げています。文章で残してよいのは、判断が要って仕組みにできないときだけです。

学びの残し先も分けています。

- 1回限りのこと → メモ
- 繰り返し起きる修正 → スキルか lint
- 根の深い問題 → 原則

この原則で見ると、プレイブックは「文章で残す」側です。そのため pstack は、TODO への書き写しや検査スクリプトで、プレイブックの文章を補っています。

会話から学びを拾ってスキルの修正につなげるスキルとして reflect があります。会話を3体の子エージェントに読ませ、見つかった学びを、既存のスキルへの具体的な修正案にします。
:::

## 先に聞くか、やってから直すか

pstack を読んでいちばん考えさせられたのは、人間に確認を取るタイミングについての方針です。

poteto-mode には「元に戻せる作業は、確認せずに進める」という方針があります。原則 `principle-never-block-on-the-human` によれば、**元に戻せる作業は人間の確認を待たずに進め、結果を見せて、間違っていれば人間に後から直してもらいます**。確認を取るのは、強制 push や本番データの削除、外部へのメッセージ送信のように、元に戻せない操作のときだけです。poteto-mode 本体はこの原則よりさらに踏み込んでいて、チームチャットへの投稿やチケットの更新も確認なしで進め、止めるのは顧客へのメッセージなどに限っています。原則は理由として、確認のたびに作業が止まり人間が待ちの原因になること、コードの変更は元に戻せてレビューもできるので、判断を誤っても止めて待つより損が小さいことを挙げています。

筆者は以前の記事で、mattpocock/skills の grilling を取り上げました。grilling は、作業の前に計画を質問攻めにして、決められることは先に決めておく、というスキルです。grilling が扱うのは着手前の計画で、pstack のこの方針が扱うのは作業を進めている途中の判断です。扱う段階が違います。

- [計画を質問攻めで鍛えるgrillingを解剖する：フロンティア式ラウンドと、実は保存されていない決定木](https://zenn.dev/uehaj/articles/grilling-frontier-design-tree)

筆者は以前、「事前に決められることは決めるべきだ」と考え、grilling を信じていました。しかし、筆者自身は grilling の質問攻めに嫌気がさしました。よく考えると、grilling は「計画に何が足りないか」を探して質問しているだけです。その質問が、本当に人間に聞くべきものだという保証はありません。上の記事でも、この点を書きました。

pstack は、作業の途中で出てくる判断を次のように扱います。AI が知っていること、スキルに書かれた知見、考えられる論理的な可能性をとことん検討します。「やってみないと分からない」ものは、作業を進めながら決めていきます。直せるものは、あとで確認して直します。

ただし、勝手に決めっぱなしにはしません。決めたことは記録に残し、最後に報告します。

- 自分で決めた判断は、show-me-your-work スキルで「何を・なぜ・根拠・結果」を1行ずつ記録に残します。
- 人間にしか決められない判断を、全面的に任された作業の途中で迫られたときは、既定の選択をして先に進みます。そのうえで、何をなぜそう決めたかと、一言で取り消せる方法を添えて報告します(poteto-mode の Non-negotiables)。
- 人間に聞く前に、それが実際に動かせば分かることかを見分けます。分かることなら、聞かずに小さく試して結果で決めます。人間に聞くのは、試しても答えが出ない、製品の方向や好みの判断だけです(同じく poteto-mode)。

人間から見ると、「ここは勝手に決めました。問題があれば直すので言ってください」という報告が最後に届くことになります。

grilling は、人間が答える前に AI が質問を選びます。pstack は、AI が作ったものを見たあとで、人間が直すところを選びます。人間の手間の中心が、答えることから、見て直すことに移ります。ただし pstack も、製品の方向や好みの判断は人間に聞くので、答える手間がなくなるわけではありません。

この方針が正しいかどうかは、手探りで探索中です。ただ、grilling に対して抱いていた「質問に答える労力に見合わないのではないか」という疑問には、1つの答えになっていると思います。筆者にとっては、grilling よりずっと受け入れやすい考え方です。

自分の CLAUDE.md に「〜の前には確認を取る」というルールを書いている場合は、pstack の方針とぶつかります。pstack の SessionStart フックは、CLAUDE.md などの利用者の指示が優先すると明記しています。なので建前では CLAUDE.md が勝ちます。ただし poteto-mode 本体の Autonomy 節には、この優先順位は書かれていません。実際にどちらに従うかは、試して確かめる必要があります。
