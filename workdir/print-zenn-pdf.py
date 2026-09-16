#!/usr/bin/env python3
"""zenn preview のページを、サイドバーを隠した状態で PDF 出力する。

ヘッドレス Chrome の --print-to-pdf は CSS を注入できないので、
リモートデバッグ経由 (CDP) で Page.printToPDF を呼ぶ。

使い方:
  python3 print-zenn-pdf.py <slug> <出力パス>
前提:
  - npx zenn preview が :8000 で稼働
  - Chrome が --remote-debugging-port=9333 --headless で起動済み
"""
import asyncio, base64, json, sys, urllib.request
import websockets

PORT = 9333
PREVIEW = "http://localhost:8000/articles/"

# zenn preview の左サイドバー(記事一覧)だけを印刷から外す。
# 記事本文中の aside.msg (:::message) や header は消さないよう、
# セレクタは layout 側のクラスに限定する。
HIDE_CSS = """
.layout__sidebar { display: none !important; }
.layout__main { width: 100% !important; max-width: 100% !important; margin: 0 !important; }
"""


async def main(slug: str, out: str) -> None:
    tabs = json.load(urllib.request.urlopen(f"http://localhost:{PORT}/json/list"))
    page = next(t for t in tabs if t["type"] == "page")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=200 * 1024 * 1024) as ws:
        i = 0

        async def cmd(method, **params):
            nonlocal i
            i += 1
            await ws.send(json.dumps({"id": i, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == i:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        await cmd("Page.enable")
        await cmd("Page.navigate", url=PREVIEW + slug)
        # SPA なので描画完了を時間で待つ (レンダリングは数秒で終わる)
        await asyncio.sleep(8)
        # mermaid 図は embed.zenn.studio の iframe で遅延読み込みされるため、
        # ページ全体を段階的にスクロールして読み込みを誘発してから待つ。
        # 待ち時間固定だと図が "Loading..." のまま印刷される (2026-09-16 に発生)。
        await cmd("Runtime.evaluate", expression=(
            "(async () => {"
            "  const h = document.body.scrollHeight;"
            "  for (let y = 0; y <= h; y += 600) {"
            "    window.scrollTo(0, y);"
            "    await new Promise(r => setTimeout(r, 300));"
            "  }"
            "  window.scrollTo(0, 0);"
            "})()"
        ), awaitPromise=True)
        await asyncio.sleep(12)
        await cmd("Runtime.evaluate", expression=(
            "const s=document.createElement('style');"
            f"s.textContent={json.dumps(HIDE_CSS)};"
            "document.head.appendChild(s);'ok'"
        ))
        await asyncio.sleep(1)
        res = await cmd(
            "Page.printToPDF",
            printBackground=True,
            preferCSSPageSize=False,
            marginTop=0.4, marginBottom=0.4, marginLeft=0.4, marginRight=0.4,
        )
        with open(out, "wb") as f:
            f.write(base64.b64decode(res["data"]))
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
