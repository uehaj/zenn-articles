# zenn-articles

[Zenn](https://zenn.dev/uehaj) に投稿する記事のソースリポジトリ。Zenn Connect で連携して、`articles/*.md` を Zenn 上の記事として管理する。

## 構成

```
.
├── articles/    # Zenn 記事 (1ファイル = 1記事)
├── images/      # 記事中で使う画像
└── package.json # zenn-cli (npx zenn preview)
```

## ローカルプレビュー

```bash
npm install
npx zenn preview
# → http://localhost:8000/
```

## 新規記事の作成

```bash
npx zenn new:article --slug my-new-article
```

## 公開フロー

1. `articles/xxx.md` の frontmatter `published: false` で下書きを作成
2. `git push` → Zenn 側で下書きとして取り込まれる
3. プレビューで確認
4. `published: true` にして再 push で公開

## 既存記事

- [人間がMarkdownを書いたり修正しない時代に、Claude Code hookでドキュメントを自動でファンシーHTML化する](articles/claude-code-fancy-html-hook.md)
  - 関連リポジトリ: <https://github.com/uehaj/claude-code-fancy-html-hook>
