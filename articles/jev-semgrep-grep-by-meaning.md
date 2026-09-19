---
title: "正規表現ではなく意味で行を探す grep を、Jev の yes/no 確率だけで作る"
emoji: "🔎"
type: "tech"
topics: ["typesafe", "jev", "grep", "nodejs", "ai"]
published: false
---

:::message
本記事は筆者個人の見解であり、所属する組織の公式見解ではありません。

また、ここで使う TypeSafe の System One API は公開されて間もないものです。この領域は仕様が頻繁に、かつ大きく変わります。本文の記述は執筆時点(2026年9月, @uehaj/semgrep 0.2.0 / Node v23.10.0 で確認)のものなので、最新の挙動は[公式ドキュメント](https://docs.typesafe.ai/)をご確認ください。
:::

## はじめに

正規表現ではなく**意味**を渡す grep を作りました。
`-e` に「顧客が怒っている、または不満を持っている」のような文を書くと、その意味に合う行が出てきます。
判定には、前回の記事[「そのプロンプト、どのプロジェクトに投げるんでしたっけ — そうだ、Jevで宛先を決めよう」](https://zenn.dev/uehaj/articles/herdr-jev-prompt-router)でも使った TypeSafe AI の System One モデル Jev を使います。

リポジトリ: <https://github.com/uehaj/jev-semgrep>
npm: [@uehaj/semgrep](https://www.npmjs.com/package/@uehaj/semgrep)

## TL;DR

- 意味で行を探す grep `semgrep` を作りました。Node.js 20.12 以降で動く 1 ファイル、依存ゼロです。
- 1 行ごとに Jev へ「この行は『X』という意味に合うか」を yes/no 確率で聞き、閾値で切ります。文章生成もパースもありません。
- 意味と本文の言語は違っていて構いません。日本語で書いた意味 1 つで、フランス語、ロシア語、ドイツ語、スペイン語、中国語、韓国語の行が見つかります。
- 意味ごとに独立した確率が返るので、AND / OR / NOT がそのままブール演算になります。ベクトル検索との違いはここです。
- 検索した行はすべて TypeSafe の API に送られます。手元で完結する grep とは前提が違うので、その注意も書きます。

なお、名前が静的解析ツールの [Semgrep](https://semgrep.dev/) と衝突しています。両方使う方はどちらかを改名してください。

## 何ができるか

`tests/corpus.txt` は、サーバログ、英語と日本語の問い合わせ、ソースコード、SQL、雑談が混ざった 51 行のファイルです。
これに英語の意味を当てると、日本語の行も含めて 5 行が出ます。

```sh
$ semgrep -n -e "customer is angry or frustrated" tests/corpus.txt
14:ユーザー山田さんからの問い合わせ: 返金してほしい、商品が壊れていた
16:ユーザー佐藤さんからの問い合わせ: 注文した覚えのない請求が来ています。至急確認してください
18:I want my money back. The item arrived broken and customer service ignored me.
21:Your product ruined my weekend. Never buying from you again.
23:This is the third time I'm writing. Nobody has replied to my previous emails.
5/51 lines, 2 requests, 3225 input tokens
```

どの行にも angry や frustrated という語はありません。
最後の 1 行は端末に出したときだけ付く集計で、パイプに流すときは出ません。

### 言語をまたいで探せる

Jev は語ではなく概念を照合するので、意味と本文の言語が一致していなくてもよいです。
`tests/multi.txt` は、フランス語、ロシア語、ドイツ語、スペイン語、中国語、韓国語の 6 言語で書いた返金要求と感謝の文を交互に並べたファイルです。
日本語の意味 1 つで、返金要求の 6 行だけが出ます。

```sh
$ semgrep -n -p -e "顧客が返金を求めている" tests/multi.txt
1:Je veux être remboursé, le produit est arrivé cassé.	[0.98]
3:Я требую вернуть деньги, товар не работает.	[0.97]
5:Ich möchte mein Geld zurück, das Gerät ist defekt.	[0.97]
7:Quiero un reembolso, el paquete llegó vacío.	[0.97]
9:我要求退款，商品坏了。	[0.97]
11:환불해 주세요. 제품이 고장났어요.	[0.97]
```

`-p` を付けると、意味ごとの確率が行末に出ます。
翻訳の段は挟んでいないので、速度も費用も単一言語のときと同じです。

ただし、公式ドキュメントによれば、英語が主な学習言語で精度も最も高く、CJK を含む他の言語も扱えるものの同等ではないので、英語以外で使う前に自分のデータで試すよう勧められています (出典: [Models — TypeSafe AI](https://docs.typesafe.ai/models#language-support))。
筆者の手元でも、日本語の意味は閾値付近で少し揺れます。
境界に近い問い合わせは英語で書くほうが安全です。

### AND / OR / NOT で意味を組み合わせる

`-e` を複数書くと OR、`-a` で直前の項に AND、`-v` で AND NOT を付けます。
先頭に `-v` だけ書くと `grep -v` と同じ単独の否定です。

| コマンド | 意味 |
|---|---|
| `-e A -e B` | A or B |
| `-e A -a B` | A and B |
| `-e A -v B` | A and not B |
| `-e A -a B -v C -e D` | (A and B and not C) or D |
| `-v B` | not B |

ネットワーク障害のうち、再試行の行を除く例です。

```sh
$ semgrep -n -e "network or remote connection failure" -v "a retry is happening or was attempted" tests/corpus.txt
4:2026-09-19 08:02:30 ERROR connection reset by peer while calling payment-gateway
6:2026-09-19 08:02:35 ERROR timeout after 5000ms waiting for payment-gateway
9:2026-09-19 08:10:44 ERROR DNS lookup failed for api.example.com
11:2026-09-19 09:00:00 ERROR SSL handshake failed: certificate expired
13:network unreachable: no route to host 10.0.0.5
30:except ConnectionError as e:
31:    logger.error("upstream unreachable: %s", e)
```

5 行目の `retrying payment-gateway request (attempt 2/3)` はネットワーク障害の意味には合いますが、`-v` で落ちています。
Python の `except ConnectionError` が拾われているのは、正規表現の grep では出てこない結果です。

## 仕組み

前回の記事では、質問の型のうち選択肢から 1 つ選ぶ `choice` を使いました。
今回は、yes である確率を返す `noul` だけを使います。
公式ドキュメントの定義は次のとおりです。

> A Noul question asks the model to evaluate a yes/no question and return the probability that the answer is yes.

(仮訳: Noul の質問は、yes/no の問いを評価して、答えが yes である確率を返すようモデルに求める)

出典: [Noul — TypeSafe AI](https://docs.typesafe.ai/primitives/noul)

`semgrep` がやっていることは、この `noul` を「行 × 意味」の数だけ 1 リクエストに詰めることです。
本体 300 行ほどのうち、API を叩く部分はこれだけです。

```js
async function evaluate(chunk) {
  const id = i => `L${String(i).padStart(3, '0')}`;
  const state = Object.fromEntries(chunk.map((l, i) => [id(i), l.text.slice(0, 2000)]));
  const questions = {};
  chunk.forEach((_, i) => meanings.forEach((text, m) => {
    questions[`${id(i)}_${m}`] = { type: 'noul', instructions: `Does line ${id(i)} match the meaning: "${text}"?` };
  }));
  const res = await fetch('https://api.typesafe.ai/v1/systemone', {
    method: 'POST',
    headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'jev-latest', state, questions }),
  });
  const { answers } = await res.json();
  return chunk.map((_, i) => meanings.map((_, m) => answers[`${id(i)}_${m}`].noul));
}
```

(再試行とタイムアウトの処理は省いています)

処理の流れは 4 段です。

1. 空行を除いた行を 30 行ずつのチャンクに切ります。
2. チャンクの各行を `state` に `{"L000": "1行目", "L001": "2行目", ...}` の形で入れ、行 × 意味の数だけ `noul` の質問を同じリクエストに入れます。
3. リクエストを 8 本まで並列で投げます。出力はファイル順に並べ直します。
4. 行ごとに、意味ごとの確率を閾値でブール値にして、AND / OR / NOT の式を評価します。

`state` をオブジェクトにしてキーで行を指す形は、公式ドキュメントにあるとおり、たいていのリクエストではオブジェクトを使って state の各部分に説明的な名前を付ける、という勧めに沿ったものです (出典: [State — TypeSafe AI](https://docs.typesafe.ai/concepts/state))。
前回の記事で「`criteria` のキーを機械用の ID にすると答えをそのままキーとして使える」と書いたのと同じ発想で、今回は質問名 `L012_0` から行と意味を逆引きしています。

30 行をまとめても、1 行ずつ送ったときと確率は変わりませんでした。
30 行を 1 リクエストにまとめると 0.2 秒程度、同じ 30 行を 1 行ずつ送ると 7 秒程度かかります。
上限は公式ドキュメントに、1 リクエスト 64k トークン、`state` と最長の質問の合計で 32k トークンとあります (出典: [Models — TypeSafe AI](https://docs.typesafe.ai/models))。
チャンクを大きくしすぎると閾値付近の行を取りこぼし始めたので、既定を 30 行にしています。

## ベクトル検索と何が違うのか

「X に関係のある行」が欲しいだけなら、埋め込みのコサイン類似度でも似た行が出ます。
違うのは判定の中身です。
`semgrep` は話題の近さではなく、その行について**命題が成り立つか**を判定します。
質問は行と同じリクエストで渡され、確率は両方を見たうえで計算されるので、誰が何をしたか、否定、「求めている」のか「済んだ」のかで答えが変わります。
行の埋め込みは質問を見る前に固定されるので、測れるのは話題の近さまでです。

次の 6 行はどれも「返金の話」ですが、顧客が返金を求めているのは 2 行だけです。
`-t 0` で閾値を外し、全行の確率を出しています。

```sh
$ semgrep -n -p -t 0 -e "customer is asking for a refund" tests/contrast.txt
1:返金してほしい。商品が壊れていた	[0.98]
2:返金処理が完了しましたのでご確認ください	[0.10]
3:当社の返金ポリシーは購入後30日以内です	[0.10]
4:The manager denied the refund request yesterday	[0.17]
5:I demand a full refund immediately	[0.94]
6:Refunds are processed within 5 business days	[0.08]
```

意味ごとに独立した確率が出るので、AND と NOT は集合の引き算や「否定クエリ」の工夫ではなく、ただのブール演算です。

```sh
# 返金の話だが、顧客が求めているのではない → 完了報告、ポリシー、却下、日数
$ semgrep -n -e "about a refund" -v "the customer is asking for a refund" tests/contrast.txt
2:返金処理が完了しましたのでご確認ください
3:当社の返金ポリシーは購入後30日以内です
4:The manager denied the refund request yesterday
6:Refunds are processed within 5 business days

# 怒っている、かつ、それが顧客であってスタッフではない
$ semgrep -n -e "someone is angry" -a "the customer, not the staff, is the one acting" tests/contrast.txt
5:I demand a full refund immediately
8:顧客が怒って電話を切った
```

7 行目の `カスタマーサポート担当者が怒って電話を切った` は、2 つ目の意味で 0.05 となり除外されます。
8 行目と語彙はほぼ同じで、主語だけが違う行です。

実用上の帰結が 2 つあります。
公式ドキュメントによれば、較正とは、ある確率を割り当てた事象がその割合で実際に起こることで、これによって不確かさをソフトウェアが扱えるようになります (出典: [Machine learning primer — TypeSafe AI](https://docs.typesafe.ai/introduction/machine-learning-primer))。
確率がその意味で較正されているので、閾値 0.5 をどの質問にもそのまま使えます。
コサイン類似度では top-k か質問ごとの閾値調整が要ります。
もう 1 つは、索引を作らないので目の前のファイルにそのまま当てられることです。
裏返すと問い合わせのたびにコーパス全体分を払うので、同じ大きなコーパスに何度も問い合わせるならベクトル索引のほうが安くて速いです。

## 閾値の調整

確率は実行のたびに 0.05 程度ぶれます。
閾値は肯定側 `-t` と否定側 `-T` の 2 つで、`-t 0.6 -T 0.4` なら 0.4 から 0.6 の行は「X」にも「not X」にも当たりません。
`--level loose` / `normal` / `strict` で両方をまとめて動かせます。

端末では `-p` の確率に色が付きます。
肯定閾値以上は緑、否定閾値未満は赤、その間は黄です。

![semgrep の色付き出力。行番号は緑、確率は閾値に応じて緑または赤 (筆者の実行環境のスクリーンショット)](/images/semgrep-color.png)

ネットワーク障害の意味で、`retrying` の行が 0.73、`except ConnectionError` が 0.61 と、正解の行より低めに出ているのが読み取れます。
`--level strict` (`-t 0.7`) にすると 0.61 の行は落ち、0.73 の行は残ります。

## 精度をどう測ったか

「意味に合う行」の正解は人手で決めるしかないので、判定役に Claude を使う LLM-as-judge のテストを書きました。
10 個の検索式を 51 行のコーパスに当て、行ごとの真偽を `claude -p` に判定させ、その真偽で AND / OR / NOT の式を評価したものを正解として `semgrep` の出力と比べます。
判定結果は JSON にキャッシュするので、2 回目以降は判定役を呼びません。

2026 年 9 月 19 日の実行では、既定の閾値で precision 0.94、recall 0.98 でした。
閾値を 0.05 刻みで総当たりした結果と、ケースごとの食い違いは [tests/report.md](https://github.com/uehaj/jev-semgrep/blob/main/tests/report.md) にあります。
食い違いの例を 2 つ挙げます。

- 「ネットワークやリモート接続の障害」で、`retrying payment-gateway request` と `except ConnectionError as e:` を `semgrep` は拾い、判定役は障害そのものではないとしました。どちらの解釈も成り立つ行です。
- 「書き手が感謝や満足を表している」で、`ぼくのなつやすみは楽しかったです` を `semgrep` だけが拾いました。

判定役も生成モデルなので、この数値は「Claude の解釈と Jev の解釈がどれだけ一致したか」です。
絶対的な正解率ではありませんが、閾値をどこに置くかを決める材料にはなります。

## 使うときの注意

**検索した行はすべて api.typesafe.ai に送られます。**
手元で完結する grep と同じ感覚で、機密を含むディレクトリに `-r` を向けるわけにはいきません。
`-r` は `.git` と `node_modules` に加えて、`.env*`、`*.pem`、`*.key`、`id_rsa` のような秘密を保持しがちなファイルと、`.ssh` / `.aws` / `.gnupg` を既定でスキップし、処理から除外して送信しません。
ただしコマンドラインで直接指定したファイルは、この一覧に該当しても検索します。

### 費用

費用は入力トークンのみに課金され、執筆時点の単価は 100 万トークンあたり 0.042 ドルです (出典: [Models — TypeSafe AI](https://docs.typesafe.ai/models))。
2 つの意味で 30 行のチャンクが 3,000 トークン程度なので、51 行のコーパス 1 回分は 1 円に届きません。
同じ比率で見積もると、1 MB のテキストを意味 1 つで検索した場合は、行の長さと言語によって 0.7M から 1.1M トークン、数円程度です。
rate limit は同じページに 1 分あたり 1,200 リクエストとありますが、需要に応じて予告なく変わると明記されています。

### そのほかの制約

- 空行は API に送らず、すべての意味で確率 0 として扱います。`-v X` には当たり、`-e X` には当たりません。
- 行は 2,000 文字で切って送ります。
- 429 と 529 は指数バックオフで 6 回まで再試行します。公式の API リファレンスがこの 2 つのステータスに対して勧めている扱いです (出典: [API reference — TypeSafe AI](https://docs.typesafe.ai/api))。

## インストール

Node.js 20.12 以降が要ります。

```sh
npm install -g @uehaj/semgrep
semgrep --help
```

API キーは [TypeSafe のコンソール](https://console.typesafe.ai/)で取得し、環境変数 `TYPESAFE_API_KEY`、または `./.env` か `~/.config/semgrep/.env` に置きます。
`--help` は `LANG` が `ja` で始まっていれば日本語で出ます。

## おわりに

使う側から見た grep との違いは、`-e` に書くものが正規表現から文に変わったことだけです。
`-a` や `-v` の組み合わせ方は grep と同じままで、これは Jev が意味ごとに独立した yes/no 確率を返すので、閾値で切った真偽をそのままブール演算できるからです。
前回の宛先ルーティングは `choice` 1 問、今回は `noul` を行数分並べただけで、どちらも生成モデルなら要るはずのプロンプト設計とパースの層がありません。
「文章はいらない、判断だけほしい」場面はほかにも転がっていそうなので、見つけたらまた書きます。
