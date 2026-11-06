# Git 運用規約

## ブランチ戦略（GitHub Flow ベース）
- `main`: 常にリリース可能な状態を保つ。直接コミット・直接 push 禁止
- 作業ブランチは `main` から分岐し、Pull Request で `main` へマージする

| 種別 | 命名 | 例 |
|---|---|---|
| 機能追加 | `feature/<概要>` | `feature/user-login` |
| バグ修正 | `fix/<概要>` | `fix/order-total-rounding` |
| リファクタ・雑務 | `chore/<概要>` | `chore/update-ci` |

Issue 番号がある場合は `feature/123-user-login` のように含める。

## コミット規約（Conventional Commits）
形式: `<type>: <要約>` または `<type>(<scope>): <要約>`（scope は任意。日本語可・50文字以内）

| type | 用途 |
|---|---|
| feat | 機能追加 |
| fix | バグ修正 |
| refactor | 挙動を変えない整理 |
| test | テストの追加・修正 |
| docs | ドキュメントのみの変更 |
| chore | ビルド・設定・依存関係 |

- 1コミット = 1論理変更。ビルドとテストが通る単位でコミットする
- 破壊的変更は `feat!:` とし、本文に `BREAKING CHANGE:` を明記する
- コミット本文には「なぜ」を書く（必要な場合のみ）

## 禁止事項
- `main` への直接 push / force push（共有ブランチでは `--force-with-lease` も原則禁止。フックは全ブランチの force push を確認制にしている）
- `git reset --hard`・`git checkout .` 等の破壊的操作をユーザー確認なしに実行すること
- `--no-verify` によるフックのスキップ
- 秘密情報・生成物（node_modules、ビルド成果物）のコミット

## Pull Request
- 小さく保つ（目安: 差分400行以内。超える場合は分割を検討）
- 説明に「目的 / 変更内容 / 確認方法」を書く（雛形 `.github/PULL_REQUEST_TEMPLATE.md` が GitHub の PR 作成画面で自動適用される）
- PR 作成前の順序: /review によるコード・セキュリティレビュー（[must] 解消）→ 全テストで回帰確認 → 最終全体確認レビュー → PR 作成（コミット済みの差分は `/review main..HEAD` のように範囲を指定する）
- マージ条件: CI green + レビュー承認

## push 前の進捗更新
- 保護ブランチ以外への push は、フック `remind-progress-update.py` が push 対象コミットに `docs/project/progress.md` の更新が含まれているかを確認する。含まれていなければ強制的にブロックはせず、許可プロンプトで確認を促す。更新してから push し直すか、このまま push するかはユーザーが選択できる
- 進捗更新専用のコミット・PR を分けないこと。直前の作業コミットに含めるか、同一 push 内の別コミットとしてまとめる。PR 範囲全体が progress.md の更新だけになっている場合も同フックが確認を促す
- `progress.md` に PR 番号・マージ状態・ブランチ削除の有無を書かないこと。マージ前には正しく書けないため、書くとマージ後に追従コミットが必要になる（詳細は CLAUDE.md「振る舞いの制限」）
