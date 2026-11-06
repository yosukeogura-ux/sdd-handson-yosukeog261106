---
description: リリース手順（テスト確認 → CHANGELOG → バージョン更新 → タグ）を実行する
argument-hint: <バージョン（例: 1.2.0）または major|minor|patch>
---

バージョン「$ARGUMENTS」のリリース作業を行ってください。
`.claude/skills/release-process/SKILL.md` のチェックリストに従って進めること。

## 手順
1. 事前確認: 作業ツリーがクリーンか、全テスト・lint・型チェックが green か（実行して確認する）
2. $ARGUMENTS が major / minor / patch の場合: 前回タグからの差分（`git log <前回タグ>..HEAD --oneline`）を確認し、SemVer 基準で新バージョン番号を決めてユーザーに確認する
3. リリースブランチ `chore/release-vX.Y.Z` を作成する（main へ直接コミットしない）
4. CHANGELOG.md を更新する（Unreleased → 新バージョンへ。差分をもとに利用者視点で記載）
5. バージョンファイル（package.json / pyproject.toml 等）を更新する
6. リリースコミット（`chore(release): vX.Y.Z`）を作成して PR を出し、マージ後の main に注釈付きタグを付ける
7. **push・デプロイは実行前に必ずユーザーの承認を得る**
8. 完了後、progress.md にリリース完了の状態を反映する

チェックが1つでも失敗した場合はリリースを中断し、失敗内容を報告すること。
