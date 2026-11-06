#!/usr/bin/env python3
"""PreToolUse(Bash|PowerShell) フック: 破壊的・危険コマンドをブロックする。

exit 2 でコマンド実行を拒否し、stderr のメッセージが Claude に渡る。
※ 完全な防御ではなく事故防止のガード。.env は settings.json の permissions.deny と併用する。
"""
from __future__ import annotations

import json
import re
import sys

# コマンド先頭・改行区切り・連結演算子(; & | サブシェル( グループ化{)の直後のみにマッチさせるアンカー
# （guard-protected-branch.py の _CMD_HEAD と同形に保つ）。
# git commit -m "rm -rf の説明" のような引用文字列内の語句への誤検知を防ぎつつ、
# 「cd x\nrm -rf y」のような改行区切りの複数行コマンドや行頭空白付き、
# 「{ rm -rf x; }」のようなブレースグループ化も検知する。
# 区切り直後の空白を [ \t]* に限定するのは、\s* だと文字クラス内の \n と二重に改行を消費でき、
# 改行が連続する入力で照合が O(N^2) になるため（コマンド直前の改行はクラス側で拾える）。
CMD_HEAD = r"(?:^|[;&|({\n\r]|\$\()[ \t]*(?:sudo\s+)?"

# git とサブコマンドの間に入るグローバルオプション（-C <path> / -c <k=v> / --no-pager 等。
# guard-protected-branch.py の _GIT_OPT と同形に保つ）。force push は feature ブランチでも
# 本フックが唯一のガードのため、-C 付きの形もすり抜けないようにする
_GIT_OPT = r"(?:\s+(?:-[cC]\s+(?:\"[^\"]*\"|'[^']*'|\S+)|--\S+))*"

# (正規表現, 説明) のリスト。プロジェクト事情に応じて追加・削除する
DANGEROUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (CMD_HEAD + r"rm\s+(-\S+\s+)*-\S*[rR]", "rm による再帰削除"),
    (CMD_HEAD + r"rm\b[^|;&]*--recursive", "rm による再帰削除"),
    (CMD_HEAD + r"find\b[^|;&]*\s-delete\b", "find -delete（一括削除）"),
    # 短形式は結合フラグ（-uf / -4f 等）も検知する。-(?!-) で --follow-tags 等の長形式を除外
    (
        CMD_HEAD + r"git" + _GIT_OPT + r"\s+push\b[^|;&]*\s(?:--force\b|-(?!-)[a-zA-Z0-9]*f)",
        "force push（--force-with-lease・結合フラグ含む）",
    ),
    (CMD_HEAD + r"git" + _GIT_OPT + r"\s+push\b[^|;&]*\s[\"']?\+\S", "force push（+refspec による強制）"),
    (CMD_HEAD + r"git\s+reset\s+(-\S+\s+)*--hard", "git reset --hard（作業内容の破棄）"),
    (CMD_HEAD + r"git\s+clean\s+(-\S+\s+)*-\S*f", "git clean -f（未追跡ファイルの削除）"),
    (CMD_HEAD + r"git\s+checkout\s+(--\s+)?\.{1,2}/?(\s|$)", "git checkout .（変更の一括破棄）"),
    (CMD_HEAD + r"git\s+checkout\s+--\s", "git checkout -- <path>（変更の破棄）"),
    (CMD_HEAD + r"git\s+checkout\s+\S+\s+--\s", "git checkout <ref> -- <path>（変更の破棄）"),
    (CMD_HEAD + r"git\s+restore\b(?!\s+--staged\b)", "git restore（変更の破棄）"),
    (CMD_HEAD + r"git\s+restore\b.*--worktree", "git restore --worktree（変更の破棄）"),
    (CMD_HEAD + r"chmod\s+(-R\s+)?777\b", "chmod 777（過剰なパーミッション付与）"),
    (r"(curl|wget)[^|;&]*\|\s*(ba|z)?sh\b", "ダウンロードしたスクリプトの直接実行"),
    (CMD_HEAD + r"dd\b.*\bof=/dev/", "dd によるデバイスへの直接書き込み"),
    (CMD_HEAD + r"mkfs\b", "ファイルシステムの作成"),
    (r"(?i)" + CMD_HEAD + r"(rmdir|rd)\s+/s\b", "rmdir /s（再帰削除）"),
    (r"(?i)" + CMD_HEAD + r"del\s+/[fsq]", "del の強制・再帰削除"),
    (r"(?i)" + CMD_HEAD + r"remove-item\b.*\s-(recurse|force)\b", "Remove-Item の再帰・強制削除"),
    (
        r"(?i)\b(psql|mysql|sqlite3|sqlcmd|mongosh?)\b[^|;&]*\bdrop\s+(table|database|schema)\b",
        "DB クライアント経由の DROP 文",
    ),
)

# .env の読み書き（.env.example / .sample / .template は許可）。
# パターンが高コストなため、main 側で「.env を含むコマンドのみ」検査する
ENV_FILE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"(?i)" + CMD_HEAD
        + r"(cat|type|more|less|head|tail|grep|findstr|sed|awk|strings|get-content|gc)\b"
        + r"[^|;&]*\s\S*\.env\b(?!\.(example|sample|template))",
        ".env ファイルの読み取り（秘密情報保護）",
    ),
    (
        # リダイレクト先が .env（"<code>.env" のような引用内テキストを拾わないよう直前を限定）
        r"(?:^|\s|\d)(>>?)\s*(\S*[/\\])?\.env\b(?!\.(example|sample|template))",
        ".env ファイルへの書き込み（秘密情報保護）",
    ),
    (
        r"(?i)" + CMD_HEAD
        + r"(out-file|set-content|add-content|tee)\b[^|;&]*\s\S*\.env\b(?!\.(example|sample|template))",
        ".env ファイルへの書き込み（秘密情報保護）",
    ),
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
    if not command:
        return 0

    patterns = DANGEROUS_PATTERNS
    if ".env" in command.lower():
        patterns = patterns + ENV_FILE_PATTERNS
    for pattern, reason in patterns:
        if re.search(pattern, command):
            print(
                f"危険なコマンドをブロックしました: {reason}\n"
                f"対象: {command[:200]}\n"
                "本当に必要な場合は、目的とリスクを説明してユーザーに実行可否を確認してください。",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
