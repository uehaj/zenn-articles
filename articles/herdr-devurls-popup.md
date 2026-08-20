---
title: "バックスクロールしてURLを探す旅に終止符を—URLを自動メモ—"
emoji: "🔖"
type: "tech"
topics: ["claudecode", "herdr", "terminal", "cli"]
published: true
---

:::message
本記事は筆者個人の見解であり、所属する組織の公式見解ではありません。

本文の記述は執筆時点(2026年8月, herdr 0.7.5 で確認)のものなので、最新の挙動は[公式ドキュメント](https://herdr.dev/docs/configuration/)をご確認ください。
:::

## TL;DR

- AI エージェントを使っていると、AIからの回答中に出てきた URL はスクロールして消えます。あとでバックスクロールして探すのが面倒です。
- そこで、出てきた URL をエージェント自身に整理したメモファイル「URL一覧」へ書かせます。生成した HTML/MD のfile:ファイル名なども書かせ、「このプロジェクトでアクセスする必要のある物の一覧」を自動的に作ります。
- herdrで任意のキーアサイン、たとえば `prefix+u` でこのファイルをポップアップ表示させます。表示は `fzf` の選択リストにして、Enter でその行を既定アプリ(ブラウザやエディタ)で開けます。マウスは不要です。
- 実装は herdr の設定 2 ブロック + シェルスクリプト 1 本(141 行)です。

## はじめに

NTTテクノクロスの上原です。Netflix「ガス人間」をはらはらしながら見ています。

さて、AIエージェントをつかっているときに、途中でURLを出力することがあります。「開発サーバをたてましたがURLはこれです」とか、HTMLファイルをここに生成しましたとか、調査に使った参考URLはここです、などです。

その出力直後はリンクをクリックしてブラウザで開くのは簡単ですが、数ターンさかのぼって探すとなると消えてしまったガス人間を探すのと同じようにもうたいへんです。セッションがかわったら辿るのをあきらめてもう1回出力させるほうを選びたくなります。なので、AIが出力したURLを自動でメモっておいて、それをポップアップさせてすぐにジャンプできるようにしようというノウハウです。

## 画面

キーを押すと、今いるプロジェクトの台帳がポップアップで出ます。下は素の表示(`prefix+U`)の例です。

![herdr 0.7.5 のポップアップに開発URL台帳を素の表示で出したところ (筆者の実行環境のスクリーンショット)](/images/herdr-devurls-plain.png)

## 置き場所

URL 一覧ファイルはプロジェクトごとに 1 本、その中に置いています。

```
<project>/.claude/devurls.md
```

`<project>` は、ペインの cwd から上に辿って最初に `.claude` を持つディレクトリです。Claude Code の設定を置くディレクトリをそのままプロジェクトの目印として使うので、サブディレクトリで押しても同じ台帳が開きます。`$HOME` は全プロジェクト共通の設定領域なので、目印の候補から外しています。

上まで辿っても `.claude` が見つからないときは、**`~/.claude/devurls.md` に落とします**。ここで cwd に `.claude` を作ってしまうと、`/tmp` の作業ディレクトリやたまたま開いた他人のリポジトリに、押しただけでディレクトリが増えます。台帳を見たかっただけで痕跡を残すのは筋が悪いので、プロジェクトが特定できない場合はホーム共通の 1 本に集めることにしました。

`CLAUDE.md` も修正してパス規則を書いておきます（後述）。

## 読む側 — herdr の設定

[herdr](https://herdr.dev) は AI エージェント向けのターミナルマルチプレクサで、任意のコマンドをキーに割り当てる機能をもっています。設定ファイルは `~/.config/herdr/config.toml` です。以下の 2 ブロックを追記します。

```toml
[[keys.command]]
key = "prefix+u"
type = "popup"
width = "70%"
height = "70%"
command = "$HOME/.config/herdr/scripts/open-devurls.sh"
description = "開発URL台帳を開く"

# 同じ台帳を fzf 無しの素の表示で開く
[[keys.command]]
key = "prefix+U"
type = "popup"
width = "70%"
height = "70%"
command = "$HOME/.config/herdr/scripts/open-devurls.sh --plain"
description = "開発URL台帳を開く (素の表示)"
```

キーを 2 つ割り当てています。**`prefix+u` は `fzf` の選択リスト**、**`prefix+U`(shift 付き)は `cat` の素の表示**です。同じスクリプトを `--plain` の有無で呼び分けているだけです。選んで開きたいときは小文字、行をマウスで範囲選択してコピーしたいときや `fzf` の絞り込み UI が邪魔なときは大文字、という使い分けになります。

`type = "popup"` はモーダルでポップアップダイアログを開く機能です。作業中のペインのレイアウトを動かさないので、「ちょっと見る」用途に合います。

出典: [herdr Documentation / Configuration — Custom command keybindings](https://herdr.dev/docs/configuration/#custom-command-keybindings)

### open-devurls.sh

`~/.config/herdr/scripts/open-devurls.sh` の全文です。

```bash
#!/usr/bin/env bash
# キーを押したペインの cwd に対応する開発URL台帳を表示し、選んだ行を開く。
#
# 台帳はプロジェクト内の <project>/.claude/devurls.md に置く。
# プロジェクトルートは cwd から上に辿って最初に .claude を持つディレクトリ。
# ($HOME/.claude は全プロジェクト共通の設定領域なので、$HOME は候補から除外する)
# 見つからなければ ~/.claude/devurls.md にフォールバックする。
# (無関係なディレクトリに .claude を勝手に作らないため)
# 書く側 (Claude Code) が同じパスを組み立てられることを最優先し、規則は単純に保つ。
#
# 中身はプレーンテキストの URL 列挙 (http(s):// または file:// + 絶対パス)。
# URL の後ろに説明が付いていてもよい。
#
# 表示は fzf の選択リスト。Enter で選択行の URL を open で開く (file:// も可)。
# --plain を付けると fzf を使わず cat + 1 キー待ちで表示する (prefix+U 用)。
# Esc / ctrl-c で閉じる。herdr のクリック検出や端末のホバーに依存しないので、
# マウスが使えない状況でもキーボードだけで開ける。
# fzf は PATH に無くても既知の場所を探す (herdr のポップアップは非ログインシェルで
# 起動するため、/opt/homebrew/bin などが PATH に無いことがある)。
# それでも見つからなければ従来どおり cat + 1 キー待ちにフォールバックする。
#
# herdr が渡す HERDR_ACTIVE_PANE_CWD を使う。未設定時は PWD にフォールバックする。
set -uo pipefail

# cwd から上に辿って最初に .claude を持つディレクトリを返す (見つからなければ空)。
# $HOME/.claude は全プロジェクト共通の設定領域なので候補から外す。
project_root() {
  local dir="$1"
  while [ "$dir" != "/" ]; do
    if [ "$dir" != "$HOME" ] && [ -d "$dir/.claude" ]; then printf '%s' "$dir"; return 0; fi
    dir="$(dirname "$dir")"
  done
  return 1
}

# --- fzf の execute から呼ばれる側 (選択行を open に渡す) -------------------
# 行から開く対象を 1 つ取り出す。
#   1. http(s):// または file:// の URL
#   2. 実在するパス。絶対パスのほか、プロジェクトルート基準・cwd 基準の
#      相対パスも解決する (台帳には相対パスで書かれた行も混ざる)
target_of() {
  local line="$1" tok base
  set -f  # 台帳の行に * や ? があってもパス名展開しない
  tok="$(printf '%s' "$line" | grep -oE '(https?|file)://[^[:space:]<>"'"'"']+' | head -1)"
  if [ -n "$tok" ]; then printf '%s' "$tok"; return 0; fi
  for tok in $line; do
    tok="${tok%[.,;:)]}"          # 行末の句読点を落とす
    tok="${tok#(}"                 # 前後の括弧を落とす
    [ -n "$tok" ] || continue
    case "$tok" in
      /*) [ -e "$tok" ] && { printf 'file://%s' "$tok"; return 0; } ;;
      '~/'*) [ -e "$HOME/${tok#\~/}" ] && { printf 'file://%s' "$HOME/${tok#\~/}"; return 0; } ;;
      *)
        # 相対パスらしきトークンだけを対象にする (説明文の単語を誤爆させない)
        case "$tok" in */*|*.md|*.html|*.txt|*.json|*.png|*.pdf) ;; *) continue ;; esac
        for base in "$ROOT" "$PWD"; do
          [ -n "$base" ] && [ -e "$base/$tok" ] && { printf 'file://%s/%s' "$base" "$tok"; return 0; }
        done ;;
    esac
  done
  return 1
}

# 既定のブラウザ (public.html のハンドラ) の bundle id。取れなければ空。
browser_bundle() {
  plutil -p "$HOME/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist" 2>/dev/null \
    | awk '/"public\.html"/{f=1} f&&/LSHandlerRoleAll/ && $0 !~ /"-"/ {sub(/.*=> "/,""); sub(/".*/,""); print; exit}'
}

if [ "${1:-}" = "--open" ] || [ "${1:-}" = "--browser" ] || [ "${1:-}" = "--target" ]; then
  # 相対パスの解決に使う。第3引数優先 (fzf 側から渡す)、無ければ cwd から探す。
  ROOT="${3:-$(project_root "$PWD" || true)}"
  target="$(target_of "${2:-}")" || exit 1
  case "${1}" in
    # 動作確認用。open せず抽出結果だけ出す。
    --target) printf '%s\n' "$target" ;;
    # 拡張子の既定ハンドラで開く (.html → ブラウザ, .md → エディタ など)。
    --open) open "$target" >/dev/null 2>&1 ;;
    # 拡張子を無視してブラウザで開く (.md を素のまま見たいとき)。
    --browser)
      b="$(browser_bundle)"
      if [ -n "$b" ]; then open -b "$b" "$target" >/dev/null 2>&1
      else open -a Safari "$target" >/dev/null 2>&1; fi ;;
  esac
  exit 0
fi

# --- 通常起動 ---------------------------------------------------------------
# --plain: fzf を使わず素の表示にする (キーごとに呼び分けるため)
plain=0
[ "${1:-}" = "--plain" ] && plain=1

cwd="${HERDR_ACTIVE_PANE_CWD:-$PWD}"
cwd="$(cd "$cwd" 2>/dev/null && pwd -P || printf '%s' "$cwd")"

# サブディレクトリで押しても同じ台帳が開くよう、.claude を持つ親まで遡る。
root="$(project_root "$cwd" || true)"
if [ -n "$root" ]; then
  file="$root/.claude/devurls.md"
  label="$(basename "$root")"
else
  # プロジェクトが特定できないので、ホーム共通の台帳に落とす。
  file="$HOME/.claude/devurls.md"
  label="(no project)"
fi

mkdir -p "$(dirname "$file")"
[ -e "$file" ] || printf '# %s\n\n' "$label" > "$file"

# fzf を探す。PATH → よくあるインストール先の順。
find_fzf() {
  command -v fzf 2>/dev/null && return 0
  local p
  for p in /opt/homebrew/bin/fzf /usr/local/bin/fzf /usr/bin/fzf \
           "$HOME/.fzf/bin/fzf" "$HOME/.local/bin/fzf" \
           /home/linuxbrew/.linuxbrew/bin/fzf; do
    [ -x "$p" ] && { printf '%s' "$p"; return 0; }
  done
  return 1
}
FZF="$(find_fzf)" || FZF=""
[ "$plain" = 1 ] && FZF=""

if [ -z "$FZF" ]; then
  # fzf 無し、または --plain: 表示するだけ (開くのは端末のクリックに任せる)
  cat "$file"
  printf '\n\033[2m[任意のキーで閉じる]\033[0m'
  # -n1 で 1 文字だけ待つ (Esc も 1 文字として受理される)。
  read -rsn1 _
  exit 0
fi

self="${BASH_SOURCE[0]}"
# 空行と見出し行 (#) は選択肢から除く。
grep -vE '^[[:space:]]*(#|$)' "$file" \
  | "$FZF" --no-sort --reverse --height=100% --no-mouse --prompt='open> ' \
        --header="$file  (Enter: 既定アプリで開く / ctrl-b: ブラウザで開く / Esc: 閉じる)" \
        --bind="enter:execute-silent(bash '$self' --open {} '$root')+abort" \
        --bind="ctrl-b:execute-silent(bash '$self' --browser {} '$root')+abort" \
  >/dev/null 2>&1
exit 0
```

読みどころを 5 つ挙げます。

**1. `HERDR_ACTIVE_PANE_CWD`** にキーを押したペインの cwd が入るので、「今いるプロジェクトの台帳」が開きます。

**2. 表示は `fzf` の選択リスト**にしています。台帳を眺めるだけなら `cat` で足りますが、それだと URL を開くのは端末のクリック(多くは Cmd/Ctrl + クリック)頼みです。マウスに手を伸ばすのが面倒ですし、端末の URL 検出に依存するので `file://` や絶対パスは開けないこともあります。`fzf` なら **Enter で選択行を `open` に渡せます**。

**3. 開く処理は自分自身を再実行して行います**。`fzf` の `execute-silent` から `bash '$self' --open {}` と自分を呼び、選択行を引数で受け取ります。開く処理を別ファイルに切り出さずに済みます。Enter は拡張子の既定ハンドラで開くので `.html` はブラウザ、`.md` はエディタに行きます。`.md` を素のままブラウザで見たいときのために、ctrl-b では既定ブラウザを直接指定します(bundle id を LaunchServices の設定から引く、macOS 依存の部分です)。

**4. 行から開く対象を 1 つ取り出します**。台帳の行は「URL + 半角スペース 2 個 + 説明」の形なので、まず `http(s)://` か `file://` の URL を拾います。無ければパスとして解釈しますが、ここが最初に動かなかった箇所です。当初は絶対パスだけを見ていたため、`articles/foo.md` のように**相対パスで書かれた行が開けませんでした**。台帳にはルールを決める前の行も残るので、絶対パス・`~/` 始まり・プロジェクトルート基準・cwd 基準の順に**実在するものを探す**形にしました。存在チェックは、説明文に紛れ込んだスラッシュ入りの語を誤って開かないためです。

相対パスの基準になるプロジェクトルートは、`fzf` の `--bind` から `'$root'` として子プロセスへ渡しています。渡さない場合は子プロセス側で cwd から再探索します。

**5. `fzf` の有無どちらでも動きます**。無ければ `cat` + 1 キー待ちに落ちます。`--plain` を付けたときも同じ経路を通るので、`prefix+U` はこのフォールバックをそのまま指名して呼んでいることになります。ここで表示に `less` を使わない理由がひとつあります。前述のとおりポップアップは Escape を含む入力をすべて受け取りますが、**`less` に渡すと Esc では閉じられませんでした**(`q` は効きます)。1 文字読んだら終了する `read -rsn1` なら、Esc も 1 文字として受理されます。

この 5 番目で 1 つ踏んだのが **PATH の問題**です。`command -v fzf` だけで判定すると、`fzf` を入れているのに `cat` の方に落ちることがあります。herdr のポップアップは非ログインシェルで起動するので(筆者の設定では `shell_mode = "non_login"`)、`/opt/homebrew/bin` が PATH に入っていない場合があるためです。実際 `PATH=/usr/bin:/bin` では `fzf` は見つかりません。そのため `find_fzf` で PATH を引いたあと、よくあるインストール先も探しています。**動くけれど期待した UI にならない**という壊れ方はデバッグしにくいので、環境依存で静かに劣化する箇所は明示的に潰しておくのが良さそうです。

## 書く側 — CLAUDE.md に 1 段落

台帳を書くのは Claude Code です。グローバルの `~/.claude/CLAUDE.md` に次の指示を入れてあります。

> **開発時に使用する主な URL を開発URL台帳に逐次保存する**。
> 作業中に判明した開発サーバのURL、試験対象システムが動作しているURL、管理画面・リポジトリ・issue の URL 、直近で生成したHTMLやMDのファイル名をつど追記する
> （終了時にまとめてではなく、判明した時点で）。
> 保存場所はプロジェクト内の `<project>/.claude/devurls.md`。
> `<project>` は cwd から上に辿って最初に `.claude` を持つディレクトリ（`$HOME` は除く）。
> 見つからなければ `~/.claude/devurls.md` に書く（無関係なディレクトリに `.claude` を作らない）。
> プロジェクトごとに独立する。
> 中身はプレーンテキストで 1 行 1 URL（ターミナルがホバーでリンク化するので HTML にしない）、ファイル名。
> 追記は**ファイルの先頭**に入れる（新しいものが上）。書き方は
> `{ printf '%s\n' "<新しい行>"; cat "$f"; } > "$f.tmp" && mv "$f.tmp" "$f"`。
> 既存行を読み直して整形・並べ替え・重複削除をしない（先頭に足すだけ）。
> 最小限に保ち、パスワード・トークン等は書かない。herdr 利用時は `C-z u` で開ける。

ポイントは以下のとおり。

- **「終了時にまとめてではなく、判明した時点で」** — セッションは途中で切れますし、compact も走ります。まとめて書かせる設計は、まとめて失われます。
- **「パスワード・トークン等は書かない」** — 平文のファイルなので、認証情報は書かせません。書かせるのは URL とファイル名だけに留めます。
- **「先頭に入れる」** — 台帳はプロジェクトに 1 ファイルで、増える一方です。末尾に足していくと、ポップアップを開くたびに一番見たい直近の行を探して下までスクロールすることになります。上に積めば、開いた瞬間に見えます。合わせて「既存行を読み直して整形・並べ替え・重複削除をしない」と書いてあります。台帳の整形は仕事ではありませんし、全体を書き戻す動きは、同じプロジェクトで並行しているセッションの追記を消します。

書かせているのは URL だけではなく、直近で生成した HTML/MD のファイル名も含みます。結果として「このプロジェクトで今アクセスしたい物の一覧」になっています。

## おわりに

Claude Desktopもいいのですが、こういう小技でClaude Codeの複数のエージェントをコントロールする司令塔としてカスタマイズしていけることが、
CLIを捨てられない部分になります。
