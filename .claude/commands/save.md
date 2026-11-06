---
description: 進捗をセーブする（progress.md 上書き）
---

現在のセッションの作業内容を記録してください。

1. `docs/project/progress.md` を上書き更新する（見出しは progress.md の既存構成に合わせる）
   - 現在のフェーズ
   - 直近で完了したこと
   - 次にやること
   - ブロッカー・未確定事項
2. 更新内容の要約を報告してください。

`docs/project/log/`（セッション要約ログ）への追記は「ログを記録して」マクロで行うため、このコマンドの対象外です（このコマンドで更新するのは progress.md のみ）。

push 前の必須更新は `.claude/hooks/remind-progress-update.py` が自動で確認するため、このコマンドはセッション途中で任意に更新したい場合の補助用です。
