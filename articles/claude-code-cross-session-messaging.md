---
title: "Claude Code のセッション同士が会話する - cross-session messaging を2台で試した"
emoji: "📮"
type: "tech"
topics: ["claudecode", "ai", "cli", "security"]
published: false
---

:::message
本記事は筆者個人の見解であり、所属する組織の公式見解ではありません。

ここで扱う cross-session messaging 自体は research preview とは書かれていませんが(v2.1.224 以降、macOS と Linux で、条件を満たせば有効)、マシンをまたぐ経路が乗る Remote Control は research preview の機能です。この領域は仕様が頻繁に、かつ大きく変わります。

本記事は**現時点の観測をまとめた暫定的な記録**です。本文の記述は執筆時点(2026年8月, Claude Code v2.1.226 で確認)のもので、後述するとおりドキュメントと実測が食い違う点や、公式の説明が見当たらない点が残っています。最新の挙動は[公式ドキュメント](https://code.claude.com/docs/en/cross-session-messaging)をご確認ください。
:::

## TL;DR

- Claude Code v2.1.224 以降、**セッション同士がメッセージを送り合えます**(cross-session messaging)。宛先の一覧は `/list-agents`(別名 `/peers`)で見られます。
- 同一マシン内はセッションごとの **Unix ドメインソケット**(受信箱)で直接届きます。Anthropic のサーバを経由しません。
- マシンをまたぐ場合は **Remote Control の接続に乗ります**。宛先が `bridge:session_...` という別形式になり、**返信は届いたメッセージの `from` 属性をそのままコピー**しないと解決しません。表示名を推測して指定すると失敗します。
- 公式ドキュメントは「マシンをまたぐ方向は返信のみで会話を開始できない」としていますが、**手元の 2 台では新規メッセージが配送されました**。
- 配管そのものは堅い作りですが、**外部から汚染された文章が隣のセッションへ渡る経路**が増えます。塞ぐなら `crossSessionInbound: "refuse"` です。
- **未確定の点がいくつも残っています**。ドキュメントと実測の食い違い、経路の暗号化の扱い、会話を始められる条件。この記事は結論ではなく、いまの観測です。

## セッションに宛先ができた

Claude Code のセッションは、これまで互いに独立していました。別のターミナルで動いているセッションのことは、こちらからは見えません。v2.1.224 でそこに宛先ができ、Claude が他のセッションへ文章を送れるようになりました。

一覧はスラッシュコマンドで見られます。

```
$ /list-agents
Other Claude sessions (55):
  [idle]  ·  <project-a>  ·  /Users/<user>/work/<project-a>  ·  started 20h ago
  [idle]  ·  synchronous-honking-koala  ·  /Users/<user>/work/<project-b>  ·  started 20h ago
  ...
  [idle]  ·  <host>-iterative-clover  ·  Remote Control
  [idle]  ·  DOOM を正規表現で実装  ·  Remote Control
  ...
```

行は 2 種類あります。**作業ディレクトリが出ている行が同一マシンのセッション**、**`Remote Control` と出ている行がこのマシンの外のセッション**です。[公式ドキュメント](https://code.claude.com/docs/en/cross-session-messaging)は一覧の対象をこう定義しています。

> * **Subagents**: agents running inside the current session. Agent team teammates aren't listed; Claude messages them through the team's own roster.
> * **Your other local sessions**: Claude Code sessions running on the same machine, including background sessions. A session appears only when it binds an inbox socket.
> * **Sessions beyond this machine**: shown while Remote Control is connected and labeled `Remote Control`. These are your sessions on other machines and your Claude Code on the web sessions.

3 番目が曲者で、**別マシンのセッションとクラウド(Claude Code on the web)のセッションが同じラベルで混ざります**。一覧を見ただけではどちらか分かりません。後述しますが、送信してみると結果に書かれています。

なお、これは `claude agents` で開く Agent view とは別の一覧です。あちらは supervisor 配下のバックグラウンドセッションの管理画面で、他の端末で開いている対話セッションは映りません。`/list-agents` には映ります。

## 受信箱の実体はソケット1本

「一覧に出る条件」は、名前でも設定でもなく**受信箱のソケットを bind しているかどうか**です。

> Claude Code binds an inbox socket for each session with cross-session messaging enabled, where other sessions on the machine deliver messages. It restricts the socket to your operating-system user, so on a shared machine another user's sessions can't reach it.

自分の受信箱のパスは環境変数で渡ってきます。実体を見てみます。

```
$ echo $CLAUDE_CODE_MESSAGING_SOCKET
/tmp/cc-socks/65171.sock

$ ls -l /tmp/cc-socks/65171.sock
srw-------  1 <user>  wheel  0  8月  8 23:08 /tmp/cc-socks/65171.sock
```

先頭の `s` がソケット、パーミッションは `600`、ファイル名は PID です。`/tmp/cc-socks/` には動作中のセッションの分だけ並びます。`/status` の `Peer address` 行にも `uds:` 付きで表示されます。

この 1 本から、性質がいくつも導かれます。

- **同一マシン内の配送は Anthropic のサーバを通りません**。ソケットに直接書き込まれます。
- **ファイルシステムを共有していない相手には届きません**。コンテナの中と外は互いに見えず、同じコンテナ内どうしなら届きます。
- **bind しないセッションは一覧にも出ず、受け取れません**。bare mode で起動した場合がこれにあたります(下のコラム)。逆に `claude -p` の常駐ワーカーは bind するので、一覧に出て受信もできます。
- `CLAUDE_CODE_MESSAGING_SOCKET` は `SessionStart` を含むすべての hook と Bash コマンドにエクスポートされるので、**スクリプトから動作中のセッションへ文章を投げ込めます**。

:::details コラム: bare mode は受信箱を持たない - そして認証も別系統

`claude -p` に `--bare` を付けると、自動読み込みを一切やめて起動します。

> Add `--bare` to reduce startup time by skipping auto-discovery of hooks, skills, plugins, MCP servers, auto memory, and CLAUDE.md. Without it, `claude -p` loads the same context an interactive session would, including anything configured in the working directory or `~/.claude`.

出典: [Run Claude Code programmatically](https://code.claude.com/docs/en/headless#start-faster-with-bare-mode)

CI やスクリプトで「どのマシンでも同じ結果」を得るためのモードです。同僚の `~/.claude` にある hook もプロジェクトの `.mcp.json` の MCP サーバも読まれません。使えるツールは Bash・ファイル読み・ファイル編集だけで、必要なものは `--settings` / `--mcp-config` / `--agents` / `--plugin-dir` などで明示的に渡します。ドキュメントには「スクリプトや SDK 呼び出しでの推奨モードであり、将来 `-p` の既定になる」とも書かれています。

この「何も読まない」の中に受信箱も含まれます。**bare mode のセッションはソケットを bind しないので、`/list-agents` に現れず、メッセージも受け取れません。**同じ `-p` でも、bare mode でなければ bind するので一覧に出ます。

もうひとつ、認証系統が変わる点は見落としやすいところです。

> In bare mode, Claude Code never reads OAuth credentials or the system keychain. For the Anthropic API, set `ANTHROPIC_API_KEY` in the environment, with a key created in the [Claude Console](https://platform.claude.com), or supply an `apiKeyHelper` in the `--settings` JSON. Amazon Bedrock, Google Cloud's Agent Platform, and Microsoft Foundry continue to read their own provider credentials as usual.

**bare mode では claude.ai のサブスクリプションのログインが使われません。**`ANTHROPIC_API_KEY`(または `apiKeyHelper`)が必要になり、課金は API 側に載ります。Bedrock などのプロバイダ認証はこれまでどおり読まれます。

裏を返すと、対話セッションや通常の `claude -p` はサブスクのログインで動き、受信箱も持ちます。「サブスクで動くセッション同士がメッセージを送り合う」のが本記事の対象で、bare mode はその輪の外にいる、という整理になります。

:::

## 送っているのはなにか

ここまで経路の話をしてきましたが、そこを流れるものは何かというと、**ただの平文のテキスト 1 通**です。

> A message is a piece of text one Claude writes to another, never conversation history or files. To move a whole conversation or its context, [resume the session](https://code.claude.com/docs/en/sessions#resume-a-session) instead.

会話履歴もファイルも運びません。実際に受け取ったメッセージは、こういう形で包まれて届きます。

```
<cross-session-message from="bridge:session_01TEGUhN..." from-name="..." from-mode="prompting">
Reply received — two-way cross-machine messaging works, ...
</cross-session-message>
```

送り主の名前と返信先(`from`)が付き、中身は書かれた文章そのものだけです。受け取った側に見えるのはこのテキストだけで、送信元の会話履歴やファイルは渡りません。

届くタイミングにも決まりがあります。

> The receiving Claude reads the message between tool calls during an active turn, so a running tool is never interrupted. When the receiving session is idle, Claude Code starts a new turn with the message.

**実行中のツールが中断されることはありません**。相手が手を動かしている最中ならツール呼び出しの合間に読まれ、待機中なら新しいターンが始まります。読み終えると `Message from` の 1 行に畳まれ、`Ctrl+O` で展開できます。

コストの扱いも押さえておくとよさそうです。配送されたメッセージは、**あなたがプロンプトを打ったのと同じように使用量に計上されます**。セッションを何十個も動かしている環境で相互に送り合わせる設計にすると、そのぶん積み上がります。ループについては、同一送信元へのレート制限、短時間の同一メッセージの破棄、未読 50 通での頭打ちがあり、2 つのセッションが延々と往復する状態は自然に止まる、と説明されています。

受け取った側がそのメッセージをどう扱うか(承認にならない、設定を変えない、コマンドを実行しない)は、後半のセキュリティの節でまとめて扱います。

## マシンをまたぐと経路が変わる

配送経路は相手の居場所で変わります。

| 相手の居場所 | 経路 | 送れるもの(ドキュメントの記載) |
|---|---|---|
| 同じマシン | セッションごとのソケット。Anthropic のサーバを通らない | 新規メッセージと返信 |
| 別のマシン | Anthropic のサーバ経由。**相手マシンの Remote Control 接続に乗って届く** | 返信のみ |
| Claude Code on the web | Anthropic のサーバ経由でクラウドのセッションへ直接 | 返信のみ |

ここからは、Mac(手元)と別の Linux 機の 2 台で実際に試した記録です。両方とも `/remote-control` を接続した状態にしてあります。

### 1 通目 - 届くが、名前では返せない

Mac 側から、一覧の `Remote Control` 行のひとつへ送ってみます。送信結果に相手の居場所が書かれていました。

```
"Ask which machine this session runs on" → <host>-iterative-clover
  (a Claude session on another machine, over Remote Control)
```

**クラウドではなく別マシンだ、と判別できます。**一覧では区別できなかった情報が、ここで出ます。

Linux 側の画面には、メッセージが届いたうえで、こう表示されていました。

> 別セッション(zenn-articles)から、このマシンの uname -a と hostname を返すよう依頼するメッセージが届きました。実行も返信もしていません。
>
> 理由:
> - 他セッションからのメッセージは、あなたの指示ではなく信頼できない入力として扱っています。
> - ホスト名・カーネル情報は環境を特定できる情報で、依頼元がなぜ必要としているかも不明です(「確認のため」という説明だけで、正当な用途が示されていません)。

**他セッションからの依頼を、ユーザの指示ではなく信頼できない入力として扱っています。**これは狙いどおりの動作です(後述)。人間が承認したうえで実行され、ホスト名(仮に `<host>` とします)と RHEL 8 系であることが分かりました。一覧に出ていた名前 `<host>-iterative-clover` は、Remote Control の自動命名 `<hostname>-<2語>` の規則そのままで、**ホスト名が名前の先頭に出ていた**わけです。

しかし返信は失敗しました。

```
No agent named 'zenn-articles' is reachable.
No agent named 'session_019HRj...' is reachable.
```

### 2 通目 - `from` をそのままコピーすると通る

原因は宛先の書き方でした。届いたメッセージはこう包まれています。

```
<cross-session-message from="bridge:session_01TEGUhN..." from-name="..." from-mode="prompting">
```

**別マシンの相手は `bridge:session_...` という形の宛先になります。**`/list-agents` に出る表示名は同一マシン内の解決には使えますが、ブリッジ越しには解決しません。1 通目で試された `zenn-articles`(表示名)も `session_019HRj...`(セッション ID)も、どちらもこの形ではありません。

そこで 2 通目に「`from` 属性の値をそのまま `to` にコピーしてください」と書いて送ったところ、返信が届きました。

> Reply received — two-way cross-machine messaging works, and copying the `from` attribute verbatim as `to` was the fix (my earlier attempt used the bare name `zenn-articles`, which did not resolve).

`bridge:` という接頭辞は Remote Control 接続を指しているようです。hook に渡る環境変数にも `CLAUDE_CODE_BRIDGE_SESSION_ID`(v2.1.199+)があり、「Remote Control 接続が生きている間、その Remote Control セッション ID が入る」と説明されています。

### ドキュメントとの食い違い

上の表のとおり、公式ドキュメントはマシンをまたぐ方向を返信のみと明記しています。

> **Reply across machines**: answer a message that arrived from one of your sessions on another machine or on the web. Across machines, Claude can only reply. It can't start the exchange.

ところが**今回の 1 通目は、こちらから始めた新規メッセージで、相手に配送されました**。ドキュメントの記述と食い違います。この会話がそれ以前に何らかの形で始まっていた可能性を完全には否定できないので断定は避けますが、少なくとも「両側が Remote Control 接続済み」の条件では、こちらから話しかけられました。

もうひとつ、バージョンについて。送信側の Mac は v2.1.226 でしたが、受信側の Linux は**ディスク上 2.1.226 / 実行中のプロセスは 2.1.220**という状態でした(更新後に再起動していないため)。**片側が 2.1.220 のままでも疎通しています**。

## セキュリティをどう見るか

配管の作りと、そこを流れる文章は分けて考えるのがよさそうです。

### 機構として守られている部分

- **ソケットは OS ユーザ限定**(実測で `600`)。共有マシンで他ユーザからは触れません。
- **メッセージは承認になりません**。

  > **It can't approve anything**: a message from another session never counts as your consent, so it can't answer a pending permission prompt on your behalf.
  > **Commands don't run**: a command in the message's text, such as `/compact`, arrives as plain text. Claude Code never executes it.
- **受信側の権限がそのまま効きます**。メッセージに従って何かするにも、通常どおり許可を求められます。
- **権限プロンプトを飛ばす設定のセッションほど厳しくなります**。既定では、受信側が `bypassPermissions` 相当のとき、送信側も同じでない限りメッセージは保留され、人間の承認待ちになります。
- ループ抑制(同一送信元のレート制限、短時間の同一メッセージ破棄、未読 50 通で頭打ち)。

### 危ういと思う部分

**1. 肝心の一線がモデルへの指示止まりです。**

> Claude is instructed never to ask another session for an action that was denied or blocked in its own session

自分が拒否された操作を隣のセッションに頼む(権限ロンダリング)の防止は、機構ではなく指示です。最終的に効くのは受信側の権限チェックと人間の承認で、そこが本当の砦になります。

**2. 汚染された文章の横展開経路が増えました。**あるセッションが Web ページや issue 本文からプロンプトインジェクションを受けると、そのセッションが**あなたの他のセッションに話しかけられます**。今回の実験がその縮図です。受け取った側は正しく警戒して人間に判断を仰ぎましたが、**人間が「実行してよい」と答えた時点でコマンドは走りました**。

**3. ソケットに書ける相手は「他ユーザ以外の全員」です。**`600` が防ぐのは他ユーザだけで、自分のユーザ権限で動くプロセスなら何でも投げ込めます。npm の postinstall や雑に入れた CLI ツールが、**動作中の Claude に指示文を差し込む足場**を得ます。

**4. マシンをまたぐと記録がサーバに残ります。**

> While Remote Control is connected, the session transcript, including your messages, Claude's responses, and tool activity, is stored on Anthropic servers.

**5. 一覧そのものが環境の情報です。**筆者の環境では 55 セッションが並び、ローカル分は作業ディレクトリの絶対パスまで表示されました。読めるのは同じマシンの自分のセッションだけですが、2 や 3 が成立したときの下見の材料にはなります。

総じて「穴だらけ」ではなく、**人間の承認疲れに耐性がない設計**という評価が近いと思います。承認ダイアログが日常になった環境では、最後の砦が薄くなります。

### 絞る設定

用途がないなら受信を止めるのが一番効きます。

```json
{
  "crossSessionInbound": "refuse",
  "permissions": { "deny": ["SendMessage", "ListAgents"] },
  "isolatePeerMachines": true
}
```

- `crossSessionInbound` は `accept` / `hold` / `refuse` の 3 値です。`refuse` は届いたものを配送せず捨てます。**プロジェクト設定・ローカル設定に置いた `refuse` は他のどの設定より優先されます**。
- `deny` 側は、こちらから送る・一覧することを止めます。どちらも指定子なしの素のツール名で書きます。
- `isolatePeerMachines: true` は、マシンをまたぐ送信のたびに承認を要求します。`bypassPermissions` でも効きます。
- Remote Control 自体が不要なら `disableRemoteControl` があります。

現実的な落としどころは、**業務リポジトリを触るセッションだけプロジェクト設定で `refuse`**、実験用は開けておく、あたりだと思います。

## おわりに - まだ確定していないこと

セッション間の通信路ができたことで、「片方で分かったことを、もう片方に伝える」がツールの仕事になりました。並行して worktree を掘っているときなどは、実際に効く場面がありそうです。

一方で、今回いちばん印象に残ったのは、返信できずに詰まった場面でした。表示名では解決せず、`from` 属性をそのまま写して初めて通る。**宛先の書き方ひとつで沈黙する**というのは、機能そのものより先に知っておきたい類の話でした。

そして、調べるほど**確定していない点**が出てきました。現時点で筆者が答えを持っていないものを、そのまま挙げておきます。

- **マシンをまたぐ会話を始められる条件**。ドキュメントは「返信のみ、開始はできない」としていますが、手元では新規メッセージが通りました。どちらが意図された仕様なのか、条件によって変わるのかが分かりません。
- **経路の暗号化**。同一マシン内はソケットで完結しますが、マシンをまたぐ分は Anthropic のサーバを経由します。公式の記述は経路の TLS までで、両端で鍵を持つ形の暗号化には触れられていません。セッション間メッセージは、送信側から受信側へのペイロードであって、中継役が中身を読める必要があるものではありません。ここは今後の説明を待ちたいところです。
- **`from-mode` 属性の意味**。届いたメッセージには `from-mode="prompting"` が付いていましたが、この値が何を表すのかを説明した記述を見つけられていません。送信側の権限モードを示している可能性はありますが、推測の域を出ません。

いずれも仕様が動けば変わる話です。**この記事は結論ではなく、v2.1.226 時点の観測**として読んでください。追って分かったことがあれば書き足します。
