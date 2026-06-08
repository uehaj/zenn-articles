---
title: "Claude Code のセッション名を作業ディレクトリ名に自動命名し、tmux/iTerm2 にも反映する"
emoji: "🏷️"
type: "tech"
topics: ["claudecode", "hook", "tmux", "iterm2", "cli"]
published: true
---

## この記事はこんな人向けです

- Claude Code を複数プロジェクトで使い分けていて、セッション一覧の見分けに困っている人
- セッション名を毎回 `--name` や `/rename` で手付けするのが地味に面倒な人
- tmux / iTerm2 を併用していて、ターミナルのタブ名・セッション名もまとめて揃えたい人
- `SessionStart` フックと `sessionTitle` の実用的な使い方を知りたい人

## はじめに

NTTテクノクロスの上原です。

Claude Code を複数のプロジェクトで使うようになってから、セッション一覧が AI 自動生成タイトルで埋まり、どれがどの作業なのか一目では見分けづらくなった、という感覚が少しずつ強くなっていきました。

「Fixing the bug in ...」「Implementing the feature ...」のような似たタイトルが並ぶと、結局どのタブがどのリポジトリだったか分からなくなります。本当は**作業ディレクトリ名さえ見えれば十分**なことが多いのに、標準では自動でそうはならず、`--name` か `/rename` の手動指定が必要です。とはいえ、新しいセッションを開くたびに手で名前を付けるのは、地味に続かない作業です。

そこで筆者は、**`SessionStart` フックで「セッション名＝作業ディレクトリ名（basename）」を自動化し、ついでに tmux のセッション名と iTerm2 のタブ名も同じ名前に揃える**形に寄せていきました。この記事では、その仕組みと設定手順、ハマりどころをまとめます。

## TL;DR

- Claude Code のセッション名は `--name` か `/rename` で**手動**です。毎回つけるのは地味に面倒です。
- **`SessionStart` フック**が `hookSpecificOutput.sessionTitle` を返すと、セッション名をプログラムで設定できます。
- これで「**セッション名 = 作業ディレクトリ名（basename）**」を自動化し、**tmux の中なら tmux のセッション名と iTerm2 のタブ名も、tmux コマンドだけで同じ名前に揃え**ます。
- `/rename` で手動上書きした場合も、**`UserPromptSubmit` フックが次のプロンプト送信時に tmux / iTerm2 へ追従**させます。

:::message
本記事は [DevelopersIO の記事「Claude Code でセッションを自動命名する」（2026-05-18）](https://dev.classmethod.jp/articles/claude-code-auto-session-named/) と同じ「`hookSpecificOutput.sessionTitle` でセッションを自動命名する」アイデアがベースです。本記事の差分は **(1) `UserPromptSubmit` ではなく `SessionStart` で1回だけ命名する**、**(2) 名前をパスではなく basename にする**、**(3) tmux セッション名と端末タイトルにも反映する**、**(4) `/rename` 後の tmux/iTerm2 への自動追従** の4点です。
:::

## 背景：セッション名はどう決まるか

複数プロジェクトを行き来していると、セッション一覧が AI 自動生成タイトルで埋まって見分けづらくなります。たいていは**作業ディレクトリ名**で十分なのに、標準では自動でそうはならず、`--name` か `/rename` の手動指定が必要です。

セッション名の決定優先順位は次のとおりです。

| 優先度 | 方法 |
|---|---|
| 高 | `claude -n <name>` / `/rename`（手動・最優先） |
| 中 | フック（`SessionStart` 等）の `sessionTitle` |
| 低 | AI 自動生成タイトル（会話内容から） |

つまり**フックで自動命名しても、`/rename` の手動指定は常に勝ちます**。普段は自動、必要なときだけ手で付け直す、という運用が成立します。

### なぜ `SessionStart` なのか（先行記事との違い）

先行記事は **`UserPromptSubmit`**（プロンプト送信のたびに発火）で命名しています。これは確実に動く実績のある方法です。一方で命名は**セッション開始時に1回決まれば十分**なので、本記事では **`SessionStart`**（セッション開始/再開時に発火）を使います。毎プロンプトでの再評価がなく、意味的にも「セッション生成時に名付ける」ほうが素直だと考えました。筆者環境（macOS / iTerm2 / tmux）では `SessionStart` の `sessionTitle` でセッション名が反映されることを確認しています。

:::message
もし環境によって `SessionStart` で効かない場合は、先行記事と同じ `UserPromptSubmit` に差し替えてください。スクリプト本体はそのまま流用できます。
:::

## 手順

### ① フックスクリプトを作る

`~/.claude/hooks/auto-session-name.sh` を作成します。端末のタブ名は、**tmux の中なら tmux コマンドで、tmux の外なら OSC（端末制御シーケンス）で**更新します。

```bash
#!/bin/bash
# SessionStart フック:
#  - 端末タブ名/セッション名を cwd の basename に揃える。
#  - 端末タブ名の更新は startup/resume の「毎回」行う（claude -c での再開でも反映）。
#  - tmux 内: セッション名 + set-titles で外側端末(iTerm2 等)を駆動。
#  - tmux 外: OSC で端末タブ名を直接更新（Claude 本体に依存しない。stdout は汚さない）。
#  - Claude のセッション名(sessionTitle)は未設定のときだけ出力し、/rename・--name を尊重。
#  - clear / compact では何もしない。
set -euo pipefail

input=$(cat)

src=$(printf '%s' "$input" | jq -r '.source // empty')
case "$src" in
  startup|resume) ;;
  *) exit 0 ;;
esac

# 既存タイトル（/rename・--name 済み）と cwd を取得。
title=$(printf '%s' "$input" | jq -r '.session_title // empty')
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
[ -z "$cwd" ] && cwd=$(pwd)
base=$(basename "$cwd")

# 表示名: 既存タイトルがあれば尊重、無ければ basename。
# set_name=1 のときだけ Claude のセッション名を新規設定する。
if [ -n "$title" ] && [ "$title" != "null" ]; then
  name="$title"; set_name=0
else
  name="$base"; set_name=1
fi

# --- 端末タブ名の更新（startup/resume の毎回。これが claude -c 対応の肝）---
if [ -n "${TMUX:-}" ] && command -v tmux >/dev/null 2>&1; then
  tmux set -g set-titles on 2>/dev/null || true
  tmux set -g set-titles-string '#S' 2>/dev/null || true
  tmux rename-session -- "$name" 2>/dev/null || true
else
  # tmux 外: OSC で端末タブ名を更新（/dev/tty が無い環境では静かにスキップ）。
  ( printf '\033]0;%s\007' "$name" > /dev/tty ) 2>/dev/null || true
fi

# --- Claude のセッション名（stdout には JSON のみ。未設定時だけ出して /rename を尊重）---
if [ "$set_name" = 1 ]; then
  jq -nc --arg t "$name" \
    '{hookSpecificOutput: {hookEventName: "SessionStart", sessionTitle: $t}}'
fi
```

ポイントは次のとおりです。

- **`startup` / `resume` のときだけ**動かします（`clear` / `compact` では何もしません）。
- **「セッション名の設定」と「タブ名の更新」を分けている**のが肝です。Claude のセッション名は**未設定のときだけ**設定し、`/rename`・`--name` を尊重します。一方、**端末のタブ名は `startup` / `resume` の毎回**更新します。セッション名は一度決まれば十分ですが、`claude -c` で再開したときにタブ名は付け直しが要るためです。
- **タブ名の更新先**は、tmux の中なら `tmux rename-session` ＋ `set-titles`、tmux の外なら `/dev/tty` への OSC です。
- **stdout には JSON だけ**を出します（タブ名の反映はコマンドや `/dev/tty` 経由で行い、stdout を汚しません。汚すと `sessionTitle` の JSON 解釈が壊れます）。
- `jq` を使います（macOS なら `brew install jq`）。

### ② `/rename` 追従スクリプトを作る

`~/.claude/hooks/sync-session-title.sh` を作成します。`/rename` でセッション名が変わったあと、次のプロンプト送信時に tmux / 端末タイトルへ追従させます。

```bash
#!/bin/bash
# UserPromptSubmit フック:
#  - session_title（現在の Claude セッション名）を読んで tmux / 端末タイトルに追従させる。
#  - /rename でセッション名が変わった直後のプロンプト送信で tmux / iTerm2 に反映される。
#  - stdout には何も出さない（sessionTitle は変更しない）。
set -euo pipefail
input=$(cat)

title=$(printf '%s' "$input" | jq -r '.session_title // empty')
[ -z "$title" ] || [ "$title" = "null" ] && exit 0

if [ -n "${TMUX:-}" ] && command -v tmux >/dev/null 2>&1; then
  tmux rename-session -- "$title" 2>/dev/null || true
  tmux set -g set-titles on 2>/dev/null || true
  tmux set -g set-titles-string '#S' 2>/dev/null || true
else
  ( printf '\033]0;%s\007' "$title" > /dev/tty ) 2>/dev/null || true
fi
```

ポイントは**stdout に何も出さない**ことです。`UserPromptSubmit` で `hookSpecificOutput.sessionTitle` を返すとセッション名を上書きしてしまいます。ここではあくまで tmux / 端末への**同期だけ**を行い、セッション名の管理は Claude に委ねます。

### ③ settings.json に登録する

`~/.claude/settings.json` の `hooks` に `SessionStart` と `UserPromptSubmit` を追加します。

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "bash ~/.claude/hooks/auto-session-name.sh" }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "bash ~/.claude/hooks/sync-session-title.sh" }
        ]
      }
    ]
  }
}
```

すでに他のフック（`PreToolUse` など）がある場合は、`hooks` オブジェクトに各キーを**足すだけ**でかまいません（既存キーは消さないでください）。

> **`bash <path>` 起動にしているのがポイントです。** こうするとスクリプトに実行権限（`chmod +x`）を付けなくても動きます。`~/.claude/hooks/` を直接 `chmod` する操作は環境によってはガードに弾かれることがあるので、これが楽です。

### ④ 設定を反映する

`settings.json` は起動時に読み込まれます。編集後は **`/hooks` を一度開く**（設定がリロードされます）か、`claude` を再起動してください。

## 動作確認

スクリプト単体はパイプで叩いて確認できます（`stdout` は JSON だけ、tmux への反映は副作用として走ります）。

```bash
$ echo '{"source":"startup","cwd":"/Users/me/work/my-project","session_title":null}' \
    | bash ~/.claude/hooks/auto-session-name.sh
{"hookSpecificOutput":{"hookEventName":"SessionStart","sessionTitle":"my-project"}}

# 既に名前があるとき → stdout は空（セッション名は上書きしない）。
# ただしタブ名の更新（tmux / OSC）は副作用として走る。
$ echo '{"source":"resume","cwd":"/x/y","session_title":"keep-me"}' \
    | bash ~/.claude/hooks/auto-session-name.sh
$        # 出力なし（exit 0）
```

あとは新しいディレクトリで `claude` を起動すると、Claude のセッション名が basename になり、tmux の中なら tmux のセッション名と iTerm2 のタブ名も同じ名前に揃います。**`claude -c` で再開したときも、セッション名は据え置きつつタブ名はそのつど付け直されます**。

`/rename` で名前を変えた場合の追従確認は `sync-session-title.sh` を直接叩いて行えます。

```bash
# /rename で "my-project" に変えたあとの状態を模擬
$ echo '{"session_title":"my-project","cwd":"/x/y"}' \
    | bash ~/.claude/hooks/sync-session-title.sh
$        # 出力なし（tmux rename-session / OSC が副作用として走る）
```

実際の操作では `/rename my-project` を実行し、次のプロンプトを送信すれば tmux と iTerm2 のタイトルが `my-project` に追従します。

## ハマりどころ

- **tmux 内では `set-titles` が肝です**。`tmux rename-session` だけでは外側端末（iTerm2）のタブ名までは変わりません。`set -g set-titles on` と `set-titles-string '#S'` を入れることで、tmux がセッション名を外側端末のタイトルとして送ってくれます。
- **iTerm2 の設定**：**Settings → Profiles → General → 「Applications in terminal may change the title」がオフ**だと、`set-titles` で送ったタイトルも無視されます。タブが変わらないときは、まずここを確認してください。
- **tmux のセッション名は共有**です。1つの tmux セッション内で複数ペインに別ディレクトリの Claude を立てると、各 `SessionStart` がセッション名を奪い合います。ペイン単位にしたいなら `tmux rename-session` を `tmux rename-window` に変えてください。
- **tmux の外**では、このスクリプトが **OSC を `/dev/tty` に書いてタブ名を直接更新**します。Claude 本体にもセッション名からタブ名を更新する動きはありますが、再開（`claude -c`）時の挙動が環境依存なので、スクリプト側で明示的に出すほうが確実です。
- **エラーにはなりません**。tmux が無ければ OSC でタブ名を更新し、セッション名が未設定のときだけ JSON を返します（`/dev/tty` が無い環境ではサブシェルごと握りつぶして静かにスキップします）。
- **`/branch` で分岐したセッションは `/rename` で付けた名前を引き継ぎません**。Claude Code の `/branch` は AI 自動生成タイトル + `" (Branch)"` を新セッション名にします。フックはその名前を尊重するため上書きしませんが、意図した名前にはなりません。分岐後に `/rename` で付け直してください。
- **設定リロードが要ります**。編集直後は反映されないことがあるので `/hooks` を開くか再起動してください。

## まとめ

`SessionStart` フックと `UserPromptSubmit` フック、2本のスクリプトで次の状態を実現できました。

- **起動時**: `auto-session-name.sh` が basename でセッション名を自動設定し、tmux / iTerm2 にも反映。
- **再開時** (`claude -c`): セッション名は据え置き、タブ名だけ付け直し。
- **`/rename` 後**: 次のプロンプト送信で `sync-session-title.sh` が tmux / iTerm2 に追従。

tmux の中では **`tmux rename-session` ＋ `set-titles`**、tmux の外では **OSC** でタブ名を揃えます。ポイントは**セッション名の設定（未設定時だけ）とタブ名の更新（毎回）を分ける**ことで、`claude -c` での再開・`/rename` のどちらにも対応できます。先行記事（[DevelopersIO](https://dev.classmethod.jp/articles/claude-code-auto-session-named/)）の `UserPromptSubmit` 方式とは、好みで使い分けてください。

## 参照

- [Claude Code でセッションを自動命名する（DevelopersIO, 2026-05-18）](https://dev.classmethod.jp/articles/claude-code-auto-session-named/) — `UserPromptSubmit` でパス＋タイムスタンプを命名する先行記事。
