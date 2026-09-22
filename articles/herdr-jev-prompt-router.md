---
title: "そのプロンプト、どのプロジェクトに投げるんでしたっけ — そうだ、Jevで宛先を決めよう"
emoji: "🚦"
type: "tech"
topics: ["claudecode", "herdr", "typesafe", "typescript", "jev"]
published: true
---

:::message
本記事は筆者個人の見解であり、所属する組織の公式見解ではありません。

また、ここで使う TypeSafe の System One API は公開されて間もないものです。仕様が変わる可能性があります。本文の記述は執筆時点(2026年9月, herdr 0.9.0 / Node v23.10.0 で確認)のものなので、最新の挙動は[公式ドキュメント](https://docs.typesafe.ai/)をご確認ください。
:::

## はじめに

AI エージェントを複数のプロジェクトで並行して走らせていると、ワークスペースが増えます。筆者の手元では、社内ツールの障害調査、別プロダクトの改修、記事の下書き、実験用の使い捨てディレクトリ……といった具合に、常時 5〜10 個が開きっぱなしです。

この状態で困るのが、**思いついたことを書き留めたいときに、宛先を自分で選ばないといけない**ことです。「さっきのエラー、設定ファイルのほうも疑ったほうがよさそう」と思いついたとして、それを打ち込むべきペインがどれだったかを思い出し、そこまで移動してから入力する。移動の時点で、何を書こうとしていたか半分忘れています。

やりたいことはシンプルで、ショートカッットキーでコマンドパレットを表示させ、**プロンプトを 1 箇所で書いたら、内容から自動で宛先が決まり、そのペインの入力欄に入る**という状態です。

![herdr のポップアップに出したプロンプトパレット。ここに書くと宛先が自動で決まる (筆者の実行環境のスクリーンショット)](/images/jev-prompt-router-palette.png)

## TL;DR

- 複数の herdr ワークスペースのうち、どこに送るべきかを **TypeSafe AI の Jev（System One モデル）** に選ばせるルータを書きました。TypeScript で 343 行、**依存ゼロ**です。
- Jev は文章を生成せず、**typed な質問に対して選択肢・スコア・真偽確率だけを返す**モデルです。`POST /v1/systemone` を 1 本叩くだけで呼べます。
- 今回、候補の作り方が肝で、**`criteria` のキーを機械用の ID、値を LLM 用の説明文**にすると、返ってきた答えをそのままキーとして使えます。
- 最後に Enter は打ちません。**入力欄に文字列を置くだけ**にして、送信するかどうかの判断は人間に残しています。

## なぜ生成モデルではなく System One モデルなのか

Jev は TypeSafe AI の **System One モデル**です。公式ドキュメントでは次のように説明されています。

> Jev evaluates typed *questions* against a *state* and returns structured results directly. No text generation, no parsing. You get typed values and probability distributions that your code can branch on, sort by, and route with.

(仮訳: Jev は state に対して型のついた question を評価し、構造化された結果を直接返す。テキスト生成もパースもない。コードがそのまま分岐・ソート・ルーティングに使える、型のついた値と確率分布が得られる)

出典: [Introduction — TypeSafe AI](https://docs.typesafe.ai/introduction)

質問の型は 3 つだけです。選択肢から 1 つ選ぶ `choice`、順序のある段階で採点する `score`、真である確率を返す `noul`。1 回の呼び出しに混ぜて入れられ、それぞれ独立に並列で評価されます。今回使うのは `choice` ひとつです。

ちなみに System One という名前は、ダニエル・カーネマンが『ファスト&スロー』で広めたシステム 1 から来ています（出典: [System One — TypeSafe AI](https://docs.typesafe.ai/concepts/system-one)）。速くて直観的な判断のほう、という含意です。

分類のためだけに生成モデルを呼ぶと、「JSON で答えて」とプロンプトに書き、返ってきた文字列をパースし、想定外のキーが来たときのリトライを書く、という定型作業がついてきます。System One モデルはその層がまるごと要りません。選択肢の集合を渡せば、その中のどれかが返ってきます。

### Jev を使うには

公式サイト（[typesafe.ai](https://typesafe.ai/)）は早期アクセスのウェイトリストを案内しています。筆者も申し込んでしばらく音沙汰がありませんでしたが、その後アクセスできるようになりました。

利用権さえあれば、あとは短い話です。[コンソール](https://console.typesafe.ai/)にログインしてダッシュボードから API キーを取り、`POST https://api.typesafe.ai/v1/systemone` を叩く。それだけで、SDK も要りません。公式の [Quick start](https://docs.typesafe.ai/introduction/quickstart) では、まず Playground で `state` にテキストを入れて質問を足してみる、という手順が紹介されています。

なお 2026 年 9 月 19 日時点では、トップページが今も "Join Waitlist" と early access を掲げている一方、Quick start のほうは順番待ちに触れず「ログインしてダッシュボードからキーを取る」だけの手順になっています。新規登録がすぐ通るようになったのかどうかは、確かめられていません。

## 全体の処理フロー

```text
プロンプト (argv または対話入力)
        │
        ├── herdr agent list ─→ ワークスペースごとに代表ペインを 1 つ選ぶ
        │                        candidates: workspace_id → { pane_id, label }
        ▼
 POST api.typesafe.ai/v1/systemone
   model: 'jev-latest'
   state: プロンプト
   questions.workspace: { type: 'choice', criteria: 候補一覧 }
        │
        ▼
   answers.workspace.choice = workspace_id
        │
        ├── DUMP があれば送信前に終了 (中身を見るだけ)
        ├── DRY があればここで終了 (判定だけ)
        ▼
 herdr workspace focus → agent focus → pane send-text → notification show
```

## コード全文

`route.mts` の全文です。依存はありません。Node の組み込みモジュールと `fetch` だけで動きます。

```ts
import { execFileSync } from 'node:child_process';
import {
  closeSync, existsSync, openSync, readdirSync, readFileSync, readSync, realpathSync,
  statSync,
} from 'node:fs';
import { homedir } from 'node:os';
import { basename, join } from 'node:path';
import { createInterface } from 'node:readline/promises';

const apiKey = process.env.TYPESAFE_API_KEY;
if (!apiKey) throw new Error('TYPESAFE_API_KEY is not set (--env-file?)');
// Do not hand the key to herdr, fzf, or anything else we spawn.
delete process.env.TYPESAFE_API_KEY;

let prompt = process.argv.slice(2).join(' ').trim();
if (!prompt) {
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  prompt = (await rl.question('prompt (empty to cancel)> ')).trim();
  rl.close();
}
if (!prompt) process.exit(2);

// herdr hands plugins the running binary's path; PATH may hold a different one.
const HERDR = process.env.HERDR_BIN_PATH || 'herdr';

const herdr = (...args: string[]) => {
  const out = execFileSync(HERDR, args, { encoding: 'utf8' }).trim();
  return out ? JSON.parse(out).result : null; // send-text answers with nothing
};

// --- Claude Code session history, used as the description of each choice ---
const PROJECTS = join(homedir(), '.claude', 'projects');
const SESSIONS = 10; // how many recent sessions to take a heading from
const PROMPTS = 10; // how many recent prompts to take from the newest session
const CHARS = 120; // per-entry truncation
const TAIL = 512 * 1024; // only the end of the newest session is read

// Transcript plumbing that says nothing about what the project is for.
const NOISE = [
  '<local-command-caveat>', '<local-command-stdout>', '<command-name>', '<command-message>',
  '<command-args>', '<bash-input>', '<bash-stdout>', '<bash-stderr>', '<task-notification>',
  'Base directory for this skill:', '[Image:',
  'Another Claude session sent a message', 'This session is being continued',
  '[Request interrupted',
];

const clean = (input: unknown): string | null => {
  const raw = (typeof input === 'string'
    ? input
    : Array.isArray(input)
      ? input.filter((b: any) => b?.type === 'text').map((b: any) => b.text).join(' ')
      : '');
  // Anything with a paste in it goes entirely. Cutting the block out instead
  // looked tidier, but the closing tag repeats the id and blocks can nest, so
  // a non-greedy match ends at the wrong tag and leaks the rest. A heading is
  // not worth a parser.
  if (/<\/?pasted_content\b/i.test(raw)) return null;
  const t = raw
    .replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, '')
    .replace(/\[Image #\d+\]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!t || NOISE.some((n) => t.startsWith(n))) return null;
  return t.slice(0, CHARS);
};

const userText = (line: string): string | null => {
  try {
    const d = JSON.parse(line);
    if (d.type !== 'user' || d.message?.role !== 'user' || d.isMeta) return null;
    return clean(d.message.content);
  } catch {
    return null; // truncated line from a partial read
  }
};

const slice = (file: string, bytes: number, fromEnd: boolean): string => {
  const size = statSync(file).size;
  const start = fromEnd ? Math.max(0, size - bytes) : 0;
  const buf = Buffer.alloc(Math.min(bytes, size - start));
  const fd = openSync(file, 'r');
  try {
    const read = readSync(fd, buf, 0, buf.length, start);
    return buf.subarray(0, read).toString('utf8');
  } finally {
    closeSync(fd);
  }
};

const head = (file: string, bytes: number) => slice(file, bytes, false);
const tail = (file: string, bytes: number) => slice(file, bytes, true);

// Claude flattens the cwd into a directory name, so /a/b_c, /a/b.c and /a/b-c
// all land in the same place. The name is a lookup hint, never proof of origin:
// every file read below is checked against the cwd recorded inside it.
const projectDir = (cwd: string) => join(PROJECTS, cwd.replace(/[/_.]/g, '-'));

const belongsTo = (lines: string[], cwd: string) => {
  const want = real(cwd);
  for (const line of lines) {
    let d: any;
    try { d = JSON.parse(line); } catch { continue; }
    if (typeof d?.cwd === 'string') return real(d.cwd) === want;
  }
  return false; // nothing claims a cwd: do not assume it is ours
};

// --- what is allowed to leave this machine ---
// History is sent by default, because a router that has to be registered per
// project before it works is a router nobody turns on. The list file then holds
// the exceptions. Set HISTORY_BY_DEFAULT to false and the same file becomes an
// allow list instead - under a different name, so a deny list is never read as
// an allow list by accident. JEV_NO_HISTORY=1 holds everything for one run.
const HISTORY_BY_DEFAULT = true;
const LIST_FILE = process.env.JEV_LIST_FILE ?? join(
  process.env.HERDR_PLUGIN_CONFIG_DIR ?? join(homedir(), '.config', 'herdr'),
  HISTORY_BY_DEFAULT ? 'jev-no-history' : 'jev-allow-history',
);

const real = (path: string) => {
  try { return realpathSync(path); } catch { return path; }
};

const listed_paths = (() => {
  try {
    return readFileSync(LIST_FILE, 'utf8')
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#'))
      .map((l) => real(l.replace(/\/$/, '')));
  } catch (e: any) {
    // Only a missing default file means "no rules". Anything else - a typo in
    // JEV_LIST_FILE, a permission error - would silently turn the policy off.
    if (e.code === 'ENOENT' && !process.env.JEV_LIST_FILE) return [];
    throw new Error(`cannot read the history list ${LIST_FILE}: ${e.message}`);
  }
})();

const isListed = (cwd: string) => {
  const path = real(cwd);
  return listed_paths.some((r) => path === r || path.startsWith(`${r}/`));
};

const sendsHistory = (cwd: string) => {
  if (process.env.JEV_NO_HISTORY) return false;
  return HISTORY_BY_DEFAULT ? !isListed(cwd) : isListed(cwd);
};

// What this project has been about: one heading per recent session.
function sessionHeadings(cwd: string): string[] {
  const dir = projectDir(cwd);
  if (!existsSync(dir)) return [];
  const files = readdirSync(dir)
    .filter((f) => f.endsWith('.jsonl'))
    .map((f) => join(dir, f))
    .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs)
    .slice(0, SESSIONS);

  const sessions: string[] = [];
  for (const f of files) {
    const top = head(f, 64 * 1024).split('\n');
    if (!belongsTo(top, cwd)) continue; // a colliding directory name is not proof
    // Claude writes an ai-title near the top for named sessions; otherwise use
    // the first prompt long enough to mean something.
    const titled = top.map((l) => {
      try { return JSON.parse(l); } catch { return null; }
    }).find((d) => d?.type === 'ai-title' && d.aiTitle);
    const title = titled
      ? String(titled.aiTitle).slice(0, CHARS)
      : top.map(userText).find((t) => t && t.length >= 12);
    if (title) sessions.push(title);
  }
  return sessions;
}

// What this pane is doing right now. Keyed by the session id herdr reports, not
// by mtime: several sessions can share a cwd, and the newest file is not
// necessarily the conversation living in this pane. No id, no prompts - another
// session must never stand in for this one.
function recentPrompts(cwd: string, sessionId: string | null): string[] {
  if (!sessionId) return [];
  const file = join(projectDir(cwd), `${sessionId}.jsonl`);
  if (!existsSync(file)) return [];

  const lines = tail(file, TAIL).split('\n');
  if (!belongsTo(lines, cwd)) return [];

  const prompts: string[] = [];
  for (const line of lines) {
    const t = userText(line);
    if (t && t.length >= 8 && t !== prompts.at(-1)) prompts.push(t);
  }
  return prompts.slice(-PROMPTS);
}

// A blocked agent is sitting on its own prompt - a permission dialog or a
// y/n - so text typed there is answering that question, not starting a new
// one. A pane that has not launched yet has nowhere to put the text. Both are
// excluded outright; working is not, because an agent mid-turn still takes a
// queued follow-up in its input box, which is exactly what this tool is for.
// (herdr reports interactive_ready, but only for agents it launched itself, so
// it is absent for hand-started panes and cannot be used here.)
const acceptsDraft = (a: any) => !a.launch_pending && a.agent_status !== 'blocked';

// Among the eligible, a pane waiting for input beats one mid-turn.
const RANK: Record<string, number> = { idle: 0, done: 0, working: 3 };
const rank = (status: string) => RANK[status] ?? 1; // unknown sits between

// Same terminal is not the same conversation: a session can be switched under
// it while we are waiting on the API and on fzf.
const sessionKey = (a: any) => JSON.stringify([
  a.agent, a.agent_session?.source, a.agent_session?.kind, a.agent_session?.value,
]);

type Candidate = {
  pane_id: string; terminal_id: string; cwd: string; rank: number; session: string;
  name: string; label: unknown;
};
const candidates = new Map<string, Candidate>();
for (const a of herdr('agent', 'list').agents) {
  if (typeof a.cwd !== 'string') continue; // cwd is optional in the herdr schema
  if (!acceptsDraft(a)) continue;
  const seen = candidates.get(a.workspace_id);
  if (seen && seen.rank <= rank(a.agent_status)) continue;
  candidates.set(a.workspace_id, {
    pane_id: a.pane_id,
    terminal_id: a.terminal_id,
    cwd: a.cwd,
    rank: rank(a.agent_status),
    session: sessionKey(a),
    name: `${basename(a.cwd)} — ${a.terminal_title_stripped}`, // for humans
    label: { // for jev
      dir: basename(a.cwd),
      pane: a.terminal_title_stripped,
      ...(sendsHistory(a.cwd) ? {
        sessions: sessionHeadings(a.cwd),
        prompts: recentPrompts(a.cwd, a.agent_session?.value ?? null),
      } : {}),
    },
  });
}
if (!candidates.size) throw new Error('no agent pane to route to');

// Without an escape hatch the model must pick one of the open workspaces even
// when the prompt belongs to none of them, and a tight distribution over the
// wrong set still reads as high confidence.
const NONE = '__none__';
const criteria = {
  ...Object.fromEntries([...candidates].map(([id, c]) => [id, c.label])),
  [NONE]: 'None of these projects is the right destination for this prompt.',
};

const payload = {
  model: 'jev-latest',
  state: prompt,
  questions: {
    workspace: {
      type: 'choice',
      instructions: 'Which project should this prompt be sent to?',
      criteria,
    },
  },
};

// DUMP stops before anything leaves the machine: no request, no charge. It
// prints the whole request, the prompt included - that is sent too. DRY still
// asks jev but touches no pane.
if (process.env.DUMP) {
  console.log(JSON.stringify(payload, null, 2));
  console.error(`${candidates.size} candidates, ${JSON.stringify(criteria).length} chars. Nothing sent.`);
  process.exit(0);
}

const res = await fetch('https://api.typesafe.ai/v1/systemone', {
  method: 'POST',
  headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json' },
  body: JSON.stringify(payload),
  signal: AbortSignal.timeout(15_000),
});
if (!res.ok) throw new Error(`typesafe ${res.status}: ${await res.text()}`);
const { answers } = await res.json();

// confidence is 0-1, computed from how the probabilities are spread: one clear
// peak is high, several close candidates is low. A low value means jev could not
// separate them, so hand the choice to the human instead of guessing.
// A missing confidence is treated as no confidence: a response shape we do not
// recognise must not turn into an automatic delivery.
const CONFIDENT = 0.7;
const { choice, probabilities = {}, confidence = 0 } = answers.workspace ?? {};

if (choice === NONE && confidence >= CONFIDENT) {
  console.error('no open workspace fits this prompt; not sending');
  process.exit(2);
}

let wid: string = choice;
if (confidence < CONFIDENT || !candidates.has(wid)) {
  const list = [...candidates.keys()]
    .sort((a, b) => (probabilities[b] ?? 0) - (probabilities[a] ?? 0))
    .map((id) => `${id}\t${String(Math.round((probabilities[id] ?? 0) * 100)).padStart(3)}%  ${candidates.get(id)!.name}`)
    .join('\n');
  try {
    const picked = execFileSync('fzf', [
      '--delimiter=\t', '--with-nth=2..', '--layout=reverse', '--height=100%',
      `--prompt=confidence ${confidence.toFixed(2)} — pick one > `,
    ], { input: list, encoding: 'utf8', stdio: ['pipe', 'pipe', 'inherit'] });
    wid = picked.split('\t')[0].trim();
  } catch (e: any) {
    // Never fall back to sending on our own: this branch exists because jev
    // could not decide. No picker, no delivery.
    if (e.code === 'ENOENT') throw new Error('fzf is needed to choose; not sending');
    process.exit(2); // esc or ctrl-c: cancelled
  }
}

const target = candidates.get(wid);
if (!target) throw new Error(`unknown workspace in the answer: ${wid}`);
console.error(`-> ${wid} ${target.name} (${target.pane_id}) confidence ${confidence.toFixed(2)}`);
console.error(probabilities);

if (process.env.DRY) process.exit(0);

// Focus first: workspace.focus does not itself request a repaint, so it only
// reaches the attached client when something later redraws. send-text and the
// toast both do, so ordering is what makes the view actually move.
// The pane may have closed or moved while we were waiting on the API and on
// fzf. Resolve it again by terminal id and refuse to type into something else.
const live = herdr('agent', 'list').agents
  .find((a: any) => a.terminal_id === target.terminal_id);
if (!live || live.workspace_id !== wid || live.cwd !== target.cwd) {
  throw new Error(`${target.name} is gone or has moved; not sending`);
}
if (!acceptsDraft(live)) {
  throw new Error(`${target.name} is waiting on its own prompt now; not sending`);
}
if (sessionKey(live) !== target.session) {
  throw new Error(`${target.name} switched session; not sending`);
}

herdr('workspace', 'focus', wid);
herdr('agent', 'focus', live.pane_id);
herdr('pane', 'send-text', live.pane_id, prompt.replace(/\p{Cc}+/gu, ' ').trim());
herdr('notification', 'show', `-> ${target.name}`, '--sound', 'none');
```

`tsx` や `ts-node` は入れていません。Node.js 23.6 以降は、`.mts` の型注釈をフラグなしで剥がしてそのまま実行できるからです。つまりこのコードの型注釈は、実行時には何の効果も持たない、読み手のためのドキュメントです。

## ポイント解説

UIですが、Claude Codeの新機能[Claude Mods](https://github.com/anthropics/claude-code/issues/91870)をつかうことも考えましたが、ワークスペースがきりかわったほうがいいのでHerdr連携にしました。Claude Modsだけなら[Cross Sesssion Messaging](https://code.claude.com/docs/en/cross-session-messaging)でプロンプトを送り合うみたいな実装にもできるでしょう。

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
const acceptsDraft = (a: any) => !a.launch_pending && a.agent_status !== 'blocked';

const RANK: Record<string, number> = { idle: 0, done: 0, working: 3 };
const rank = (status: string) => RANK[status] ?? 1; // unknown はその中間

if (!acceptsDraft(a)) continue;
const seen = candidates.get(a.workspace_id);
if (seen && seen.rank <= rank(a.agent_status)) continue;
```

まず**下書きを置けないペインを外します**。起動前のものと、`blocked` のものです。`blocked` は自分の y/n プロンプトで止まっているので、打ち込んだ文字はその回答として消費されてしまいます。`working` は外しません。作業中のエージェントも入力欄にキューとして受け取れますし、それこそがこのツールの用途です。

残ったものの中では、**入力を待っているペインを作業中のペインより優先します。**同順なら先勝ちです。

ここは最初「すでに候補がいて、かつ今見ているのが `working`」ならスキップする、という後勝ちの 1 行でした。単純ですが穴があって、`idle` の候補が後から来た `blocked` や `unknown` に上書きされます。宛先のワークスペースは合っているのに、入力を受け取れないペインに打ち込む、という外し方をします。

なお herdr は `interactive_ready`（入力を受け付けられるか）も返しますが、**これは herdr 自身が起動したエージェントにしか付きません**。手で `claude` と打って始めたペインでは常に欠落するので、絞り込み条件には使えませんでした（`skip_serializing_if` で JSON からも消えます）。


畳んだあと、各ワークスペースに**そのプロジェクトの説明文**を付けます。ここが判定精度をいちばん左右する部分です。

最初はディレクトリ名とターミナルタイトルだけを渡していました。これだと「その名前から連想できること」しか材料がなく、ディレクトリ名が日付とローマ字の羅列だと手も足も出ません。そこで **Claude Code のセッション履歴**を足しています。

```ts
label: {
  dir: basename(a.cwd),
  pane: a.terminal_title_stripped,
  ...(sendsHistory(a.cwd) ? {
    sessions: sessionHeadings(a.cwd),
    prompts: recentPrompts(a.cwd, a.agent_session?.value ?? null),
  } : {}),
},
```

`history()` が読むのは `~/.claude/projects/<cwd を - で符号化したディレクトリ>/*.jsonl` です。ここに Claude Code が会話ログを 1 セッション 1 ファイルで置いています。

| キー | 中身 | 引き方 |
|---|---|---|
| `sessions` | そのプロジェクトが何を扱ってきたか | mtime の新しい順に 10 セッション。各ファイル先頭の `ai-title`（Claude が付けたセッション名）を使い、無ければ最初のまともなプロンプト |
| `prompts` | **そのペインでいま何をしているか** | herdr が返す `agent_session.value`（セッション ID）でファイルを名指しし、直近 10 件 |

`prompts` を mtime で引いてはいけません。同じ cwd に複数セッションがあると、別ターミナルで開いた無関係な会話が「最新」になります。実際、手元の 5 ワークスペースのうち 1 つで、ペインの本来のセッションと mtime 最新が食い違っていました。ID が取れないときは**他のセッションで代用せず、`prompts` を空にします**。

ログには判定の役に立たないものが大量に混ざります。`<bash-input>` とその出力、`<task-notification>`、他セッションからの伝言、スキルの起動文、compaction の要約、画像のパス。これらを `NOISE` で頭から落とし、`<system-reminder>` は中身ごと消し、**貼り付けを含む項目は丸ごと捨て**、1 件 120 文字で切り、`push` のような一語だけの指示（8 文字未満）と直前と同じ内容は捨てています。残るのは「このプロジェクトで人間が何を言ってきたか」だけです。

貼り付けだけを切り出して地の文を残す、という実装を最初は書きました。これは不十分でした。閉じタグが `</pasted_content id="49da">` と**貼り付け ID を繰り返す**うえ、入れ子にもなり得るので、非貪欲マッチが手前の閉じタグで止まって中身が残ります。タグ記法を含むログを貼り付けるだけで起こります。見出し 1 行のためにパーサを書く価値はないので、項目ごと捨てる方に倒しました。

最新セッションのログは 15MB を超えることもあるので、全部は読みません。直近プロンプトは末尾 512KB だけ、`ai-title` は先頭 4KB だけを読んでいます。

#### 何が外に出るのかを決められるようにする

ここで一度立ち止まる必要があります。**選ばれなかったプロジェクトの履歴も、毎回まとめて外部 API に送っています。** 宛先を決めるには全候補の説明が要るので、構造上そうなります。120 文字に切っているのは要約であって、匿名化ではありません。

既定は「送る」にしました。使う前にプロジェクトを登録しろというルータは、結局誰も有効にしないからです。そのうえで、出したくないプロジェクトを外せるようにしています。

```
# $HERDR_PLUGIN_CONFIG_DIR/jev-no-history （1 行 1 パス接頭辞）
/Users/ueha-j/work/2026_Trial_Security_Check
```

ここに挙げたパス配下は `dir` と `pane` だけになります。`JEV_NO_HISTORY=1` を付ければその実行だけ全プロジェクトを対象にできますし、コード側の `DENY_DEFAULT` を `true` にすれば、登録したものだけ送る運用にも切り替わります。

送る前に中身を見たいなら `DUMP=1` です。**API を呼ぶ手前で止まる**ので、通信も課金も発生しません。

```bash
DUMP=1 node --env-file=.env route.mts "テスト"
# 5 candidates, 4555 chars. Nothing sent.
JEV_NO_HISTORY=1 DUMP=1 node --env-file=.env route.mts "テスト"
# 5 candidates, 278 chars. Nothing sent.
```

`DRY=1` のほうは判定だけを見るモードで、こちらは jev を呼びます。名前が紛らわしいので分けました。ついでに、読み込んだ API キーは `delete process.env.TYPESAFE_API_KEY` で環境から落としています。この先 `herdr` と `fzf` を子プロセスとして起動するので、渡す必要のないものは渡しません。

### 3. criteria のキーと値で役割を分ける

`choice` 型でいちばん効いているのがここです。

```ts
const criteria = {
  ...Object.fromEntries([...candidates].map(([id, c]) => [id, c.label])),
  [NONE]: 'None of these projects is the right destination for this prompt.',
};
```

公式ドキュメントでは `choice` の `criteria` は "The answer options, as a map. Each key is an option name and each value is a description of that option."（仮訳: 答えの選択肢をマップで渡す。キーが選択肢の名前、値がその説明）と説明されています（出典: [Choice — TypeSafe AI](https://docs.typesafe.ai/primitives/choice)）。このキーと値で、役割をきれいに分けられます。

| 位置 | 中身の例 | 役割 |
|---|---|---|
| **キー** | `"w68"` などの `workspace_id` | 選択肢の識別子。判定後に `answers.workspace.choice` としてそのまま返る |
| **値** | `{ dir, pane, sessions, prompts }` | その選択肢の具体的な説明。モデルが読み取る |

値は文字列でなくてもかまいません。公式ドキュメントには、`instructions` と `criteria` の値は `string` / `object` / `array` のいずれでもよいと明記されています（出典: [Advanced: structure — TypeSafe AI](https://docs.typesafe.ai/primitives/advanced)）。セッション履歴のような複数の要素を渡すなら、文字列テンプレートに詰め込むよりオブジェクトのほうがキーが付くぶん明確です。

つまりこの 1 行で「**機械が使う ID**」と「**モデルが読む説明**」を同時に渡しています。返ってきた `choice` をそのまま `candidates.get()` のキーにできるので、後段で名前の逆引きをする必要がありません。ID を人間可読な名前にしたい誘惑に駆られますが、その必要はないわけです。ドキュメントによればキー側もモデルには送られますが、判定材料は値のほうに寄せておけば足ります。

なお `label` をオブジェクトにしたので、ログや通知に出す人間向けの文字列は `name` として別に持たせています。

`answers.workspace.probabilities` には全選択肢にわたる確率分布が入ります（合計が 1 になります）。「w68 が 0.62、w5Q が 0.31」のように**どれくらい迷ったか**が見えるので、stderr に出してルーティングの当たり外れを目視できるようにしています。答えには確率の散らばり具合から計算した `confidence` も付いてくるので、これが低いときだけ人間に投げる、といった分岐にも使えます（出典: [Confidence-gated routing — TypeSafe AI](https://docs.typesafe.ai/patterns/confidence-routing)）。

なお今回は HTTP を直接叩いているので、`await res.json()` の戻りは `any` で、`answers.workspace.choice` に型は付きません。型を効かせたいなら公式の [JavaScript SDK](https://docs.typesafe.ai/sdk/javascript) を使う手もありますが、質問 1 つのために依存を 1 本増やすのは割に合わないと判断しました。

### 4. 制御文字を潰し、最後の Enter は押さない

```ts
herdr('pane', 'send-text', live.pane_id, prompt.replace(/\p{Cc}+/gu, ' ').trim());
```

`send-text` は生バイトをそのまま端末に書き込みます。したがって改行 `\n` は「Enter を押した」ことと同義で、プロンプトが途中で確定されてしまいます。

ここは最初 `\r?\n` を潰していたのですが、それでは足りませんでした。**単独の `\r` が残ります。** CR を Enter として扱う入力先なら、これだけで送信されます。ESC も素通りして、対象アプリにはキー入力として届きます。C0 制御文字をまとめて（`\p{Cc}`）スペースに潰すのが正しい範囲でした。複数行を維持したいなら bracketed paste（`ESC[200~ … ESC[201~`）で包む必要があります。

ここで意図的にやっていないのが、**改行を送って確定すること**です。このツールがやるのは入力欄に文字列を置くところまでで、送信するかどうかは対象ペインを見た人間が決めます。

分類モデルは確率を返すのであって、正解を保証するわけではありません。宛先を間違えたまま自動で走り出すと、無関係なプロジェクトでエージェントが動き始めます。逆に、入力欄に置くだけなら、間違っていても Ctrl-U で消せば済みます。**自動化の範囲を「移動と入力」に限定し、「実行」のトリガーを人間に残す**ことで、精度が 100% でなくても実用的なツールになります。

### 5. workspace focus が効かないケースへの配慮

最後に、順序に意味がある箇所の話です。

```ts
herdr('workspace', 'focus', wid);
herdr('agent', 'focus', live.pane_id);
herdr('pane', 'send-text', live.pane_id, prompt.replace(/\p{Cc}+/gu, ' ').trim());
herdr('notification', 'show', `-> ${target.name}`, '--sound', 'none');
```

別ワークスペースのペインに送る場合、`agent focus` だけでは画面が移動しません。ワークスペース自体を切り替える必要があるので `workspace focus` を先に呼びます。

ただし、**`workspace focus` はそれ自体が再描画を要求しません**。後続の何かが画面を描き直したときに、初めてクライアント側に反映されます。`send-text` と通知の表示はどちらも再描画を伴うので、`focus` を先に置いておけば結果として画面が動く、という順序依存になります。コード中のコメントに書いてあるのはこのことです。

つまりこの 4 行は「フォーカス 2 つ → 入力 → 通知」という手順であると同時に、**再描画を起こす操作を後ろに置くための並び**でもあります。通知の表示は、どこに送られたかをトーストで知らせる UI 上の意味だけでなく、**再描画を確実に起こすトリガー**としての役割も兼ねています。音は不要なので `--sound none` を指定しています（`herdr notification show --help`（herdr 0.9.0）に `none` / `done` / `request` の 3 値があります）。

## ショートカットキーでポップアップさせる

手で `node route.mts ...` と打つのでは本末転倒なので、herdr のキーに割り当てています。`~/.config/herdr/scripts/route-prompt.sh` の全文です。

```sh
#!/bin/sh
# プロンプトを jev に判定させ、該当ワークスペースの agent ペインへ未送信で入力する。
set -e
cd "$HOME/work/<project>"
exec node --env-file=.env route.mts
```

引数なしで呼ぶので、必ず対話入力のパスに入ります。ポップアップに `prompt (empty to cancel)> ` が出て、そこに書いて Enter を押すと分類が走る、という流れです。空で Enter を押せば終了コード 2 で抜けます。

`--env-file=.env` は `TYPESAFE_API_KEY` を読み込むためです。`cd` しているのは `.env` の解決のため、`exec` は余計なシェルプロセスを残さないためです。

herdr 側の設定は、[以前の記事](https://zenn.dev/uehaj/articles/herdr-devurls-popup)で書いた URL 台帳のポップアップと同じ要領で、`[[keys.command]]` に `type = "popup"` で割り当てています。

## 肝心の精度は

内容による、ですね。分類モデルに渡しているのは前述の `label`、つまり `basename(cwd)` とステータス記号を除いたターミナルタイトルだけです。作業の実体がそこに現れていなければ当たりません。

運用としては、あてはまりそうなキーワードをプロンプトに入れておくことになるでしょう。ただしこれは「正確な名前を思い出せ」という話ではありません。むしろ逆で、こういう入力で通ります。

> えーとあの、なんだっけ、カーネマンのシステム1とかの、それに関係あるやつの、今やってることおしえて

ワークスペース番号もディレクトリ名も思い出さないまま、周辺の連想語だけで宛先が決まります。キーワード一致や正規表現ではこうはいきません。中高年にやさしいシステムになっています。

## おわりに

「宛先を選ぶ」という操作は、人間にとっては一瞬の判断でも、手を動かすコストが意外に高い部類の作業です。タブを探し、移動し、その間に何を書こうとしていたか思い出す。この往復がなくなるだけで、思いついたことを書き留めるハードルはかなり下がりました。

System One モデルは、こういう「判断そのものは軽いが、ルールとして書き下すのが面倒」な箇所にちょうど合います。生成モデルで同じことをやると、プロンプト・パース・リトライの層が要りますし、選択肢の集合から外れた答えが返る余地も残ります。選択肢を渡して 1 つ返してもらう、という形に落とせる問題なら、こちらのほうが素直です。

一方で、精度を前提にした設計にはしていません。確率で選んでいる以上は外れますし、外れたときに自動で走り出すと後始末のほうが高くつきます。だから最後の Enter だけは人間に残す。自動化の線をどこで引くかという話で、今回はここが落としどころでした。

さて、今後の展開です。プロジェクトが増えてきたとき、「次に何をやるか」を AI が決めることはおそらく必須で、選択の負荷はなくすに越したことはありません。音声認識で入力するようになると、このことはさらに重要になります。ディスプレイなしで作業できるようになったとき、プロジェクトをマウスやキーボードで選ぶことはもうありえず、文脈でルーティングしていくことになるでしょう。その際にも、分類モデルを使った今回のような方法論は有効なはずです。

また一歩、未来に近付いた!
