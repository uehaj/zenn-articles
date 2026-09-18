---
title: "そのプロンプト、どのプロジェクトに投げるんでしたっけ — そうだ、Jevで宛先を決めよう"
emoji: "🚦"
type: "tech"
topics: ["claudecode", "herdr", "aisdk", "typescript", "jev"]
published: false
---

:::message
本記事は筆者個人の見解であり、所属する組織の公式見解ではありません。

また、ここで使う AI SDK の `experimental_evaluate` は名前のとおり experimental な API です。この領域は仕様が頻繁に、かつ大きく変わります。本文の記述は執筆時点(2026年9月, herdr 0.9.0 / ai 7.0.106 / Node v23.10.0 で確認)のものなので、最新の挙動は[公式ドキュメント](https://ai-sdk.dev/docs/ai-sdk-core/evaluation)をご確認ください。
:::

## はじめに

AI エージェントを複数のプロジェクトで並行して走らせていると、ワークスペースが増えます。筆者の手元では、社内ツールの障害調査、別プロダクトの改修、記事の下書き、実験用の使い捨てディレクトリ……といった具合に、常時 5〜10 個が開きっぱなしです。

この状態で困るのが、**思いついたことを書き留めたいときに、宛先を自分で選ばないといけない**ことです。「さっきのエラー、設定ファイルのほうも疑ったほうがよさそう」と思いついたとして、それを打ち込むべきペインがどれだったかを思い出し、そこまで移動してから入力する。移動の時点で、何を書こうとしていたか半分忘れています。

やりたいことはシンプルで、ショートカッットキーでコマンドパレットを表示させ、**プロンプトを 1 箇所で書いたら、内容から自動で宛先が決まり、そのペインの入力欄に入る**という状態です。

![herdr のポップアップに出したプロンプトパレット。ここに書くと宛先が自動で決まる (筆者の実行環境のスクリーンショット)](/images/jev-prompt-router-palette.png)

このとき、宛先のワークスペースを判断する必要がありますが、分類タスクですから、いま話題の**意思決定モデル [Jev](https://vercel.com/ai-gateway/models/jev)** を使います。

## TL;DR

- 複数の herdr ワークスペースのうち、どこに送るべきかを **TypeSafe AI の Jev（評価モデル）** に選ばせるルータを書きました。TypeScript で 56 行です。
- Jev は文章を生成せず、**typed な質問に対して選択肢・スコア・真偽確率だけを返す**モデルです。AI SDK 7 の `experimental_evaluate` から呼べます。
- 今回、候補の作り方が肝で、**`criteria` のキーを機械用の ID、値を LLM 用の説明文**にすると、返ってきた答えをそのままキーとして使えます。
- 最後に Enter は打ちません。**入力欄に文字列を置くだけ**にして、送信するかどうかの判断は人間に残しています。

## なぜ生成モデルではなく評価モデルなのか

Jev は 2026年9月16日に Vercel AI Gateway で使えるようになったモデルです。Vercel の changelog では次のように紹介されています。

> a probabilistic decision model for software: state goes in, typed Choice, Score, and Boolean answers come out.

(仮訳: ソフトウェアのための確率的な意思決定モデル。状態を入れると、型のついた Choice・Score・Boolean の答えが出てくる)

出典: [TypeSafe AI's Jev now available on AI Gateway — Vercel Changelog](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway)

AI Gateway のモデルページによれば、Jev の最大出力トークン数は **0** で、コンテキストウィンドウの欄は「該当なし」です（出典: [Jev — Vercel AI Gateway](https://vercel.com/ai-gateway/models/jev)）。文章を書かないので、出力トークンという概念がそもそもありません。入力の料金は 100 万トークンあたり 0.042 ドルです。

分類のためだけに生成モデルを呼ぶと、「JSON で答えて」とプロンプトに書き、返ってきた文字列をパースし、想定外のキーが来たときのリトライを書く、という定型作業がついてきます。評価モデルはその層がまるごと要りません。選択肢の集合を渡せば、その中のどれかが返ってきます。

TypeSafe 社の報告として、Vercel は「自社のワークフロー評価において LLM 比で最大 193.6 倍高速・444.6 倍安価」という数字を紹介しています（同 changelog）。これは同社自身の測定値であり、筆者が検証したものではありません。ただ、今回のような「1 プロンプトにつき 1 回、選択肢 10 個弱から 1 つ選ぶ」規模であれば、速度も費用も気にする水準ではありません。

## 全体の処理フロー

```text
プロンプト (argv または対話入力)
        │
        ├── herdr agent list ─→ ワークスペースごとに代表ペインを 1 つ選ぶ
        │                        candidates: workspace_id → { pane_id, label }
        ▼
 experimental_evaluate
   model: 'typesafe-ai/jev'
   state: プロンプト
   questions.workspace: { type: 'choice', criteria: 候補一覧 }
        │
        ▼
   answers.workspace.choice = workspace_id
        │
        ├── DRY があればここで終了 (判定だけ)
        ▼
 herdr workspace focus → agent focus → pane send-text → notification show
```

## コード全文

`route.mts` の全文です。依存は `ai` パッケージ 1 本だけです。

```ts
import { execFileSync } from 'node:child_process';
import { basename } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { experimental_evaluate as evaluate } from 'ai';

let prompt = process.argv.slice(2).join(' ').trim();
if (!prompt) {
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  prompt = (await rl.question('prompt (empty to cancel)> ')).trim();
  rl.close();
}
if (!prompt) process.exit(2);

const herdr = (...args: string[]) => {
  const out = execFileSync('herdr', args, { encoding: 'utf8' }).trim();
  return out ? JSON.parse(out).result : null; // send-text answers with nothing
};

// 1 pane per workspace: prefer one that is not mid-turn.
const candidates = new Map<string, { pane_id: string; label: string }>();
for (const a of herdr('agent', 'list').agents) {
  if (candidates.has(a.workspace_id) && a.agent_status === 'working') continue;
  candidates.set(a.workspace_id, {
    pane_id: a.pane_id,
    label: `${basename(a.cwd)} — ${a.terminal_title_stripped}`,
  });
}

const { answers } = await evaluate({
  model: 'typesafe-ai/jev',
  state: prompt,
  questions: {
    workspace: {
      type: 'choice',
      instructions: 'Which project should this prompt be sent to?',
      criteria: Object.fromEntries([...candidates].map(([id, c]) => [id, c.label])),
    },
  },
});

const wid = answers.workspace.choice;
const target = candidates.get(wid)!;
console.error(`-> ${wid} ${target.label} (${target.pane_id})`);
console.error(answers.workspace.probabilities);

if (process.env.DRY) process.exit(0);

herdr('workspace', 'focus', wid);
herdr('agent', 'focus', target.pane_id);
herdr('pane', 'send-text', target.pane_id, prompt.replace(/\r?\n/g, ' '));
herdr('notification', 'show', `-> ${target.label}`, '--sound', 'none');
```

`tsx` や `ts-node` は入れていません。`tsconfig.json` も置いていないため、型注釈は実行時に捨てられるだけで型検査は走っていません。

## ポイント解説

UIですが、Claude Codeの新機能Claude Modsをつかうことも考えましたが、ワークスペースがきりかわったほうがいいのでHerdr連携にしました。Claude Modsだけなら[Cross Sesssion Messaging](https://code.claude.com/docs/en/cross-session-messaging)でプロンプトを送り合うみたいな実装にもできるでしょう。

### 1. herdr の状態を読む

herdr は AI エージェント向けのターミナルマルチプレクサで、ペインやワークスペースをソケット API 越しに操作する CLI を持っています。`herdr agent list` は次のような JSON を返します（パスとタイトルはマスクしています）。

```json
{
  "id": "cli:agent:list",
  "result": {
    "agents": [
      {
        "agent": "claude",
        "agent_status": "idle",
        "cwd": "/Users/<user>/work/<project>",
        "focused": false,
        "pane_id": "w68:p1",
        "tab_id": "w68:t1",
        "terminal_title_stripped": "<project>",
        "workspace_id": "w68"
      }
    ]
  }
}
```

ラッパ関数が `.result` を剥がしているので、呼び出し側は `herdr('agent','list').agents` と書けます。

`execSync` ではなく `execFileSync` を使っているのが地味に重要です。シェルを経由しないので引数は配列のまま渡り、プロンプトに `;` や `$(...)` が含まれていてもシェル注入になりません。最後の行でユーザー入力をそのまま引数に渡せているのはこのためです。

`pane send-text` は標準出力に何も返さないので、空文字のときは `JSON.parse('')` を避けて `null` を返しています。

### 2. ワークスペースごとに候補を 1 つに絞り込む

herdr は 1 つのワークスペースに複数のエージェントペインを持てます。一方、選ばせたい粒度はあくまで「プロジェクト単位」です。選択肢が多すぎると分類精度が落ちますし、同じプロジェクトの別ペインが並んでいても人間には区別がつきません。そこで、ワークスペース単位に情報を畳み込みます。

```ts
if (candidates.has(a.workspace_id) && a.agent_status === 'working') continue;
```

この 1 行は「すでに候補がいて、かつ今見ているのが `working`」のときだけスキップする、という後勝ちのロジックです。挙動を表にするとこうなります。

| 既存の候補 | 今評価しているエージェント | 結果 |
|---|---|---|
| なし | idle | 登録される |
| なし | **working** | **登録される**（最初の 1 件は状態を問わない） |
| あり | idle | 上書きされる（後勝ち） |
| あり | working | スキップされ、既存候補が温存される |


`label` は `${basename(cwd)} — ${terminal_title_stripped}` で組み立てています。フルパスだとノイズが多いので `basename` で畳み、ステータス記号を除いたターミナルタイトルで「いま何をしているか」を足しています。**これが分類モデルに見せる唯一の説明文**です。

### 3. criteria のキーと値で役割を分ける

`choice` 型でいちばん効いているのがここです。

```ts
criteria: Object.fromEntries([...candidates].map(([id, c]) => [id, c.label])),
```

公式ドキュメントでは `choice` の `criteria` は "A nonempty map of options to descriptions"（仮訳: 選択肢から説明への、空でないマップ）と説明されています（出典: [Evaluation — AI SDK Core](https://ai-sdk.dev/docs/ai-sdk-core/evaluation)）。このキーと値で、役割をきれいに分けられます。

| 位置 | 中身の例 | 役割 |
|---|---|---|
| **キー** | `"w68"` などの `workspace_id` | 選択肢の識別子。判定後に `answers.workspace.choice` としてそのまま返る |
| **値** | `"<project> — エラー切り分け"` | その選択肢の具体的な説明。モデルが読み取るテキスト |

つまりこの 1 行で「**機械が使う ID**」と「**モデルが読む説明**」を同時に渡しています。返ってきた `choice` をそのまま `candidates.get()` のキーにできるので、後段で名前の逆引きをする必要がありません。ID を人間可読な名前にしたい誘惑に駆られますが、その必要はないわけです。

`answers.workspace.probabilities` には全選択肢にわたる確率分布が入ります（プロバイダが対応していれば、という条件付きのオプショナルです）。「w68 が 0.62、w5Q が 0.31」のように**どれくらい迷ったか**が見えるので、stderr に出してルーティングの当たり外れを目視できるようにしています。公式ドキュメントにも、選択された選択肢の確率が十分に高いときだけルーティングする、という条件分岐の例が載っています（出典: [Evaluation — AI SDK Core](https://ai-sdk.dev/docs/ai-sdk-core/evaluation)）。

なお、`Object.fromEntries` で動的に組んでいるため、TypeScript 上は `criteria` の型が `Record<string, string>` に広がり、`choice` はただの `string` になります。リテラルで書けば `'positive' | 'neutral'` のようなユニオン型に絞られるので、静的な選択肢ならそちらのほうが型の恩恵は大きいです。

### 4. 改行を潰し、最後の Enter は押さない

```ts
herdr('pane', 'send-text', target.pane_id, prompt.replace(/\r?\n/g, ' '));
```

`send-text` は生バイトをそのまま端末に書き込みます。したがって改行 `\n` は「Enter を押した」ことと同義で、プロンプトが途中で確定されてしまいます。`\r?\n` をスペースに潰しているのはその暴発を防ぐためです（`\r?` は CRLF 混入対策）。複数行を維持したいなら bracketed paste（`ESC[200~ … ESC[201~`）で包む必要があります。

ここで意図的にやっていないのが、**改行を送って確定すること**です。このツールがやるのは入力欄に文字列を置くところまでで、送信するかどうかは対象ペインを見た人間が決めます。

分類モデルは確率を返すのであって、正解を保証するわけではありません。宛先を間違えたまま自動で走り出すと、無関係なプロジェクトでエージェントが動き始めます。逆に、入力欄に置くだけなら、間違っていても Ctrl-U で消せば済みます。**自動化の範囲を「移動と入力」に限定し、「実行」のトリガーを人間に残す**ことで、精度が 100% でなくても実用的なツールになります。

### 5. workspace focus が効かないケースへの配慮

最後に、順序に意味がある箇所の話です。

```ts
herdr('workspace', 'focus', wid);
herdr('agent', 'focus', target.pane_id);
herdr('pane', 'send-text', target.pane_id, prompt.replace(/\r?\n/g, ' '));
herdr('notification', 'show', `-> ${target.label}`, '--sound', 'none');
```

別ワークスペースのペインに送る場合、`agent focus` だけでは画面が移動しません。ワークスペース自体を切り替える必要があるので `workspace focus` を先に呼びます。

ただし、**`workspace focus` はそれ自体が再描画を要求しません**。後続の何かが画面を描き直したときに、初めてクライアント側に反映されます。`send-text` と通知の表示はどちらも再描画を伴うので、`focus` を先に置いておけば結果として画面が動く、という順序依存になります。コード中のコメントに書いてあるのはこのことです。

つまりこの 4 行は「フォーカス 2 つ → 入力 → 通知」という手順であると同時に、**再描画を起こす操作を後ろに置くための並び**でもあります。通知の表示は、どこに送られたかをトーストで知らせる UI 上の意味だけでなく、**再描画を確実に起こすトリガー**としての役割も兼ねています。音は不要なので `--sound none` を指定しています（`herdr notification show --help`（herdr 0.9.0）に `none` / `done` / `request` の 3 値があります）。

## 起動の仕組み

手で `node route.mts ...` と打つのでは本末転倒なので、herdr のキーに割り当てています。`~/.config/herdr/scripts/route-prompt.sh` の全文です。

```sh
#!/bin/sh
# プロンプトを jev に判定させ、該当ワークスペースの agent ペインへ未送信で入力する。
set -e
cd "$HOME/work/<project>"
exec node --env-file=.env route.mts
```

引数なしで呼ぶので、必ず対話入力のパスに入ります。ポップアップに `prompt (empty to cancel)> ` が出て、そこに書いて Enter を押すと分類が走る、という流れです。空で Enter を押せば終了コード 2 で抜けます。

`--env-file=.env` は AI Gateway 用の資格情報を読み込むためです。`cd` しているのは `node_modules` と `.env` の解決のため、`exec` は余計なシェルプロセスを残さないためです。

herdr 側の設定は、[以前の記事](https://zenn.dev/uehaj/articles/herdr-devurls-popup)で書いた URL 台帳のポップアップと同じ要領で、`[[keys.command]]` に `type = "popup"` で割り当てています。

判定の精度を確かめたいときは `DRY` を立てます。

```console
$ DRY=1 node --env-file=.env route.mts "さっきのエラー、設定ファイルも見て"
```

送信は行わず、stderr に選ばれた宛先の 1 行（`-> <workspace_id> <label> (<pane_id>)`）と、`probabilities` のオブジェクトだけが出ます。候補の `label` をどう作ると当たりやすいかを調整するときに使っています。

## おわりに

「宛先を選ぶ」という操作は、人間にとっては一瞬の判断でも、手を動かすコストが意外に高い部類の作業です。タブを探し、移動し、その間に何を書こうとしていたか思い出す。この往復がなくなるだけで、思いついたことを書き留めるハードルはかなり下がりました。

評価モデルは、こういう「判断そのものは軽いが、ルールとして書き下すのが面倒」な箇所にちょうど合います。生成モデルで同じことをやると、プロンプト・パース・リトライの層が要りますし、選択肢の集合から外れた答えが返る余地も残ります。選択肢を渡して 1 つ返してもらう、という形に落とせる問題なら、こちらのほうが素直です。

一方で、精度を前提にした設計にはしていません。確率で選んでいる以上は外れますし、外れたときに自動で走り出すと後始末のほうが高くつきます。だから最後の Enter だけは人間に残す。自動化の線をどこで引くかという話で、今回はここが落としどころでした。
