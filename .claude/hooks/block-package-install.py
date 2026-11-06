#!/usr/bin/env python3
"""PreToolUse(Bash|PowerShell) フック: 外部ライブラリの無断追加をブロックする（動作規定「振る舞いの制限」）。

exit 2 でコマンド実行を拒否し、stderr のメッセージが Claude に渡る
（→ Claude は理由と代替案を提示してユーザーに許可を求める行動に誘導される）。
"""
from __future__ import annotations

import json
import re
import sys

# コマンド先頭・改行区切り・連結演算子(; & | サブシェル( グループ化{)の直後のみにマッチさせるアンカー
# （guard-protected-branch.py の _CMD_HEAD と同形に保つ。引用文字列内の語句への誤検知を防ぎつつ、
# 改行区切りの複数行コマンドや行頭空白付きも検知する。区切り直後の空白を [ \t]* に限定するのは、
# \s* だと文字クラス内の \n と二重に改行を消費でき、改行が連続する入力で照合が O(N^2) になるため）
CMD_HEAD = r"(?:^|[;&|({\n\r]|\$\()[ \t]*(?:sudo\s+)?"

# 依存関係を「追加」するコマンドのみ対象。
# lockfile からの復元（npm ci / 引数なし・フラグのみの npm install / pip install -r /
# pip install -e . / uv sync / poetry install 等）は日常操作のため許可する。
# -U/--upgrade も既存依存の更新用として許可する（未導入パッケージの新規追加にも使えるが、
# 更新操作を妨げないことを優先する設計判断。pip / uv pip で除外条件は同期を保つ）。
INSTALL_PATTERNS: tuple[str, ...] = (
    CMD_HEAD + r"(npm|pnpm|yarn|bun)\s+(global\s+)?(install|i|add)\s+(-\S+\s+)*[^-\s]",
    # Windows の py ランチャー（py -m pip / py -3.11-64 -m pip）と、バージョンサフィックス・
    # .exe 付きの python（python3.11 / python.exe）経由も捕捉する
    CMD_HEAD
    + r"(?:(?:python3?(?:\.\d+)?(?:\.exe)?|py)(?:\s+-3(?:\.\d+)?(?:-\d+)?)?\s+-m\s+)?pip3?\s+install\s+"
    + r"(?!(?:(?:-r|--requirement)[= ]|(?:-e\s+)?\.(?:\[|\s|$)|(?:-U|--upgrade)\s))\S",
    CMD_HEAD + r"pipx\s+install\s",
    CMD_HEAD + r"poetry\s+add\s",
    CMD_HEAD + r"uv\s+add\s",
    CMD_HEAD + r"uv\s+tool\s+install\s",
    # 除外条件（-r / -e . / . / -U）は上の pip install パターンと同期を保つ
    CMD_HEAD
    + r"uv\s+pip\s+install\s+"
    + r"(?!(?:(?:-r|--requirement)[= ]|(?:-e\s+)?\.(?:\[|\s|$)|(?:-U|--upgrade)\s))\S",
    CMD_HEAD + r"cargo\s+(add|install)\s",
    CMD_HEAD + r"go\s+get\s",
    CMD_HEAD + r"composer\s+require\s",
    CMD_HEAD + r"gem\s+install\s",
    CMD_HEAD + r"(apt|apt-get|apk|brew|choco|winget)\s+(install|add)\s",
    # npx / uvx / pipx run 等の一時実行は対象外とする設計判断: マニフェスト・lockfile を変更する
    # 「依存の追加」ではなく、日常操作との機械的な区別も困難なため（恒久導入は各 install 側で捕捉する）
)

BLOCK_MESSAGE = (
    "外部ライブラリ・パッケージの追加は動作規定「振る舞いの制限」によりユーザー許可が必要です。"
    "追加したい理由・選定根拠・代替案を提示して、ユーザーに許可を求めてください。"
)


def configure_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main() -> int:
    configure_utf8()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # 入力形式が想定外の場合はブロックしない（フック不具合で開発が止まるのを防ぐ）
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input")
    command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""

    if command and any(re.search(pattern, command) for pattern in INSTALL_PATTERNS):
        print(BLOCK_MESSAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
