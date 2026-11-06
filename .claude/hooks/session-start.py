#!/usr/bin/env python3
"""SessionStart フック: セッション開始時に現在地（進捗）をコンテキストへ自動注入する。

exit 0 時、stdout への出力がそのまま Claude のコンテキストに追加される（動作規定「参照順序の厳守」の確実化）。
過去の作業ログ（docs/project/log/）は注入しない。経緯の確認はユーザーの依頼ベースで行う（動作規定「参照順序の厳守」）。
セッションログの記録は「ログを記録して」マクロによる手動起動のみで、フックは関与しない。

CLAUDE.md の地の文（「セッション開始時は /read-handover の実行を促す」）だけでは、長い会話の
途中でセッション開始時の指示が埋もれて実行されないことがあるため、/read-handover の提案を
このフックの出力自体にも含め、毎回のセッション開始時に確実に注入する。
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

# .claude/hooks/ の2階層上 = プロジェクトルート（フック実行時の cwd に依存しないため）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROGRESS_FILE = PROJECT_ROOT / "docs" / "project" / "progress.md"
PROGRESS_MAX_LINES = 80  # progress.md 肥大時のコンテキスト浪費を防ぐ上限
LOG_DIR = PROJECT_ROOT / "docs" / "project" / "log"


def configure_utf8() -> None:
    """Windows のロケール既定（cp932 等）による文字化けを防ぐ。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main() -> int:
    configure_utf8()
    print(f"今日: {datetime.datetime.now():%Y-%m-%d}")

    try:
        if PROGRESS_FILE.is_file():
            lines = PROGRESS_FILE.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            print("--- 現在の進捗 (docs/project/progress.md) ---")
            print("\n".join(lines[:PROGRESS_MAX_LINES]))
            if len(lines) > PROGRESS_MAX_LINES:
                print(f"(長いため先頭{PROGRESS_MAX_LINES}行のみ表示。progress.md は「現在の状態」だけに保つこと)")
        else:
            print("(docs/project/progress.md が未作成です。作業開始時に作成してください)")
    except OSError:
        pass  # 読み取り失敗時はコンテキスト注入なしで通常起動させる

    try:
        if any(f.name != "README.md" for f in LOG_DIR.glob("*.md")):
            print(
                "(過去の作業ログが docs/project/log/ にあります。詳しい経緯が必要な場合は"
                " /read-handover「ログを読んで」の実行を提案してください)"
            )
    except OSError:
        pass  # 読み取り失敗時はコンテキスト注入なしで通常起動させる

    return 0


if __name__ == "__main__":
    sys.exit(main())
