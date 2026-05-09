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

その場合、Markdownは人間が作成も修正することはなくなるわけで、Markdown形式がドキュメントの形式としてはたして良いものかが問われます。なぜなら、Markdownは「書きやすく」「それほど読みにくくはない」形式だからです。これに対してHTMLは「書きにくく」「読みやすくできる」フォーマットです。HTMLは色やフォント、CSSやSVG図も駆使して、インフォグラフィック風に「いかにわかりやすく読みやすいか」を追求できる道具立てがそろっているからです。ようするにレビュー目的でAIが生成するドキュメントに限っていえば「Markdownばっかりでレビューしているのは見にくいので不合理、HTMLにすればレビューがより正確に、より短時間でおこなうことができる」のです。採用しない手はありません。(もちろんトークン消費が増えるなどデメリットがないわけではないのでその兼ね合いにはなる)。

あと1つ、生成されたドキュメントのファイル名をAIエージェントの出力から探してコピペするのは不毛です。Markdownであってもそうです。今生成されたドキュメントは今見るのが基本です。だから自動でブラウザで開きましょう。そのために、Claude Code の hook をつかってみましたというのがこの記事の主旨です。

## TL;DR

- Markdown書かなくなった時代には、レビュー向きではないので生成AIが出力するドキュメントはHTMLを基本にする。
- 多くの場合、ドキュメントを生成させたら中身を確認する必要があるのだから、生成直後にそのまま開くのが理にかなっている。ファイル名コピペは不毛。
- Markdownはdiffなどに有用なので生成はする。「レビュー用ビュー」としてHTMLを追加的に生成する。
- そのうえで、Claude Code の **PostToolUse hook** で、`.md` を書き出した瞬間に `claude -p` をサブプロセス起動してHTMLを生成させる

これを実装したのが以下のリポジトリです。

リポジトリ: <https://github.com/uehaj/claude-code-fancy-html-hook>

> **動作環境について**: 本スクリプトは確認ダイアログに `osascript` / `display dialog`、ファイルオープンに `open` コマンドを使用しているため、**現状 macOS 専用** です。Linux で動かす場合は `zenity` や `notify-send`、`xdg-open` 等への置き換えが必要です。

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

ポイントは **`claude` をシェルから別プロセスとして再帰的に呼ぶ** 点です。これが成立するのは、Claude Code の `claude -p` が **ヘッドレスな one-shot 実行モード** を備えているためです。
親の Claude Code は通常どおり作業を継続し、子プロセスがバックグラウンドでリッチHTMLを生成する、という処理の分離が実現できます。

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

hook は **全ての Write/Edit/MultiEdit で発火する** ため、ガード句で早期に対象外を除外しないと、作業のたびに不要な処理が走ってしまいます。

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

毎回自動でHTMLが開かれる挙動は煩わしいので、`osascript` で確認ダイアログを表示します。
**タイムアウト付き**（`giving up after 20`）にしてあるため、操作しなければ20秒で自動的に閉じます。

なお「タイムアウトしたかどうか」を厳密に判定したい場合は、`button returned of r` だけでなく `gave up of r` も併せて参照するのが正攻法です（[Apple公式の AppleScript ガイド](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/DisplayDialogsandAlerts.html)）。本スクリプトはボタン文字列の比較だけで実用上問題がないため簡略化しています。

```bash
DO_CONVERT=$(osascript -e "
set theResult to button returned of (display dialog \"Markdownファイルが更新されました...\" buttons {\"スキップ\", \"HTML生成\"} default button 2 with title \"MD → HTML Hook\" giving up after 20)
return theResult
")
[[ "$DO_CONVERT" == "HTML生成" ]] || exit 0
```

#### 4. 通常HTML（python-markdown）

GitHub 風の見やすいスタイルを当てたシンプルな HTML を `python-markdown` で生成します。
最低限のCSSを当てる程度の処理なので、変換は瞬時に完了します。

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

本記事の中核となる処理です。**親の Claude Code から、もうひとつ Claude Code を呼び出す** 構造になっています。

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
- **Markdown 本文は stdin で渡す**: 引数に埋め込むと、長い `.md` で `ARG_MAX` を超過する可能性があり、また `ps` でプロセス引数として本文が露出するリスクもあります。stdin 経由ならいずれも回避できます。
- **末尾の `&`（Bash のバックグラウンド演算子）**: ファンシー生成だけを子シェルでバックグラウンド化しています。Claude Code の hook 自体はデフォルトで同期実行されるため、`&` を付けないと数十秒〜分単位で親の Claude Code を待たせることになります。
- **プロンプトで「コードフェンスを出すな」と明示**: 指定しないと出力が \`\`\`html ... \`\`\` で囲まれてしまい、HTML としてブラウザで開けなくなります。

#### 6. 完了したら macOS 通知 + `open`

```bash
osascript -e "display notification \"ファンシーHTML生成完了\" with title \"MD → HTML Hook\""
open "$BEAUTIFUL_FILE"
```

数十秒〜数分後に、`.html` に関連付けられた **既定のブラウザ** が `open` 経由で起動します。

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

これで、Claude Code が `.md` を書き出すたびに macOS の確認ダイアログが表示され、生成を選択すると同じディレクトリの `.html/` 配下にリッチなHTMLが生成されるようになります。

---

## 使ってみての所感

### 良い点

- **レビューの視認性が高い**。プレーン Markdown を直接読むよりも、図・色・アイコン付きで概念構造を可視化した方が、内容の把握が圧倒的に速い。
- **Markdown はソースとして残せる**ため、`git diff` や AI による編集はそのまま機能する。「書く側」の強みは維持できる。
- **対話は Markdown ベースで保ったまま、ビジュアライズだけ AI に委譲できる**。CLAUDE.md や設計メモにもそのまま適用可能。
- **Claude Code が Claude Code を呼ぶ**という構造は応用範囲が広い。要約・翻訳・図解・差分説明など、いずれもこの hook パターンに載せられます。

### 注意点・ハマりどころ

- **コードフェンス問題**: `claude -p` の出力は高い確率で \`\`\`html ... \`\`\` で囲まれます。プロンプトで強く禁止しても発生する場合があるため、必要に応じて `sed` 等による後処理で除去してください。
- **ファンシー生成は数十秒〜分単位**。Claude Code の hook はデフォルト同期実行のため、何もしないと親プロセスの作業が停止します。スクリプト側で Bash の `&` を用いてファンシー生成のみ並走させてください。
- **API 課金**: 親 Claude Code とは別に子プロセスがトークンを消費します。`.md` を多く生成する場面ではコストが嵩むため、ダイアログによるオプトイン方式を推奨します。
- **macOS 専用**: `osascript` / `display dialog` / `open` を利用しているため、Linux / Windows ではそのままでは動作しません。Linux で動かす場合は `zenity` や `notify-send`、`xdg-open` 等への置き換えが必要です。
- **ファイル除外リストは育てる前提**: `CLAUDE.md` や `CHANGELOG.md` などは最初から除外しておかないと、編集のたびに不要な発火が頻発します。
- **Markdown を頻繁に生成する用途には不向き**: たとえば AI を使ってブログ記事を執筆するようなケースでは、書きかけの `.md` を何度も保存するため、その都度 HTML 生成ダイアログが立ち上がって作業の妨げになります。「ドキュメント／プランファイルを生成して人間がレビューする」ような、生成頻度がそれほど高くない用途に向いています。

---

## まとめ

- Markdown も HTML も、それぞれ得意なシーンがある。**どちらが優れているかではなく、用途で使い分ける**話。
- AI 駆動開発では **書く・直すは AI、読むは人間** という役割分担になる。
- ならば **「書く用＝Markdown」「読む用＝HTML」** の二段構えにしておくと、両方の強みを使えてレビュー時間も短縮できる（トークン効率は別問題）。
- Claude Code の **PostToolUse hook** + **`claude -p` のサブプロセス呼び出し** で、この使い分けを今すぐ自動化できる。

リポジトリはこちら:

- hook スクリプト本体: <https://github.com/uehaj/claude-code-fancy-html-hook>
- この記事のソース: <https://github.com/uehaj/zenn-articles>

「Claude Code が Claude Code を呼ぶ」系のパターンは他にも応用例が考えられます。事例があればぜひ共有してください。

---

### 参考

- [Claude Code hooks 公式ドキュメント](https://docs.claude.com/en/docs/claude-code/hooks)
- [Claude Code CLI (`claude -p`) の使い方](https://docs.claude.com/en/docs/claude-code/cli-reference)
- 着想元の議論: [@trq212 のポスト](https://x.com/trq212/status/2052811606032269638)
