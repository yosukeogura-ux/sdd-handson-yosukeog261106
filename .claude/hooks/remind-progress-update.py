#!/usr/bin/env python3
"""PreToolUse(Bash|PowerShell) フック: git push 前に docs/project/progress.md の扱いを確認する。

次の2点をそれぞれ検査し、該当すれば hookSpecificOutput.permissionDecision="ask" を stdout に返して
確認を促す（reason のメッセージがユーザーへの許可プロンプトに表示される）。いずれも強制的には
ブロックせず、push し直すか・このまま push するかはユーザーが選択する。

1. 更新漏れ: push しようとしているコミット群（アップストリーム、無ければ main/master との merge-base
   から HEAD までの範囲）に progress.md への変更が含まれていない場合。push 時点の作業内容を都度
   反映させるための検査（CLAUDE.md セクション5「セーブして」マクロを機械的に補助する）。
2. 進捗更新のみの PR: PR 範囲（main/master との merge-base から HEAD まで）の変更が progress.md
   だけの場合。「進捗更新専用のコミット・PR を分けない」規約（git-workflow.md）を補助する検査で、
   1 とは判定範囲が異なる（1 は push 単位、2 は PR 単位）。progress.md を既存 PR へ追加する
   push は PR 範囲に作業差分が含まれるため 2 には該当しない。

比較起点が判定できない場合（最初のコミットのみ・main/master 不在・detached HEAD・git 未導入等）や
push する新規コミットがない場合は何もしない（フック不具合や環境差で開発が止まるのを防ぐ）。
保護ブランチ（main/master）への push は guard-protected-branch.py が別途ブロックするため対象外とする。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

PROTECTED_BRANCHES = frozenset({"main", "master"})
PROGRESS_FILE = "docs/project/progress.md"

# guard-protected-branch.py と同じアンカー・オプション表記に合わせる（複合コマンド・改行区切り・
# グローバルオプション付きの git push も検知するため）
_CMD_HEAD = r"(?:^|[;&|({\n\r]|\$\()[ \t]*"
_GIT_OPT = r"(?:-[cC]\s+(?:\"[^\"]*\"|'[^']*'|\S+)|--\S+)"
_GIT_C_PATH_RE = re.compile(r"-C\s+(?:\"([^\"]*)\"|'([^']*)'|(\S+))")
# group(1): git とサブコマンドの間のグローバルオプション（-C 抽出用）
_PUSH_RE = re.compile(_CMD_HEAD + r"git((?:\s+" + _GIT_OPT + r")*)\s+push(?![\w-])")


def configure_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            cwd=cwd,
        )
    except (subprocess.SubprocessError, OSError):
        return None


def current_branch(cwd: str) -> str | None:
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if result is None or result.returncode != 0:
        return None
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        return None  # detached HEAD
    return branch


def resolve_trunk_merge_base(cwd: str) -> str | None:
    """main/master との merge-base（PR 範囲の起点）を返す。"""
    for candidate in ("main", "master", "origin/main", "origin/master"):
        verify = run_git(["rev-parse", "--verify", "--quiet", candidate], cwd)
        if verify is None or verify.returncode != 0:
            continue
        merge_base = run_git(["merge-base", "HEAD", candidate], cwd)
        if merge_base is not None and merge_base.returncode == 0 and merge_base.stdout.strip():
            return merge_base.stdout.strip()
    return None


def resolve_base_ref(cwd: str) -> str | None:
    """push 差分の比較起点を返す（アップストリーム優先、無ければ main/master との merge-base）。"""
    upstream = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd)
    if upstream is not None and upstream.returncode == 0 and upstream.stdout.strip():
        return upstream.stdout.strip()
    return resolve_trunk_merge_base(cwd)


def commit_count(cwd: str, base_ref: str) -> int | None:
    result = run_git(["rev-list", "--count", f"{base_ref}..HEAD"], cwd)
    if result is None or result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def progress_touched(cwd: str, base_ref: str) -> bool | None:
    diff = run_git(["diff", "--name-only", f"{base_ref}..HEAD", "--", PROGRESS_FILE], cwd)
    if diff is None or diff.returncode != 0:
        return None
    return bool(diff.stdout.strip())


def changed_files(cwd: str, base_ref: str) -> list[str] | None:
    diff = run_git(["diff", "--name-only", f"{base_ref}..HEAD"], cwd)
    if diff is None or diff.returncode != 0:
        return None
    return [line.strip() for line in diff.stdout.splitlines() if line.strip()]


def emit_ask(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": reason,
                }
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    configure_utf8()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0

    tool_input = payload.get("tool_input")
    command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
    if not command:
        return 0

    match = _PUSH_RE.search(command)
    if match is None:
        return 0

    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    c_paths = ["".join(groups) for groups in _GIT_C_PATH_RE.findall(match.group(1))]
    for path in c_paths:
        cwd = os.path.join(cwd, path)

    branch = current_branch(cwd)
    if branch is None or branch in PROTECTED_BRANCHES:
        return 0  # 保護ブランチは guard-protected-branch.py が別途処理する

    base_ref = resolve_base_ref(cwd)
    if base_ref is None:
        return 0  # 比較起点が判定できない場合は塞がない

    pending = commit_count(cwd, base_ref)
    if pending is None or pending <= 0:
        return 0  # push する新規コミットがない、または判定不能

    touched = progress_touched(cwd, base_ref)
    if touched is None:
        return 0  # 判定不能なら塞がない
    if touched is False:
        emit_ask(
            f"push 対象のコミットに {PROGRESS_FILE} の更新が含まれていません。\n"
            "CLAUDE.md の規約では、現在の状態を反映させた上でこの push に含めることを推奨しています。\n"
            f"更新する場合: {PROGRESS_FILE} を更新 → git add → git commit してから push し直してください。\n"
            "（このまま push するかどうかはユーザーが選択できます。"
            "「セーブして」/save はセッション途中の任意の手動更新用です）"
        )
        return 0

    # progress.md は含まれている。PR 範囲全体が progress.md だけなら進捗更新専用の PR として確認を促す
    pr_base = resolve_trunk_merge_base(cwd)
    if pr_base is None:
        return 0  # PR 範囲の起点が判定できない場合は塞がない
    files = changed_files(cwd, pr_base)
    if not files:
        return 0  # 差分なし、または判定不能
    if set(files) != {PROGRESS_FILE}:
        return 0  # 作業差分を伴うため規約に沿っている

    emit_ask(
        f"この PR の変更が {PROGRESS_FILE} だけです（進捗更新専用の PR）。\n"
        "git-workflow.md の規約では、進捗更新だけのコミット・PR を分けず、"
        "次の作業コミットに同梱することを推奨しています。\n"
        f"マージ後に追従更新が必要になっている場合は、{PROGRESS_FILE} に PR 番号・マージ状態を"
        "書いていないか確認してください（これらは書かない規約です）。\n"
        "（このまま push するかどうかはユーザーが選択できます）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
