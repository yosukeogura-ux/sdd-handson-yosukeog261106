#!/usr/bin/env python3
"""Stop フック: 作業終了前に「テスト漏れ」「テスト記録漏れ」「データモデル文書の更新漏れ」を git diff ベースで検査する（動作規定「振る舞いの制限」）。

exit 2 で停止をブロックし、stderr の内容に従って Claude が対応を続行する。
stop_hook_active が true の場合は再ブロックしない（無限ループ防止）。
同一セッション・同一内容の警告は1回のみ（ユーザーの WIP が残っている間、コードに触れない
ターンまで毎回ブロックされるのを防ぐ）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 警告済み内容の記録先（.gitignore 登録済み）
MARKER_FILE = PROJECT_ROOT / ".claude" / ".consistency-warned"

# ソースコードとみなすパス（プロジェクト構成に合わせて調整する）。
# モノレポの packages/*/src/ のようなネスト配置も拾うため、TEST_RE と同様に任意階層を許容する
SOURCE_RE = re.compile(r"(^|/)(src|app|lib)/")
# テストとみなすパス
TEST_RE = re.compile(
    r"(^|/)(tests?|specs?|__tests__)(/|$)"
    r"|\.(test|spec)\.[^/]+$"
    r"|_test\.[^/]+$"
    r"|(^|/)test_[^/]+$"
)
# データモデル関連とみなすパス（名前の先頭に限定し、UserModel.tsx 等への誤検知を防ぐ）
DATA_MODEL_RE = re.compile(r"(^|/)(migrations?|schemas?|models?)(/|\.)", re.IGNORECASE)
# データモデル定義ドキュメント（1テーブル1ファイル＋overview.md。サブフォルダ整理も定義として扱う。
# 直下の README.md は書式定義であり定義ではないため除外）
DATA_DOC_RE = re.compile(r"^docs/design/data/(?!README\.md$).+\.md$")
# テスト記録ドキュメント（サブフォルダ整理も記録として扱う。直下の README.md は書式定義であり記録ではないため除外）
TEST_DOC_RE = re.compile(r"^docs/test/(?!README\.md$).+\.md$")


def git_lines(*args: str) -> list[str] | None:
    try:
        result = subprocess.run(
            # core.quotepath=false: 日本語等の非 ASCII ファイル名が8進エスケープされ、
            # パターン照合を黙ってすり抜けるのを防ぐ
            ["git", "-c", "core.quotepath=false", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=PROJECT_ROOT,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def collect_changed_files() -> set[str]:
    changed = git_lines("diff", "--name-only", "HEAD")
    if changed is None:
        # HEAD が無い（初回コミット前）場合はステージ済み + 作業ツリーの差分で代替
        changed = git_lines("diff", "--name-only") or []
        changed += git_lines("diff", "--name-only", "--cached") or []
    untracked = git_lines("ls-files", "--others", "--exclude-standard") or []
    return set(changed) | set(untracked)


def build_warnings(files: set[str]) -> list[str]:
    warnings: list[str] = []
    # docs/ 配下は記録ドキュメント、.claude/ 配下はフック等の開発環境、.devcontainer/ 配下は
    # コンテナ環境設定であり、いずれもプロダクトのソース・テストコードではない
    # （ソースとテストで判定を対称に保つ）
    EXCLUDED_PREFIXES = ("docs/", ".claude/", ".devcontainer/")
    has_source = any(SOURCE_RE.search(f) and not f.startswith(EXCLUDED_PREFIXES) for f in files)
    has_test = any(TEST_RE.search(f) and not f.startswith(EXCLUDED_PREFIXES) for f in files)
    if has_source and not has_test:
        warnings.append(
            "ソースコードが変更されていますが、テストの追加・更新がありません（動作規定「振る舞いの制限」）。"
            "テストを書くか、不要と判断した理由をユーザーへ報告してください。"
        )
    has_test_doc = any(TEST_DOC_RE.search(f) for f in files)
    if has_test and not has_test_doc:
        warnings.append(
            "テストコードの変更がありますが docs/test/ のテスト記録が未更新です（テスト記録規約）。"
            "テストケース一覧を docs/test/<機能名>.md に、実行結果（○/×）を"
            " docs/test/<機能名>-履歴.md に記録してください。"
        )
    has_data_model = any(DATA_MODEL_RE.search(f) for f in files)
    has_data_doc = any(DATA_DOC_RE.search(f) for f in files)
    if has_data_model and not has_data_doc:
        warnings.append(
            "データモデルの変更がありますが docs/design/data/ のテーブル定義が未更新です（動作規定「振る舞いの制限」）。"
            "該当テーブルの docs/design/data/<テーブル名>.md（全体像に影響する場合は overview.md も）を同時更新してください。"
        )
    return warnings


def already_warned(session_id: str, warnings: list[str]) -> bool:
    """同一セッション・同一警告内容なら True（2回目以降はブロックしない）。"""
    key = session_id + "\n" + "\n".join(warnings)
    try:
        if MARKER_FILE.is_file() and MARKER_FILE.read_text(encoding="utf-8") == key:
            return True
        MARKER_FILE.write_text(key, encoding="utf-8")
    except OSError:
        pass  # マーカーが扱えない環境では通常どおり毎回警告する
    return False


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0

    # 無限ループ防止: このフックによるブロックから続行中の場合は再ブロックしない
    if payload.get("stop_hook_active"):
        return 0

    if git_lines("rev-parse", "--is-inside-work-tree") is None:
        return 0

    files = collect_changed_files()
    if not files:
        return 0

    warnings = build_warnings(files)
    if not warnings:
        return 0
    if already_warned(str(payload.get("session_id") or ""), warnings):
        return 0

    message = "\n".join(f"- {w}" for w in warnings)
    print(f"作業完了前チェック:\n{message}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
