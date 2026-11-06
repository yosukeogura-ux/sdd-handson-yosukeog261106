---
description: 現在の差分をファイル種別に応じた観点でレビューする（コードを含む場合は code-reviewer エージェントを起動）
argument-hint: [レビュー対象（省略時: 未コミットの変更全体）]
---

現在の変更をレビューしてください。

対象: $ARGUMENTS（指定がない場合は `git diff HEAD` の全差分と未追跡ファイル。コミット済みブランチのレビューは `/review main..HEAD` のように範囲を指定する）

## 手順
1. 対象差分のファイル一覧を取得し（`git diff --name-only` + 未追跡ファイル）、code-review スキルの「差分種別と適用観点」で分類する
2. コード等、.md 以外のファイル（ソース・テスト・スクリプト・フック・設定・データ等）を含む場合: code-reviewer サブエージェントを起動し、対象差分のレビューを依頼する
3. 手順2で code-reviewer を起動する場合は、security-auditor サブエージェントも常に併せて起動する（コードレビューとセキュリティレビューをセットで実施する）
4. ドキュメント（.md）のみの場合: サブエージェントは起動せず、code-review スキルの「ドキュメント差分の観点」に沿って直接確認する（仕様・設計ドキュメント `docs/product/`・`docs/requirements/`・`docs/features/`・`docs/changes/`・`docs/design/`・`docs/adr/` や動作規定 `CLAUDE.md`・`.claude/` 配下の .md を含む場合は「仕様・設計差分の観点」も適用する。区分の正: code-review スキル「差分種別と適用観点」）
5. 結果を severity 順（[must] → [should] → [nits] → [ask]）に整理して報告する（security-auditor の報告は Critical・High = [must] / Medium = [should] / Low・Info = [nits] に読み替える）
6. [must] がある場合: 修正方針を提案し、ユーザーの承認を得てから修正する
7. [must] がない場合: 「マージ可」と報告する
