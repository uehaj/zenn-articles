---
title: "人間がMarkdownを書いたり修正しない時代に、Claude Code hookでドキュメントを自動でファンシーHTML化する"
emoji: "🎨"
type: "tech"
topics: ["claudecode", "ai", "markdown", "html", "hook"]
published: false
---

## はじめに

X 上で見かけた **「もう Markdown じゃなくて HTML でドキュメント書いた方がよくない？」** 系の議論（[@trq212](https://x.com/trq212/status/2052811606032269638) のポスト等）には、まったく同感です。
というのも、自分は **もう半年ほど前から、Claude CodeにHTMLでドキュメント生成させています**。エージェントを使えばつかうほど、その生成物を直接人間が修正することが減るからです。プランファイルがその典型で、プランがまちがっていたらそれはAIに指示して修正させるべきで手動修正するべきではないのです。その理由は手間を減らしたいからではなく、「なぜそう出力されたか」の理由にたちもどって指示しないとAIは同じ間違いをくりかえしてしまうからです。そうすることで人間はAIと思考を共有することができます。

そうだとするともはやMarkdownは人間が作成も修正することはなくなるのです。そうなったとき、Markdown形式がドキュメントの形式としてはたして良いものかが問われます。なぜなら、Markdownは「書きやすく」「それほど読みにくくはない」形式だからです。これに対してHTMLは「書きにくく」「読みやすくできる」フォーマットです。HTMLは色やフォント、CSSやSVG図も駆使して、インフォグラフィック風に「いかにわかりやすく読みやすいか」を追求できる道具立てがそろっているからです。ようするに「Markdownばっかりでレビューしているのは見にくいので不合理、HTMLにすればレビューがより正確に、より短時間でおこなうことができるのです。採用しない手はありません。(もちろんトークン消費が増えるなどデメリットがないわけではないのでその兼ね合いにはなる)。

あと1つ、生成されたドキュメントのファイル名をAIエージェントの出力から探してコピペするのは不毛です。Markdownであってもそうです。今生成されたドキュメントは今見るのが基本です。だから自動でブラウザで開きましょう。そのために、Claude Code の hook をつかってみましたというのがこの記事の主旨です。

## TL;DR

- Markdown書かなくなった時代には、レビュー向きではないので生成AIが出力するドキュメントはHTMLを基本にする。
- 多くの場合、ドキュメントを生成させたら中身を確認する必要があるのだから、生成直後にそのまま開くのが理にかなっている。ファイル名コピペは不毛。
- Markdownはdiffなどに有用なので生成はする。「レビュー用ビュー」としてHTMLを追加的に生成する。
- そのうえで、Claude Code の **PostToolUse hook** で、`.md` を書き出した瞬間に `claude -p` をサブプロセス起動してHTMLを生成させる

これをやるのが以下です。

リポジトリ: <https://github.com/uehaj/claude-code-fancy-html-hook>

---

## 仕組み

Claude Code には [hooks](https://docs.claude.com/en/docs/claude-code/hooks) という拡張ポイントがあって、ツール実行の前後に任意のシェルスクリプトを差し込めます。
今回は `Write` / `Edit` / `MultiEdit` の **PostToolUse** に hook を仕込み、`.md` が書き出されたら次の処理を走らせます。

```
Claude Code が *.md を Write/Edit
        ↓ PostToolUse hook (JSON over stdin)
on-md-write.sh
   ├─ AppleScript ダイアログで「HTML 生成しますか？」
   ├─ python-markdown で通常HTML生成（プレーンスタイル）
   ├─ 続けて「ファンシーも生成しますか？」を聞く
   ├─ Yes なら claude -p をバックグラウンド起動して
   │     インフォグラフィック風 HTML を生成（SVG/グラデーション/CSSアニメ込み）
   └─ open でブラウザに表示
```

ポイントは **`claude` をシェルから別プロセスとして再帰的に呼ぶ** ところで、これが効くのは Claude Code の `claude -p` が **ヘッドレスな one-shot 実行モード** を持っているからです。
親の Claude Code は普通に作業を続けて、子プロセスが裏でゆっくりリッチ HTML を作ってくれる、という分離がとても気持ちいい。

### スクリプト本体（要点）

全文は [`hooks/on-md-write.sh`](https://github.com/uehaj/claude-code-fancy-html-hook/blob/main/hooks/on-md-write.sh) を見てもらうとして、要所だけ抜粋します。

#### 1. hook 入力の JSON から `file_path` を取り出す

Claude Code の hook は **stdin に JSON** を渡してきます。`tool_input.file_path` に対象ファイルが入っているのでそれを拾うだけ。

```bash
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
")
```

#### 2. `.md` 以外、特定ファイル/ディレクトリは即 exit

hook は **全ての Write/Edit/MultiEdit で発火する** ので、ガード句で早めに弾かないと作業のたびに鬱陶しいことになります。

```bash
[[ "$FILE_PATH" == *.md ]] || exit 0
case "$(basename "$FILE_PATH")" in
    CHANGELOG.md|CLAUDE.md|MEMORY.md) exit 0 ;;
esac
case "$FILE_PATH" in
    */node_modules/*|*/.html/*|*/.claude/*|*/.git/*) exit 0 ;;
esac
```

`CLAUDE.md` や `MEMORY.md` のような **人間も AI も頻繁にいじるメタファイル** はノイズになるので除外。

#### 3. AppleScript ダイアログで対話

毎回勝手にHTMLを開かれるとうざいので、`osascript` で確認ダイアログを出します。
**タイムアウト付き**（`giving up after 20`）にしてあるので、放置しても20秒で勝手に閉じます。

ちなみに「タイムアウトしたかどうか」をきっちり判定したいなら、`button returned of r` だけでなく `gave up of r` も見るのが正攻法（[Apple公式の AppleScript ガイド](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/DisplayDialogsandAlerts.html)）。今回はボタン文字列の比較だけで実害がなかったので簡略化しています。

```bash
DO_CONVERT=$(osascript -e "
set theResult to button returned of (display dialog \"Markdownファイルが更新されました...\" buttons {\"スキップ\", \"HTML生成\"} default button 2 with title \"MD → HTML Hook\" giving up after 20)
return theResult
")
[[ "$DO_CONVERT" == "HTML生成" ]] || exit 0
```

#### 4. 通常HTML（python-markdown）

GitHub 風の見やすいスタイルを当てたシンプルな HTML を `python-markdown` で生成。
これは「ちょっと色がついてるだけのプレーンHTML」なので一瞬で終わります。

```bash
python3 -c "
import markdown, pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
html_body = markdown.markdown(text, extensions=['tables', 'fenced_code', 'toc', 'nl2br'])
# ... 簡単なCSSと一緒に書き出し
"
```

> 補足: `fenced_code` は \`\`\` フェンスを `<pre><code>` に変換するだけで **シンタックスハイライトはしません**（やりたいなら別途 `codehilite` や Pygments などが必要）。`toc` は `[TOC]` マーカーがあれば目次を挿入しますが、無くても見出しに `id` を付けてくれるので、後で別ツールで TOC 生成しやすくなります。

#### 5. ファンシーHTML（claude -p をサブプロセスで起動）

ここが本記事の山場です。**親の Claude Code から、もう一個 Claude Code を呼ぶ**。

```bash
PROMPT='あなたはMarkdownをインフォグラフィック風HTMLに変換する専門家です。
以下のルールを厳守してください:
- 出力は <!DOCTYPE html> で始まる完全なHTMLドキュメントのみ
- 説明文、コメント、マークダウンのコードフェンス(```)は一切含めない
- draw.ioスタイルの図、SVGアイコン、CSSアニメーション、グラデーションを活用
- 情報を流麗にビジュアライズしたインフォグラフィック風デザイン
- 単一HTMLファイルで完結（外部リソース参照なし）

入力Markdownは標準入力から読み取って変換してください。'

(
    claude -p --tools "" --output-format text "$PROMPT" \
        < "$FILE_PATH" > "$BEAUTIFUL_FILE"

    [[ -s "$BEAUTIFUL_FILE" ]] && open "$BEAUTIFUL_FILE"
) &
```

ポイント:

- **`--tools ""`**: 子プロセスにツールを渡さない。テキスト生成だけさせる。暴走防止。
- **`--output-format text`**: パース不要の素テキスト出力。生成された HTML をそのままファイルに流せる。
- **Markdown 本文は stdin で渡す**: 引数に埋め込むと、長い `.md` で `ARG_MAX` に当たる可能性があるのと、`ps` でプロセス引数として本文が見えてしまうのが微妙。stdin 経由なら両方回避できます。
- **末尾の `&`（Bash のバックグラウンド演算子）**: ファンシー生成だけを子シェルでバックグラウンド化しています。Claude Code の hook 自体はデフォルト同期で動くので、`&` を付けないと数十秒〜分単位で親の Claude Code を待たせることになります。
- **プロンプトで「コードフェンスを出すな」と明示**: しないと \`\`\`html ... \`\`\` で囲まれて HTML として開けなくなる、という地味で致命的な事故が起きます。

#### 6. 完了したら macOS 通知 + `open`

```bash
osascript -e "display notification \"ファンシーHTML生成完了\" with title \"MD → HTML Hook\""
open "$BEAUTIFUL_FILE"
```

数十秒〜数分後に **既定のブラウザ**（`open` が `.html` の関連付けで開いてくれる）がポンと立ち上がる感じになります。

---

## 導入方法

```bash
git clone https://github.com/uehaj/claude-code-fancy-html-hook.git
cd claude-code-fancy-html-hook

# hook を ~/.claude/hooks/ に配置
mkdir -p ~/.claude/hooks
cp hooks/on-md-write.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/on-md-write.sh

# 依存
pip3 install markdown
```

`~/.claude/settings.json` に hook を登録（`settings.example.json` 参照）:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          { "type": "command", "command": "$HOME/.claude/hooks/on-md-write.sh" }
        ]
      }
    ]
  }
}
```

これで、Claude Code が `.md` を書き出すたびに macOS のダイアログが出て、Yes を押せば隣にリッチなHTMLが並ぶようになります。

---

## 使ってみての所感

### 良い点

- **レビューが目に優しい**。プレーン Markdown 直読みより、図・色・アイコン付きで概念地図が見える方が圧倒的に速い。
- **Markdown はソースとして残せる**ので `git diff` も AI 編集もそのまま。**書く側の強み**は維持できる。
- **対話を Markdown ベースで保ったまま、ビジュアライズだけ AI に外注できる**。CLAUDE.md や設計メモにそのまま使える。
- **Claude Code が Claude Code を呼ぶ**という構造は、思った以上に応用が効きます。要約・翻訳・図解・差分説明…全部この hook パターンに乗ります。

### 注意点・ハマりどころ

- **コードフェンス問題**: `claude -p` の出力は割と高い確率で \`\`\`html ... \`\`\` で囲まれます。プロンプトで強く禁止しても出ます。気になるなら sed で剥がす後処理を足してください。
- **ファンシー生成は数十秒〜分単位**。Claude Code の hook はデフォルト同期実行なので、何もしないと親の作業が止まります。スクリプト側で Bash の `&` を使ってファンシー生成だけ並走させましょう。
- **API 課金**: 親 Claude Code とは別に子プロセスがトークンを消費します。`.md` を量産する作業中は地味に効くので、ダイアログでオプトインにしておくのが吉。
- **macOS 専用**: `osascript` / `display dialog` / `open` を使っているので Linux/Windows ではそのままでは動きません。`zenity` や `notify-send` に置き換えれば Linux でも動くはずです。
- **ファイル除外リストは育てる前提**: `CLAUDE.md` `CHANGELOG.md` あたりは最初から外しておかないと作業が止まります。

---

## まとめ

- Markdown も HTML も、それぞれ得意なシーンがある。**どちらが優れているかではなく、用途で使い分ける**話。
- AI 駆動開発では **書く・直すは AI、読むは人間** という役割分担になる。
- ならば **「書く用＝Markdown」「読む用＝HTML」** の二段構えにしておくと、両方の強みを使えてレビュー時間も短縮できる（トークン効率は別問題）。
- Claude Code の **PostToolUse hook** + **`claude -p` のサブプロセス呼び出し** で、この使い分けを今すぐ自動化できる。

リポジトリはこちら:

- hook スクリプト本体: <https://github.com/uehaj/claude-code-fancy-html-hook>
- この記事のソース: <https://github.com/uehaj/zenn-articles>

「Claude Code が Claude Code を呼ぶ」系のレシピは他にも色々作れそうなので、何か面白いの思いついたら教えてください。

---

### 参考

- [Claude Code hooks 公式ドキュメント](https://docs.claude.com/en/docs/claude-code/hooks)
- [Claude Code CLI (`claude -p`) の使い方](https://docs.claude.com/en/docs/claude-code/cli-reference)
- 着想元の議論: [@trq212 のポスト](https://x.com/trq212/status/2052811606032269638)
