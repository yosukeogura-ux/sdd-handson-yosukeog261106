#!/usr/bin/env python3
"""PostToolUse(Edit|Write) フック: 編集されたファイルを自動フォーマットし、lint エラーを Claude に返す。

exit 2 の stderr が Claude に渡り、その場で修正させる。
対応ツールがプロジェクトに存在しない場合は何もしない（スタック確定前でも安全に導入できる）。
スタック確定後、このファイルの分岐をプロジェクトに合わせて調整すること。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TIMEOUT_SEC = 60

ESLINT_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue"}
PRETTIER_ONLY_EXTENSIONS = {".css", ".scss"}
PY_EXTENSIONS = {".py"}


def configure_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


# cmd /c が制御構文・変数展開として誤解釈しうる文字（& ^ % < > | と、
# "Program Files (x86)" のような括弧、遅延展開の !、引用の崩れる "、行分割になる改行・タブ）
_CMD_UNSAFE_CHARS_RE = re.compile(r'[&^%<>|()!"\r\n\t]')


def run(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """コマンドを実行する。実行ファイル（.exe 等）は直接、.cmd/.bat シムのみ cmd /c を噛ませる。

    cmd /c はメタ文字入りパスを別コマンドに分解する危険があるため、経由は最小限にし、
    経由する場合は全引数を検査して該当すれば実行しない（check_js / check_py 共通のガード）。
    """
    exe = shutil.which(args[0])
    if exe and not exe.lower().endswith((".cmd", ".bat")):
        args = [exe, *args[1:]]
    elif os.name == "nt":
        if any(_CMD_UNSAFE_CHARS_RE.search(arg) for arg in args):
            return None  # cmd /c 経由で安全に渡せない引数はスキップ（安全側）
        args = ["cmd", "/c", *args]
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SEC,
            cwd=PROJECT_ROOT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def node_bin(name: str) -> str | None:
    """node_modules/.bin 配下のツールのパスを返す（Windows は .cmd シムを優先）。"""
    bin_dir = PROJECT_ROOT / "node_modules" / ".bin"
    candidates = [f"{name}.cmd", name] if os.name == "nt" else [name]
    for candidate in candidates:
        path = bin_dir / candidate
        if path.exists():
            return str(path)
    return None


def check_js(file_path: str, with_eslint: bool) -> str | None:
    prettier = node_bin("prettier")
    if prettier:
        run([prettier, "--write", file_path])
    if with_eslint:
        eslint = node_bin("eslint")
        if eslint:
            result = run([eslint, "--fix", file_path])
            if result is not None and result.returncode != 0:
                return f"ESLint エラー:\n{(result.stdout + result.stderr).strip()}"
    return None


def check_py(file_path: str) -> str | None:
    if shutil.which("ruff") is None:
        return None
    run(["ruff", "format", file_path])
    result = run(["ruff", "check", "--fix", file_path])
    if result is not None and result.returncode != 0:
        return f"Ruff エラー:\n{(result.stdout + result.stderr).strip()}"
    return None


def main() -> int:
    configure_utf8()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input")
    file_path = str(tool_input.get("file_path") or "") if isinstance(tool_input, dict) else ""
    if not file_path or not Path(file_path).is_file():
        return 0

    suffix = Path(file_path).suffix.lower()
    error: str | None = None
    if suffix in ESLINT_EXTENSIONS:
        error = check_js(file_path, with_eslint=True)
    elif suffix in PRETTIER_ONLY_EXTENSIONS:
        error = check_js(file_path, with_eslint=False)
    elif suffix in PY_EXTENSIONS:
        error = check_py(file_path)

    if error:
        print(f"{error}\n上記の lint エラーを修正してください。", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
