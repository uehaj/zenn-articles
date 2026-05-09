---
title: "人間がMarkdownを書いたり修正しない時代に、Claude Code hookでドキュメントを自動でファンシーHTML化する"
emoji: "🎨"
type: "tech"
topics: ["claudecode", "ai", "markdown", "html", "hook"]
published: false
---

## はじめに

X 上で見かけた **「もう Markdown じゃなくて HTML でドキュメント書いた方がよくない？」** 系の議論（[@trq212](https://x.com/trq212/status/2052811606032269638) のポスト等）には、まったく同感です。
というのも、自分は **もう半年ほど前から、ドキュメントはほぼ HTML で作っています**。AI に書かせる前提だと、書きやすさより「読みやすさ・伝わりやすさ」の方が圧倒的に効くので、自然とそうなりました。

その流れで、Claude Code の hook をひとつ仕込んでいます。

> **Claude Code が Markdown を生成した瞬間に、HTML に変換してブラウザで開く（確認ダイアログ付き）**

理由はシンプルで、

- そもそも Claude に Markdown を生成させたら、**中身を確認する必要がある**。
- VSCode の Markdown プレビューはいちいち開くのが面倒で、リッチさにも限界がある。
- そもそも自分は **もう VSCode を使わなくなった**（CLI で Claude Code を叩く運用がメイン）。
- なら、**ブラウザでそのまま開く**のが一番筋がかなっている。

この hook を、せっかくなのでもう一段おもしろくして、**通常HTMLだけじゃなく「ファンシーHTML（インフォグラフィック風）」も `claude -p` のサブプロセスで自動生成する** ようにしたものを今回は紹介します。

---

## TL;DR

- **「書くフォーマット」と「読むフォーマット」を、目的に合わせて使い分けよう** という話。
- ソースは Markdown のまま残しつつ、レビュー時に見るビューは色・図・アイコン込みの **HTML** にする。
- それを Claude Code の **PostToolUse hook** で、`.md` を書き出した瞬間に
- **通常HTML** と、`claude -p` をサブプロセス起動して作る **ファンシーHTML（インフォグラフィック風）** を
- 自動で生成・ブラウザで開く、というスクリプトにまとめた。

リポジトリ: <https://github.com/uehaj/claude-code-fancy-html-hook>

---

## 用途で使い分けるという話

Markdown のコンセプトは **「書きやすく、読みにくくはない」** です。
プレーンテキストで書けて、見出し・リスト・コードブロックぐらいは形式が分かる。「フォーマット付き文書を、**人間が手で**ストレスなく書く」ための、ちょうど良い妥協点として広まりました。

このコンセプト自体は今でも完全に有効です。人間が手で書くなら、Markdown は依然としてベストに近い選択肢のひとつ。

ただし、**Markdown の強みは「人間が書く／直す」シーンに紐づいたもの** です。
そのシーンが減ると、強みが発揮される機会も減ります。AI 駆動開発の現場で起きているのは、まさにこの「シーンの変化」です。

- **ドキュメントの初稿は AI が書く**（Claude Code、Cursor、Copilot 等が `.md` を量産）
- **修正も AI が差分パッチで書く**（人間は `Edit` ツールに「ここをこう直して」と指示するだけ）
- **人間がやるのはほぼレビューだけ**

これは「コードを人間が書かなくなる」のと同じ構図です。PLAN や設計メモといった Markdown 文書も、もはや人間が直接タイプしない・直接修正しない領域に入りつつある。
そうなったとき、**Markdown を「書く側のフォーマット」として残すのは合理的**ですが、**「読む側のフォーマット」として人間に押し付けるのは、ちょっともったいない**。

人間に残された仕事が **読む（レビューする）** ことなら、ビュー側のフォーマットは

- 色
- フォント・タイポグラフィ
- 図・アイコン・矢印
- レイアウト

をフル活用できる **HTML** の方が、理解性は上がるしレビュー時間も短縮できる。
要するに、

> **Markdown が悪いのではなく、「書く用」「読む用」で別のフォーマットを選んでいい時代になった**

というだけの話です。Markdown と HTML、どちらが優れているかではなく、**それぞれが得意なシーンに当てはめる**。

> もちろん **トークン効率** という別の軸はあります。HTML は Markdown よりタグでかさみがちで、コンテキストや課金の観点では不利です。本記事はあくまで **「人間が読む側の効率」** にフォーカスした使い分けの話、という前提で読んでください。

具体的な落としどころとして僕が選んだのは、こういう運用です。

> **「ソースは Markdown のまま残す。`.md` が書き出された瞬間に、レビュー用のリッチHTMLを並走生成する」**

- `git diff` するのも、AI が編集するのも **Markdown**（書く側に強いフォーマット）
- 人間がレビューで読むのは **HTML**（読む側に強いフォーマット）

両方の強みを使う、というシンプルな分業です。

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

hook は **全ての Write/Edit で発火する** ので、ガード句で早めに弾かないと作業のたびに鬱陶しいことになります。

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
**タイムアウト付き**（`giving up after 20`）にしてあるので、放っておけば何も起きません。

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

#### 5. ファンシーHTML（claude -p をサブプロセスで起動）

ここが本記事の山場です。**親の Claude Code から、もう一個 Claude Code を呼ぶ**。

```bash
(
    MD_CONTENT=$(cat "$FILE_PATH")
    claude -p --tools "" --output-format text "あなたはMarkdownをインフォグラフィック風HTMLに変換する専門家です。
以下のルールを厳守してください:
- 出力は <!DOCTYPE html> で始まる完全なHTMLドキュメントのみ
- 説明文、コメント、マークダウンのコードフェンス(\`\`\`)は一切含めない
- draw.ioスタイルの図、SVGアイコン、CSSアニメーション、グラデーションを活用
- 情報を流麗にビジュアライズしたインフォグラフィック風デザイン
- 単一HTMLファイルで完結（外部リソース参照なし）

変換対象のMarkdown:

${MD_CONTENT}" > "$BEAUTIFUL_FILE"

    [[ -s "$BEAUTIFUL_FILE" ]] && open "$BEAUTIFUL_FILE"
) &
```

ポイント:

- **`--tools ""`**: 子プロセスにツールを渡さない。テキスト生成だけさせる。暴走防止。
- **`--output-format text`**: パース不要の素テキスト出力。生成された HTML をそのままファイルに流せる。
- **末尾の `&`**: バックグラウンド実行。親の Claude Code をブロックしない。
- **プロンプトで「コードフェンスを出すな」と明示**: しないと \`\`\`html ... \`\`\` で囲まれて HTML として開けなくなる、という地味で致命的な事故が起きます。

#### 6. 完了したら macOS 通知 + `open`

```bash
osascript -e "display notification \"ファンシーHTML生成完了\" with title \"MD → HTML Hook\""
open "$BEAUTIFUL_FILE"
```

数十秒〜数分後に Safari/Chrome がポンと立ち上がる感じになります。

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
- **ファンシー生成は数十秒〜分単位**。同期にするとClaude Codeの作業が止まるので、必ずバックグラウンド `&` 推奨。
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
