---
title: "Jevのキラーアプリ、「意味で探す grep」を作った"
emoji: "🔎"
type: "tech"
topics: ["typesafeai", "jev", "grep", "nodejs", "llm"]
published: true
---

:::message
本記事は筆者個人の見解であり、所属する組織の公式見解ではありません。

また、ここで使う TypeSafe の System One API は公開されて間もないものです。この領域は仕様が頻繁に、かつ大きく変わります。本文の記述は執筆時点(2026年9月, @uehaj/semgrep 0.2.0 / Node v23.10.0 で確認)のものなので、最新の挙動は[公式ドキュメント](https://docs.typesafe.ai/)をご確認ください。
:::

## はじめに

正規表現ではなく**意味**を渡す grep を、Jev で作りました。
`-e` に「誰かが変装している、または正体を隠している」のような文を書くと、その意味に合う行が出てきます。

先日これを X で紹介したところ、ちょっとバズりました。本記事はその解説です。

https://x.com/uehaj/status/2101198713834381716
判定には、前回の記事[「そのプロンプト、どのプロジェクトに投げるんでしたっけ — そうだ、Jevで宛先を決めよう」](https://zenn.dev/uehaj/articles/herdr-jev-prompt-router)でも使った [TypeSafe AI](https://typesafe.ai/) の System One モデル [Jev](https://docs.typesafe.ai/models) を使います。

今回作った `semgrep` のソースコードと、npx で実行できる npm パッケージは、こちらで公開しています。文中で使用しているテキストデータ(`tests/` 配下)もこちらにあります。

- GitHub: [uehaj/jev-semgrep](https://github.com/uehaj/jev-semgrep)
- npm: [@uehaj/semgrep](https://www.npmjs.com/package/@uehaj/semgrep)

なお、本ツールは静的解析ツールの [Semgrep](https://semgrep.dev/)(Semgrep, Inc. の製品)とは無関係です。

## TL;DR

- **1 ファイル、依存ゼロ**：意味で行を探す grep `semgrep` を作りました。Node.js 20.12 以降で動きます。
- **文章生成もパースもなし**：1 行ごとに Jev へ「この行は『X』という意味に合うか」を yes/no 確率で聞き、閾値で切ります。
- **言語をまたぐ**：意味と本文の言語は違っていて構いません。日本語で書いた意味 1 つで、フランス語、ロシア語、ドイツ語、スペイン語、中国語、韓国語の行が見つかります。
- **AND / OR / NOT が使える**: 類似度ではなく命題を検索することができ、複合論理演算もできます。ベクトル検索との違いはここです。
- **送信データの注意**：検索した行はすべて TypeSafe の API に送られます。手元で完結する grep とは前提が違います。

## 何ができるか

ここからは検索の例を示します。まず、検索対象のテキストファイルを次のように準備します。`tests/fairy.txt` は、昔話や童話の一場面を 1 行ずつ書いた 16 行のファイルです(筆者による要約文で、日本語のほかドイツ語・フランス語・英語の行が混ざっています)。

```
桃太郎は犬と猿とキジにきびだんごを与えて家来にした
狼はおばあさんを飲み込むと、その帽子を深くかぶってベッドに横たわり、赤ずきんを待った
「おばあさんのお耳はどうしてそんなに大きいの?」と赤ずきんはたずねた
女王は行商人の老婆に身をやつし、毒リンゴを白雪姫に差し出した
灰まみれの娘は、誰にも名乗らぬまま舞踏会で王子と踊り、真夜中の鐘とともに走り去った
浦島太郎は玉手箱を開け、たちまち白髪の老人になった
羊飼いの少年は「狼が来た」と叫んだが、それは嘘だった
かぐや姫は自分が月の都の者であることを、育ての翁についに打ち明けた
三匹の子豚の末の弟は、レンガで家を建てた
Der Wolf setzte Großmutters Haube auf und legte sich in ihr Bett.
Cendrillon s'enfuit à minuit, laissant une pantoufle de verre sur les marches du palais.
The emperor walked in the procession wearing nothing at all, yet everyone praised his new clothes.
一寸法師は針の刀を腰に差し、お椀の舟で川を下った
アリは夏のあいだせっせと働き、キリギリスは歌って過ごした
鶴は「機を織るあいだ、決して覗かないでください」と言い、夜ごと戸を閉てた
おむすびころりん、すっとんとん
```

### (検索例) 「変装している、または正体を隠している」行を探す

この 16 行を「誰かが変装している、または正体を隠している」という意味で検索します。

```sh
$ semgrep -n -e "someone is disguising themselves or hiding their true identity" tests/fairy.txt
2:狼はおばあさんを飲み込むと、その帽子を深くかぶってベッドに横たわり、赤ずきんを待った
4:女王は行商人の老婆に身をやつし、毒リンゴを白雪姫に差し出した
5:灰まみれの娘は、誰にも名乗らぬまま舞踏会で王子と踊り、真夜中の鐘とともに走り去った
10:Der Wolf setzte Großmutters Haube auf und legte sich in ihr Bett.
4/16 lines (16 sent), 1 requests, 1353 input tokens
```

どの行にも「変装」「正体」にあたる語はありません。赤ずきんの狼は日本語の行(2)とグリム原文風のドイツ語の行(10)が同時に出ています。
最後の 1 行は端末に出したときだけ付く集計で、パイプに流すときは出ません。

### (検索例) 冒険者の掲示板から「危険のわりに報酬が安すぎる」依頼を探す

もう 1 つ、以下のファイルから検索する例です。`tests/guild.txt` は、冒険者ギルドの依頼掲示板を模した 12 行です。

```
【討伐】村はずれの洞窟にゴブリンが住み着いた。報酬は銀貨20枚。討伐証明を持参のこと
【苦情】先日届いた薬草がしおれていた。金を返してほしい。二度とこのギルドには頼まない
【護衛】商隊を隣町まで。夜盗が出るため腕利きを希望。報酬は応相談
【採取】満月の夜にだけ咲く月光草を10本。受注時に前金で金貨1枚を支払う
【討伐】ドラゴン退治。報酬は銅貨5枚
【感謝】息子を助けてくれた冒険者様、本当にありがとうございました。パンを焼いてお待ちしています
【急募】井戸に落ちた指輪を今夜中に拾ってほしい。ただの古い指輪だが、どうしても必要なのだ
Recherche mage de feu pour escorter une caravane. Paiement d'avance : 30 pièces d'or.
【苦情】護衛に雇った剣士が夜番のあいだ居眠りしていた。報酬の返還を求める
Es wird ein Alchemist gesucht. Die Bezahlung erfolgt erst nach der Lieferung.
【売却】ミスリルの鎧、ほぼ新品。値札どおり、値引き交渉には応じない
【依頼】亡き妻が好きだった花を、山頂から一輪だけ摘んできてほしい。礼は少ないが誠意を尽くす
```

これを「危険のわりに報酬が安すぎる」という意味で検索します。

```sh
$ semgrep -n -p -e "the reward is far too low for the danger involved" tests/guild.txt
5:【討伐】ドラゴン退治。報酬は銅貨5枚	[0.86]
```

「ドラゴンは危険」で「銅貨 5 枚は安すぎる」という、書かれていない世界知識を使った判定です。銀貨 20 枚のゴブリン討伐(1 行目)は出ません。この種の条件は正規表現では原理的に書けません。

### (検索例) 「報酬の返還を求めている」依頼主を 6 言語から探す

Jev は語ではなく概念を照合するので、意味と本文の言語が一致していなくてもよいです。
`tests/guild-multi.txt` は、フランス語、ロシア語、ドイツ語、スペイン語、中国語、韓国語の 6 言語で書いた「報酬を返せ」という苦情と感謝の手紙を交互に並べたファイルです。

```
Je demande la restitution de la récompense : le garde engagé dormait pendant sa ronde.
Merci mille fois, aventurier. Le village est enfin en paix.
Требую вернуть плату: наёмник сбежал при виде гоблинов.
Спасибо вам, герой. Урожай спасён.
Ich verlange die Rückzahlung des Lohns. Der Trank hat nicht gewirkt.
Vielen Dank, tapferer Held. Der Drache ist fort.
Exijo la devolución de la recompensa: el mapa que compré era falso.
Gracias, valiente aventurero. Mi hija volvió sana y salva.
我要求退还报酬，护卫在半路就跑了。
谢谢你，勇敢的冒险者。村庄得救了。
보수를 돌려주십시오. 호위병이 야간 경비 중에 잠들어 있었습니다.
고맙습니다, 용사님. 덕분에 마을이 평화로워졌습니다.
```

日本語の意味 1 つで、苦情の 6 行だけが出ます。

```sh
$ semgrep -n -p -e "依頼主が報酬の返還を求めている" tests/guild-multi.txt
1:Je demande la restitution de la récompense : le garde engagé dormait pendant sa ronde.	[0.96]
3:Требую вернуть плату: наёмник сбежал при виде гоблинов.	[0.96]
5:Ich verlange die Rückzahlung des Lohns. Der Trank hat nicht gewirkt.	[0.95]
7:Exijo la devolución de la recompensa: el mapa que compré era falso.	[0.95]
9:我要求退还报酬，护卫在半路就跑了。	[0.96]
11:보수를 돌려주십시오. 호위병이 야간 경비 중에 잠들어 있었습니다.	[0.95]
```

`-p` を付けると、意味ごとの確率が行末に出ます。
翻訳の段は挟んでいないので、速度も費用も単一言語のときと同じです。

ただし、公式ドキュメントによれば、英語が主な学習言語で精度も最も高く、CJK を含む他の言語も扱えるものの同等ではないので、英語以外で使う前に自分のデータで試すよう勧められています (出典: [Models — TypeSafe AI](https://docs.typesafe.ai/models#language-support))。
筆者の手元でも、日本語の意味は閾値付近で少し揺れます。
境界に近い問い合わせは英語で書くほうが安全です。

### AND / OR / NOT で意味を組み合わせる

`-e` を複数書くと OR、`-a` で直前の項に AND、`-v` で AND NOT を付けます。
先頭に `-v` だけ書くと `grep -v` と同じ単独の否定です。

| コマンド | 論理 | 説明 |
|---|---|---|
| `-e A -e B` | OR | A または B |
| `-e A -a B` | AND | A かつ B |
| `-e A -v B` | AND NOT | A かつ B ではない |
| `-e A -a B -v C -e D` | 複合 | (A and B and not C) or D |
| `-v B` | NOT | B ではない行（単独の否定） |

掲示板から、護衛の依頼のうち報酬額がはっきりしないものを探す例です。

```sh
$ semgrep -n -e "an escort job is requested" -a "the amount of the reward is not clearly stated" tests/guild.txt
3:【護衛】商隊を隣町まで。夜盗が出るため腕利きを希望。報酬は応相談
```

フランス語の護衛依頼(8 行目)は「Paiement d'avance : 30 pièces d'or(前払いで金貨 30 枚)」と額が明示されているため、2 つ目の意味が 0.05 となり落ちます。「応相談」が「額がはっきりしない」に該当する、という判定も語の一致ではありません。

`-v` の例です。金銭に触れている依頼から、苦情を除きます。

```sh
$ semgrep -n -e "money or payment is mentioned" -v "the requester is angry or dissatisfied" tests/guild.txt
1:【討伐】村はずれの洞窟にゴブリンが住み着いた。報酬は銀貨20枚。討伐証明を持参のこと
3:【護衛】商隊を隣町まで。夜盗が出るため腕利きを希望。報酬は応相談
4:【採取】満月の夜にだけ咲く月光草を10本。受注時に前金で金貨1枚を支払う
5:【討伐】ドラゴン退治。報酬は銅貨5枚
8:Recherche mage de feu pour escorter une caravane. Paiement d'avance : 30 pièces d'or.
10:Es wird ein Alchemist gesucht. Die Bezahlung erfolgt erst nach der Lieferung.
11:【売却】ミスリルの鎧、ほぼ新品。値札どおり、値引き交渉には応じない
12:【依頼】亡き妻が好きだった花を、山頂から一輪だけ摘んできてほしい。礼は少ないが誠意を尽くす
```

「金を返してほしい」「報酬の返還を求める」という 2 件の苦情は、金銭の話でありながら `-v` で落ちています。

## 仕組み

前回の記事では、Jev への質問の型のうち、選択肢から 1 つ選ぶ `choice` を使いました。
今回は、yes である確率を返す `noul` だけを使います。
公式ドキュメントの定義は次のとおりです。

> A Noul question asks the model to evaluate a yes/no question and return the probability that the answer is yes.

(仮訳: Noul の質問は、yes/no の問いを評価して、答えが yes である確率を返すようモデルに求める)

出典: [Noul — TypeSafe AI](https://docs.typesafe.ai/primitives/noul)

`semgrep` がやっていることは、行と指定されたすべての意味のマトリックス(全組み合わせ)を作り、その 1 マスを 1 つの `noul` の質問としてリクエストに詰めることです。ただしファイル全体を 1 リクエストで送るのではなく、行を一定数(既定 30 行)ずつのチャンクに区切り、「チャンク内の行 × 全意味」のマトリックスごとに 1 リクエストにします。

このとき各質問は、`type: 'noul'` のように**期待する回答の型**を宣言しています。生成モデルに「JSON で答えて」と頼んでパースするのではなく、回答の形(noul なら「yes である確率」という数値 1 つ、前回使った choice なら「選択肢のうちの 1 つ」)がスキーマとして最初から決まっていて、レスポンスにはその型の値だけが返ります。

たとえば 3 行のファイルを 2 つの意味で検索するときは、次の形になります。行を `state`、3 × 2 = 6 個の `noul` を `questions` としてリクエストに入れると、レスポンスの `answers` に確率が 6 個返ります。

```
コマンドライン:
  semgrep -e "意味0" -e "意味1" 3行のファイル.txt

リクエスト:
  state:     { L000: "1行目", L001: "2行目", L002: "3行目" }
  questions: { L000_0: { type: "noul", instructions: "L000 は意味0に合うか" },
               L000_1: { type: "noul", instructions: "L000 は意味1に合うか" },
               L001_0: { type: "noul", instructions: "L001 は意味0に合うか" },
               L001_1: { type: "noul", instructions: "L001 は意味1に合うか" },
               L002_0: { type: "noul", instructions: "L002 は意味0に合うか" },
               L002_1: { type: "noul", instructions: "L002 は意味1に合うか" } }

期待する回答のかたち (各質問の type: "noul" が宣言している):
  質問 1 つにつき { noul: <0〜1 の数値> } が 1 つ。yes である確率で、文章は返らない

レスポンス:
  answers:   { L000_0: { noul: 0.93 }, L000_1: { noul: 0.08 },
               L001_0: { noul: 0.12 }, L001_1: { noul: 0.96 },
               L002_0: { noul: 0.04 }, L002_1: { noul: 0.07 } }
```

このように、「複数対象」×「多数・多種」の質問にたいして、1 リクエストで一撃で回答できることが Jev の本質であり、従来の LLM との機能的な差異の核心です。これをチャンクごとに、ファイルの全行を処理し終えるまで繰り返していきます。

:::message
**この構造はどこまでが API の規定か**

リクエストのトップレベルが `model` / `state` / `questions` の 3 フィールドであることは [System One API の仕様](https://docs.typesafe.ai/api)です。`state` は評価対象のコンテンツで、プレーン文字列でも構造化データ(オブジェクト・配列)でもよく、`questions` は型付きの質問のマップで、**キーは利用者が自由に命名し、答えは同じキーで返ります**。複数の質問を 1 リクエストに入れることまでが API のネイティブな仕様です。

一方、「複数の対象(行)」という概念は API 側にはありません。API から見れば評価対象の `state` は 1 つです。`semgrep` は、その 1 つの `state` をオブジェクトにして `L000`, `L001`... のキーで複数行を詰め、各質問の instructions からキー名で行を参照することで「行 × 意味」のマトリックスを表現しています。質問キーを `L000_0` の形にして行と意味を逆引きするのも、このツールの命名規約にすぎません。
:::

:::message
**質問の型は混在できる**

この例ではすべての質問が `type: "noul"` ですが、質問の型はほかに、選択肢から 1 つ選ぶ `choice`(前回の記事で使用)と、ルーブリックに沿って段階評価する `score` があり、[公式ドキュメント](https://docs.typesafe.ai/primitives)には "You can mix question types freely."(仮訳: 質問の型は自由に混在できる)とあります。1 つのリクエストの中で、分類は `choice`、真偽は `noul`、程度は `score`、という使い分けが可能です。
:::

これで得られた確率をどうするかは、もう Jev の仕事ではありません。`semgrep` 側で意味ごとに閾値(既定 0.5)でブール値に変換し、`-e` / `-a` / `-v` で組み立てた式を行ごとに評価して、真になった行だけを grep と同じ体裁で出力します。

本体 300 行ほどのうち、API を叩く部分はこれだけです。

```js
async function evaluate(chunk) {
  const id = i => `L${String(i).padStart(3, '0')}`;
  const state = Object.fromEntries(chunk.map((l, i) => [id(i), l.text.slice(0, 2000)]));
  const questions = {};
  // 行 × 意味の組み合わせごとに noul の質問を作る
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

「X に関係のある行」が欲しいだけなら、ベクトル検索(埋め込みのコサイン類似度)でも似た行は出ます。違うのは判定の中身です。

ベクトル検索では、まず各行を埋め込み(意味を数値の列にしたベクトル)へ変換し、索引として保存しておきます。この変換は、どんな質問が来るかを知らない時点で行われ、以後は固定です。検索するときは質問の側も同じ形のベクトルにして、行のベクトルとの近さを測ります。行の側は質問に合わせて解釈し直されないので、測れるのは「話題が近いか」までです。

`semgrep` はこの索引を作りません。行と質問を同じ 1 つのリクエストで Jev に渡し、Jev は質問を読んだうえでその行を評価します。だから「誰が何をしたか」「否定かどうか」「求めているのか、済んだのか」で答えが変わる、**命題が成り立つかどうか**の判定になります。索引が要らないので目の前のファイルにその場で使えます。その裏返しとして、問い合わせのたびにコーパス全体分の入力トークンを払うので、同じ大きなコーパスに何度も問い合わせるなら、索引を一度作って使い回すベクトル検索のほうが安くて速くなります。

### (検索例) 「変装している、または正体を隠している」のは誰か

次の 6 行はどれも「正体」や「嘘」の話題ですが、この命題が成り立つのは 2 行だけです。
`-t 0` で閾値を外し、全行の確率を出しています。

```sh
$ semgrep -n -p -t 0 -e "someone is disguising themselves or hiding their true identity" tests/fairy-contrast.txt
1:女王は行商人の老婆に身をやつし、毒リンゴを白雪姫に差し出した	[0.98]
2:灰まみれの娘は、誰にも名乗らぬまま舞踏会で王子と踊り、真夜中の鐘とともに走り去った	[0.83]
3:The emperor walked in the procession wearing nothing at all, yet everyone praised his new clothes.	[0.17]
4:羊飼いの少年は「狼が来た」と叫んだが、それは嘘だった	[0.13]
5:かぐや姫は自分が月の都の者であることを、育ての翁についに打ち明けた	[0.47]
6:鶴は「機を織るあいだ、決して覗かないでください」と言い、夜ごと戸を閉てた	[0.43]
```

裸の王様(3)は偽りの話ですが、王様は偽っているのではなく騙されている側なので低く出ます。オオカミ少年(4)は嘘をついていますが変装ではありません。かぐや姫(5)は正体を「打ち明けた」、つまり隠すのをやめた行なので、命題としては裏返っています。話題の近さで測るとどれも「正体・嘘」の同じあたりに固まる行たちです。

### (検索例) 「変装しているが、悪意はない」のは誰か

意味ごとに独立した確率が出るので、AND と NOT は集合の引き算や「否定クエリ」の工夫ではなく、ただのブール演算です。

```sh
# 変装しているが、悪意はない → シンデレラだけが残る
$ semgrep -n -e "someone is disguising themselves or hiding their true identity" -v "there is malicious or harmful intent" tests/fairy-contrast.txt
2:灰まみれの娘は、誰にも名乗らぬまま舞踏会で王子と踊り、真夜中の鐘とともに走り去った
```

毒リンゴの女王(1)は変装 0.98 ですが、悪意の側で落ちます。語彙ではなく、誰が何のためにしているかで切れています。

実用上の帰結があります。
公式ドキュメントによれば、較正とは、ある確率を割り当てた事象がその割合で実際に起こることで、これによって不確かさをソフトウェアが扱えるようになります (出典: [Machine learning primer — TypeSafe AI](https://docs.typesafe.ai/introduction/machine-learning-primer))。
確率がその意味で較正されているので、閾値 0.5 をどの質問にもそのまま使えます。
コサイン類似度では top-k か質問ごとの閾値調整が要ります。


| 比較項目 | ベクトル検索 | semgrep (Jev の noul) |
|---|---|---|
| 判定の基準 | 話題の近さ（類似度） | 命題が成り立つ確率 |
| 否定や複合条件 | 類似度の演算では表しにくい | AND / OR / NOT をそのまま評価 |
| 事前の索引 | 必要（埋め込みを作る） | 不要（目の前のファイルをその場で検索） |
| 費用の構造 | 索引作成が高く、検索は安い | 問い合わせごとに全行分を払う |

固定された大きな文書群に繰り返し問い合わせるならベクトル検索、手元のログやファイルをその場で意味の条件で絞るなら `semgrep` が向いています。

## 閾値の調整

確率は実行のたびに 0.05 程度ぶれます。
閾値は肯定側 `-t` と否定側 `-T` の 2 つで、`-t 0.6 -T 0.4` なら 0.4 から 0.6 の行は「X」にも「not X」にも該当しません。
`--level loose` / `normal` / `strict` で両方をまとめて動かせます。

端末では `-p` の確率に色が付きます。
肯定閾値以上は緑、否定閾値未満は赤、その間は黄です。

![semgrep の色付き出力。行番号は緑、確率は閾値に応じて緑または赤 (筆者の実行環境のスクリーンショット)](/images/semgrep-color.png)

閾値の意味は、さきほどの童話の対照実験がそのまま教材になります。かぐや姫 0.47 と鶴 0.43 は、既定の閾値 0.5 のすぐ下です。かぐや姫が低いのは「打ち明けた」が隠すのをやめた行為だからで妥当ですが、鶴は物語を知っていれば変装の場面です。1 行だけでは「覗くな」の理由まで分からないので、確率が境界に張り付きます。この 2 行は実行ごとのぶれで閾値をまたぐことがある、という距離感です。

## 精度をどう測ったか

「意味に合う行」の正解は人手で決めるしかないので、判定役に Claude を使う LLM-as-judge のテストを書きました。
10 個の検索式を、ログ・問い合わせ・コード・雑談が混ざった 51 行のコーパス(`tests/corpus.txt`)に対して実行し、行ごとの真偽を `claude -p` に判定させ、その真偽で AND / OR / NOT の式を評価したものを正解として `semgrep` の出力と比べます。
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

- 空行は API に送らず、すべての意味で確率 0 として扱います。`-v X` には該当し、`-e X` には該当しません。
- 行は 2,000 文字で切って送ります。
- HTTP ステータス 429 (rate limit 超過) と 529 (サーバ側の過負荷) は、待ち時間を倍々に延ばしながら(指数バックオフ) 6 回まで再試行します。公式の API リファレンスがこの 2 つのステータスに対して勧めている扱いです (出典: [API reference — TypeSafe AI](https://docs.typesafe.ai/api))。

## インストール

Node.js 20.12 以降が要ります。

```sh
# グローバルインストール
npm install -g @uehaj/semgrep

# ヘルプの表示 (LANG が ja で始まっていれば日本語)
semgrep --help
```

### API キーの設定

API キーは [TypeSafe のコンソール](https://console.typesafe.ai/)で取得し、環境変数 `TYPESAFE_API_KEY`、または `./.env` か `~/.config/semgrep/.env` に置きます。

## おわりに

使う側から見た grep との違いは、`-e` に書くものが正規表現から文に変わったことだけです。
`-a` や `-v` の組み合わせ方は grep と同じままで、これは Jev が意味ごとに独立した yes/no 確率を返すので、閾値で切った真偽をそのままブール演算できるからです。
前回の宛先ルーティングは `choice` 1 問、今回は `noul` を行数分並べただけで、どちらも生成モデルなら要るはずのプロンプト設計とパースの層がありません。
「文章はいらない、判断だけほしい」場面はほかにも転がっていそうなので、見つけたらまた書きます。

## 追記: Claude Code のスキルとしても使えます

semgrep を代わりに走らせてくれる Claude Code のスキルを、[uehaj/skills](https://github.com/uehaj/skills) マーケットプレースの `uehaj` プラグインとして公開しています。探したいものを言葉で書くと、スキルが式を組み立てて検索し、`file:line` 付きで該当行を報告します。

```sh
claude plugin marketplace add uehaj/skills
claude plugin install uehaj@uehaj-skills
```

コマンドラインツールを別途インストールする必要はありません(PATH に `semgrep` が無ければ `npx @uehaj/semgrep` に自動で切り替わります)。必要なのは API キーの設定だけです。あとは Claude Code の中で次のように打ちます。

```
/uehaj:semgrep 返金を求めている問い合わせ tickets/*.txt
/uehaj:semgrep 未テストのまま入った修正 git log --oneline -200
```

このスキルだけ欲しい場合の入れ方も含め、詳細は [README の「Claude Code から使う」](https://github.com/uehaj/jev-semgrep/blob/main/README.ja.md#claude-code-から使う)を参照してください。
