#!/usr/bin/env python3
"""PreToolUse(Bash|PowerShell) フック: 保護ブランチ(main/master)への直接コミット・プッシュをブロックする。

git commit / push / merge / rebase / cherry-pick / revert（-C・-c 等のグローバルオプション付きを
含む）を検知したら、対象リポジトリ（-C 指定があればそのパス、なければ実行 cwd）のブランチを調べ、
保護ブランチなら exit 2 で拒否する（stderr のメッセージが Claude に渡る）。refspec（HEAD:main 等）で
保護ブランチへ push する形は、現在のブランチによらず拒否する。git 管理外・detached HEAD・git 未導入
では何もしない（フック不具合や環境差で開発が止まるのを防ぐ）。
※ 事故防止のガード。git-workflow.md「main への直接コミット・push 禁止」を機械的に補助する。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# 直接コミット・プッシュを禁じるブランチ。プロジェクトの既定ブランチ名に合わせて調整する
PROTECTED_BRANCHES = frozenset({"main", "master"})

# コマンド先頭・改行区切り・連結演算子(; & | サブシェル( グループ化{)の直後のみにマッチさせるアンカー。
# git commit -m "push to main の説明" のような引用文字列内の語句への誤検知を防ぎつつ、
# 「git add -A\ngit commit」のような改行区切りの複数行コマンドや行頭空白付き、
# 「{ git push -u origin main; }」のようなブレースグループ化も検知する。
# 区切り直後の空白を [ \t]* に限定するのは、\s* だと文字クラス内の \n と二重に改行を消費でき、
# 改行が連続する入力で照合が O(N^2) になるため（コマンド直前の改行はクラス側で拾える）。
_CMD_HEAD = r"(?:^|[;&|({\n\r]|\$\()[ \t]*"
# git とサブコマンドの間に入るグローバルオプション。引数を取る短形式は -C / -c のみ対応し、
# 「--git-dir <path>」のような2トークン長形式は対象外とする（事故防止ガードの範囲）
_GIT_OPT = r"(?:-[cC]\s+(?:\"[^\"]*\"|'[^']*'|\S+)|--\S+)"
# 保護ブランチを直接変更・前進させるサブコマンド。commit / push に加え、保護ブランチ上での
# merge / rebase / cherry-pick / revert もコミットを直接積む操作のため対象とする
_OPERATIONS = {
    "commit": "コミット",
    "push": "プッシュ",
    "merge": "マージ",
    "rebase": "リベース",
    "cherry-pick": "チェリーピック",
    "revert": "リバート",
}
_GIT_CMD_RE = re.compile(
    # 末尾は (?![\w-]) で区切る: \b だと merge が merge-base / merge-tree（読み取り専用）に
    # 前方一致して誤ブロックするため
    _CMD_HEAD + r"git((?:\s+" + _GIT_OPT + r")*)\s+(" + "|".join(_OPERATIONS) + r")(?![\w-])"
    # --abort / --quit / --continue / --skip は進行中操作の中断・続行であり、保護ブランチを
    # 新たに変更する開始操作ではないため対象外とする。引用文字列内の語（コミットメッセージ等）で
    # 検知が外れないよう、サブコマンド直後のトークンに限って判定する
    r"(?!\s+--(?:abort|quit|continue|skip)\b)"
)
# -C の引数（ブランチ判定に使うリポジトリパス）。引用符付き・なしの両形式を拾う
_GIT_C_PATH_RE = re.compile(r"-C\s+(?:\"([^\"]*)\"|'([^']*)'|(\S+))")
# push コマンドの出現ごとに、同一コマンド区切り内（引数部分）だけを refspec 検査の対象にする。
# コマンド全体を検査すると、後続の別コマンドや引用文字列内の「:main」表記に誤発火するため
_PUSH_SEGMENT_RE = re.compile(
    _CMD_HEAD + r"git(?:\s+" + _GIT_OPT + r")*\s+push(?![\w-])([^|;&\n\r]*)"
)
_PROTECTED_ALT = "|".join(sorted(PROTECTED_BRANCHES))
# refspec（<src>:<dst>）の dst が保護ブランチを指す形（HEAD:main / feature:main /
# :main による削除 / HEAD:refs/heads/main）。src 側に : を許さないことで SCP 形式 URL
# （host:repo）への誤検知を避け、末尾の (?![\w/.-]) で main-fix / main.git 等を除外する。
# dst 省略形（git push origin main）はローカル保護ブランチを進める操作（commit / merge 系）を
# 本フックが塞いでいるため対象外とする
_REFSPEC_TO_PROTECTED_RE = re.compile(
    r"\s[\"']?[^\s:\"']*:(?:refs/heads/)?(" + _PROTECTED_ALT + r")(?![\w/.-])"
)
# --delete / -d による保護ブランチ削除（refspec の :main 削除形と等価な別表記）
_PUSH_DELETE_RE = re.compile(
    r"\s(?:--delete|-(?!-)[a-zA-Z]*d)\b[^|;&\n\r]*\s(?:refs/heads/)?("
    + _PROTECTED_ALT + r")(?![\w/.-])"
)


def configure_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def detect_operation(command: str) -> tuple[str, list[str]] | None:
    """保護対象の git 操作なら（サブコマンド名, -C で指定されたパス群）を、無関係なら None を返す。"""
    match = _GIT_CMD_RE.search(command)
    if match is None:
        return None
    c_paths = ["".join(groups) for groups in _GIT_C_PATH_RE.findall(match.group(1))]
    return match.group(2), c_paths


def current_branch(cwd: str) -> str | None:
    """cwd の git リポジトリの現在ブランチ名を返す。取得できなければ None を返す。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            cwd=cwd,
        )
    except (subprocess.SubprocessError, OSError):
        return None  # git 未導入・実行不能
    if result.returncode != 0:
        return None  # git リポジトリでない
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        return None  # detached HEAD はブランチ上でない
    return branch


def main() -> int:
    configure_utf8()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # 入力形式が想定外の場合はブロックしない
        return 0
    if not isinstance(payload, dict):
        return 0

    tool_input = payload.get("tool_input")
    command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
    if not command:
        return 0

    # refspec（<src>:<dst>）や --delete で保護ブランチを更新・削除する push は、現在の
    # ブランチによらずブロックする。複合コマンド（git commit && git push origin HEAD:main）でも
    # 検査が漏れないよう、detect_operation の結果とは独立に push の出現ごとに判定する
    for push_segment in _PUSH_SEGMENT_RE.finditer(command):
        args = push_segment.group(1)
        target_match = _REFSPEC_TO_PROTECTED_RE.search(args) or _PUSH_DELETE_RE.search(args)
        if target_match is not None:
            target = target_match.group(1)
            print(
                f"保護ブランチへの push をブロックしました（push 先: {target}）。\n"
                f"git-workflow.md の規約により、{target} への反映は Pull Request で行ってください。\n"
                f"意図的に {target} へ push する必要がある場合は、"
                "理由を説明してユーザーに実行可否を確認してください。",
                file=sys.stderr,
            )
            return 2

    detected = detect_operation(command)
    if detected is None:
        return 0
    subcommand, c_paths = detected
    operation = _OPERATIONS[subcommand]

    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    # -C はブロック判定の対象リポジトリを変える。git と同様に指定順へ連結する
    # （相対パスは直前の基点から解決し、絶対パスは基点を置き換える）
    for path in c_paths:
        cwd = os.path.join(cwd, path)

    branch = current_branch(cwd)
    if branch is None or branch not in PROTECTED_BRANCHES:
        return 0

    print(
        f"保護ブランチへの直接{operation}をブロックしました（現在のブランチ: {branch}）。\n"
        "git-workflow.md の規約により、作業は feature/ ・ fix/ ・ chore/ ブランチで行ってください。\n"
        f"対処: `git switch -c feature/<概要>` で作業ブランチを作成してから再実行してください。\n"
        f"意図的に {branch} で作業する必要がある場合は、理由を説明してユーザーに実行可否を確認してください。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
