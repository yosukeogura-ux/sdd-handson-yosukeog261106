---
name: release-process
description: リリース作業のスキル。バージョンアップ、CHANGELOG 更新、タグ付け、リリース準備・実施時に使用する。
# /release コマンドを入口とするため、スラッシュメニューには載せない（Claude は Skill ツールで参照する）
user-invocable: false
---

# リリース・変更履歴作成手順

## バージョン判断（SemVer）
| 変更内容 | バージョン |
|---|---|
| 破壊的変更（API 互換性が壊れる） | major（X.0.0） |
| 後方互換の機能追加 | minor（x.Y.0） |
| 後方互換のバグ修正のみ | patch（x.y.Z） |

## CHANGELOG（Keep a Changelog 形式）
- 開発中は `## [Unreleased]` セクションに都度追記する（リリース時の一括作成はしない）
- リリース時に `## [X.Y.Z] - YYYY-MM-DD` へ繰り下げる
- 分類: Added / Changed / Deprecated / Removed / Fixed / Security
- **利用者視点**で書く（内部リファクタの羅列にしない）

## リリース手順チェックリスト
1. [ ] main を最新化し、作業ツリーがクリーンであることを確認する
2. [ ] 全テスト・lint・型チェックが green（実行して確認し、結果を `docs/test/` に記録する。未実行のまま進めない）
3. [ ] 認証・認可・入力処理・依存関係の変更を含む場合は security-auditor で事前監査する
4. [ ] 前回タグからの差分を確認する: `git log <前回タグ>..HEAD --oneline`
5. [ ] リリースブランチを作成する: `chore/release-vX.Y.Z`（main へ直接コミットしない: git-workflow）
6. [ ] CHANGELOG.md を更新する（Unreleased → 新バージョンへ）
7. [ ] バージョンを更新する（package.json / pyproject.toml 等）
8. [ ] リリースコミット `chore(release): vX.Y.Z` を作成し、PR 経由で main へマージする
9. [ ] マージ後の main に注釈付きタグ: `git tag -a vX.Y.Z -m "vX.Y.Z"`
10. [ ] **タグの push とデプロイは実行前にユーザーへ最終確認する**
11. [ ] デプロイ後の動作確認（ヘルスチェック・主要導線）
12. [ ] progress.md にリリース完了の状態を反映する（リリースの時系列記録は CHANGELOG.md と git タグが担う）

途中のチェックが1つでも失敗したらリリースを中断し、状況を報告する。

## ロールバック方針
- リリース後に重大な問題が発生した場合: 前バージョンへの切り戻し（デプロイの巻き戻し / revert コミット）を優先し、原因調査は切り戻し後に行う
- DB マイグレーションを含むリリースは、down（ロールバック）が用意されていることをリリース前に確認する（db-design スキル）

## アンチパターン
- テスト未実行のままのリリース
- CHANGELOG の後追い一括作成
- タグとバージョンファイルの不一致
- 金曜夕方・退勤直前の本番リリース（対応者不在の時間帯を避ける）
