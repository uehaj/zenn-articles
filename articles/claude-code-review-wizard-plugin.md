---
title: "AskUserQuestionをもっと見やすくわかりやすく：Claude Codeの質問を図表を駆使したウィザードUIに"
emoji: "🧙"
type: "tech"
topics: ["claudecode", "ai", "plugin", "nodejs"]
published: false
---

## TL;DR

- Claude Code の AskUserQuestion はターミナル UI なので、選択肢を読み比べる質問には向かない。図っぽいものも出てくるが罫線素片とASCIIアートでは限界がある。
- 今回作成した review-wizard は、AIエージェントからの人間への質問をブラウザのウィザード画面（1問ずつ表示、ステッパー付き）で出すプラグイン。質問の内容に応じて比較表やインライン SVG の図で説明され、質問が理解しやすくなる。
- 実装は一時的なローカル HTTP サーバ方式で、外部 npm 依存はゼロ。回答を受け取ったら閉じて終了し、常駐しない。
- 導入すると、質問が3問以上、あるいは選択肢の比較検討が要るときは Claude Code が自動でこちらを使い、1〜2問の即答は AskUserQuestion のままになる（SKILL.md の基準による）。
- リポジトリ: <https://github.com/uehaj/review-wizard>

## はじめに

NTTテクノクロスの上原です。映画「マイケル」を見てあらためて「スリラー」ってすごいMVだなと思い動画をみなおしたりしています。

さて、Claude Code には AskUserQuestion という超便利な仕組みがあります。AIから人間に必要な一連の質問をしてくる機能です。1〜2問ならこれで何の不満もありません。手を止めずに答えて、すぐ作業に戻れます。

ところが、質問が3問4問と続いたり、質問の内容がややこしくなってくると、様子が変わります。
これは[AIが生成する資料はMarkdownではなくHTMLにしよう](https://zenn.dev/uehaj/articles/claude-code-fancy-html-hook)、という流れがあるのと同じで、フォントや図表を駆使して情報提示すれば認知負荷を下げることができます。おなじ考えで、HTMLで質問を提示するのが review-wizard というプラグインです。まずは画面を見てください。

## 画面を見てみる

画面例1は、チャットアプリの UI 案を選ぶ質問です。質問文の下に3案のワイヤーフレームと比較表が描かれ、その下に選択肢が並びます。わかりやすく目にやさしいですね。

![画面例1: チャットアプリのレイアウトを選ぶ質問画面。質問文の下に「案A サイドバー型」「案B シングルカラム」「案C 3ペイン型」の3つのワイヤーフレーム図と、情報密度、モバイル適性、実装コスト、向く用途の比較表が描画され、選択肢では案A サイドバー型が選択済み](/images/review-wizard-chatui-q1.png)

次の画面例2は、表をつかったものです。一目瞭然です。質問は前後に戻ることもできます。

![画面例2: 認証方式の設計レビューの1問目。上部に現在位置を示すステッパー、ヘッダーチップ「認証方式」、質問文の下に方式ごとの比較表とトークンの流れを示すインライン SVG 図、セッション管理方式を選ぶ単一選択のラジオボタンで「ハイブリッド」が選択済み、下部に「その他（自由記述）」欄と「戻る/次へ」ボタン](/images/review-wizard-q1.png)

## 裏のしくみ

しくみとしては、ローカル用途に限るウェブサーバをたてています。

質問をユーザに提示するためにClaude Codeは 127.0.0.1 に一時的な HTTP サーバを立てます。URL には毎回ランダムなワンタイムトークンを埋め込み、そのパスでだけウィザード画面を返します。ブラウザが URL を開き、回答が送信されると、サーバは回答を JSON で書き出してそのまま閉じます。起動して、答えを待って、閉じる。ポーリングも常駐もない短命なプロセスです。


## 導入と使い方

マーケットプレイス経由なら次の2行です。

```bash
claude plugin marketplace add https://github.com/uehaj/review-wizard.git
claude plugin install review-wizard@review-wizard-marketplace
```

開発中や導入前の確認では、ローカルのディレクトリを直接読み込ませます。

```bash
claude --plugin-dir /path/to/review-wizard
```

Claude Code から使うときは、質問 JSON を一時ファイルに書き、バックグラウンドで実行します。回答が送信されるまでプロセスは終わらないので、フォアグラウンドで待つと Claude Code 自体が止まってしまいます。

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/review_wizard.ts" \
  --questions <in.json> --out <out.json> --timeout 1800
```

起動すると標準出力に `review_wizard: <URL>` が出て、その URL が自動で開きます。プロセスが終わったら、終了コードで結果を判別し、`--out` の回答 JSON を読みます。終了コードは、回答受領が 0、入力エラーが 1、タイムアウトやサーバ起動失敗が 2、中断が 130 です。

### 起動条件

スキル定義には「質問が3問以上、あるいは選択肢の比較検討が要るときに AskUserQuestion の代わりに使う。1〜2問の即答は AskUserQuestion のまま」という起動条件が書いてあり、Claude Code はこの説明文を読んで起動を判断します。つまり導入しておけば、場面に応じて自動的に使用されます。基準を変えたいときは、CLAUDE.md に自分のルールを書いて上書きできます。

この「CLAUDE.md で上書きする」方法は、他の人が配布しているスキルの質問にも効きます。たとえば mattpocock 氏の `grilling`(計画を質問攻めで詰めるスキル)や、それを呼び出す `grill-with-docs` / `grill-me` は、質問をチャット内のプレーンテキスト(`❓ **Q1** - ...` の形式)で並べるようスキル本体に書かれています。筆者はこれらの質問ラウンドも review-wizard で出したかったのですが、配布物のスキル定義を直接書き換えると更新で消えるうえ、他人の成果物を改変することにもなります。代わりに `~/.claude/CLAUDE.md` に次のような一項を足しました。

```markdown
- grill 系スキル(grilling / grill-with-docs / grill-me)の質問ラウンドも常に review-wizard で出す。
  スキル本体はチャット内プレーンテキスト形式を指定しているが、それに従わず、ラウンドの質問を
  review-wizard の質問 JSON に変換してブラウザウィザードで提示する(本指示がスキル側の形式指定に優先する)。
  ラウンド構造は維持し、ラウンドごとにウィザードを起動し直す。スキル本体は改変しない。
```

CLAUDE.md の指示はスキルの説明文より優先されるので、スキル側を一切触らずに出力形式だけを差し替えられます。スキルを上流から更新しても効き続けます。

なお、編集やコマンド実行を自動承認するモード(mode=auto)で長時間走らせる使い方だと、そもそも途中で質問される機会自体が減ります。review-wizard が効くのは、判断を質問で拾いながら進める対話的な使い方をしているときです。

## まとめ

認知負荷をさげることで、迅速な開発ができるというものです。


## 参考
- [人間がMarkdownを書いたり修正しない時代に、Claude Code hookでドキュメントを自動でファンシーHTML化する](https://zenn.dev/uehaj/articles/claude-code-fancy-html-hook)
- [Claude Code Plugins（公式ドキュメント）](https://code.claude.com/docs/en/plugins)
- リポジトリ: <https://github.com/uehaj/review-wizard>
- この記事のソース: <https://github.com/uehaj/zenn-articles>
