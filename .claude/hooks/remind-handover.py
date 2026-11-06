#!/usr/bin/env python3
"""Stop フック: 前回のセッションログ記録以降にコミットが積み上がっていたら /handover を促す。

「セッション終了時や作業の区切り」を機械的に検知する手段は無いため、代わりに次の2つを
区切りの目安として使う。
1. 直近のログ記録（docs/project/log/ の最新ファイルの更新時刻。無ければこのセッションで最初に
   本フックが呼ばれた時刻）以降に一定数のコミットが積まれたか
2. 直近のログ記録以降のコミットに、PRマージによるマージコミット（「Merge pull request #」で
   始まる件名）が含まれるか（1件数閾値に達していなくても、PRマージは明確な区切りのため即座に促す）

いずれかを満たしたセッションでは exit 2 で一度だけ Stop をブロックし、Claude に
「ユーザーへ /handover の実行を提案するか検討する」よう促す（stderr の内容が Claude に渡る）。
ログへの追記自体はこのフックが強制するものではなく、あくまでユーザーの明示的な依頼を受けてから
行う（動作規定「セッション引き継ぎ」・docs/project/log/README.md）。

コミット数の判定は HEAD のコミット総数の差分で行う（git log --since の秒単位丸めでは、ログ記録
直後・コミット直後にフックが同一秒内で呼ばれた場合に誤って1件多く/少なくカウントしうるため）。
ログの更新時刻から commit 数へ変換する一度きりの --since 呼び出しだけは時刻ベースだが、
その後の蓄積判定は整数の差分のみで行うため誤差が累積しない。

同一セッションでの再ブロックは1回のみ（ユーザーが実際に /handover を実行してログが更新されたら
基準をリセットし、以後の蓄積で再度促す）。stop_hook_active が true の場合は再ブロックしない
（無限ループ防止。check-consistency.py と同じ方式）。git 管理外・判定不能な場合は何もしない。
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "docs" / "project" / "log"
# セッションごとの判定状態の記録先（.gitignore 登録済み）
STATE_FILE = PROJECT_ROOT / ".claude" / ".handover-reminder-state.json"
COMMIT_THRESHOLD = 3  # この件数以上コミットが積まれたら促す


def configure_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def run_git(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
            cwd=PROJECT_ROOT,
        )
    except (subprocess.SubprocessError, OSError):
        return None


def is_git_repo() -> bool:
    result = run_git(["rev-parse", "--is-inside-work-tree"])
    return result is not None and result.returncode == 0


def head_commit_count() -> int | None:
    result = run_git(["rev-list", "--count", "HEAD"])
    if result is None or result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def commits_since(iso_time: str) -> int | None:
    """iso_time 以降にコミットされた件数（HEAD 上）。判定不能なら None。"""
    result = run_git(["rev-list", "--count", f"--since={iso_time}", "HEAD"])
    if result is None or result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def commit_subjects(count: int) -> list[str]:
    """直近 count 件のコミットの件名一覧（新しい順）。count が0以下・取得不能なら空リスト。"""
    if count <= 0:
        return []
    result = run_git(["log", f"-{count}", "--format=%s"])
    if result is None or result.returncode != 0:
        return []
    return result.stdout.splitlines()


def has_merge_commit(subjects: list[str]) -> bool:
    """GitHub の PR マージでできるマージコミット（"Merge pull request #..."）が含まれるか。"""
    return any(s.startswith("Merge pull request #") for s in subjects)


def latest_log_mtime() -> float | None:
    if not LOG_DIR.is_dir():
        return None
    mtimes = [f.stat().st_mtime for f in LOG_DIR.glob("*.md") if f.name != "README.md"]
    return max(mtimes) if mtimes else None


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # 記録できない環境では毎回初回判定になるだけで、動作自体は継続する


def main() -> int:
    configure_utf8()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0

    # 無限ループ防止: このフックによるブロックから続行中の場合は再ブロックしない
    if payload.get("stop_hook_active"):
        return 0

    if not is_git_repo():
        return 0

    current_head_count = head_commit_count()
    if current_head_count is None:
        return 0  # コミットが無い等、判定不能なら塞がない

    log_mtime = latest_log_mtime()

    session_id = str(payload.get("session_id") or "")
    state = load_state()
    session_state = state.get(session_id)

    if session_state is None:
        # このセッションで初めての判定: 基準となる commit 数を決める。
        # 既存ログがあれば「ログ更新時刻以降のコミット数」を差し引いた時点を基準にし、
        # 無ければ現在の HEAD をそのまま基準にする（全コミット履歴を対象にしない）
        if log_mtime is not None:
            since_log = commits_since(datetime.datetime.fromtimestamp(log_mtime).isoformat())
            baseline_head_count = current_head_count - since_log if since_log is not None else current_head_count
        else:
            baseline_head_count = current_head_count
        state[session_id] = {
            "baseline_head_count": baseline_head_count,
            "baseline_log_mtime": log_mtime,
            "reminded": False,
        }
        save_state(state)
        return 0

    # 基準時点より新しいログがあれば /handover 実行済みとみなし、基準を今のコミット数にリセットする
    baseline_log_mtime = session_state.get("baseline_log_mtime")
    if log_mtime is not None and (baseline_log_mtime is None or log_mtime > baseline_log_mtime):
        state[session_id] = {
            "baseline_head_count": current_head_count,
            "baseline_log_mtime": log_mtime,
            "reminded": False,
        }
        save_state(state)
        return 0

    if session_state.get("reminded"):
        return 0  # このセッションでは既に一度促した

    baseline_head_count = session_state.get("baseline_head_count")
    if not isinstance(baseline_head_count, int):
        return 0
    commits = current_head_count - baseline_head_count
    if commits <= 0:
        return 0

    subjects = commit_subjects(commits)
    merge_detected = has_merge_commit(subjects)
    if commits < COMMIT_THRESHOLD and not merge_detected:
        return 0

    session_state["reminded"] = True
    state[session_id] = session_state
    save_state(state)

    if merge_detected:
        reason = "直近のログ記録以降のコミットにPRのマージコミットを検知しました"
    else:
        reason = f"直近のログ記録以降に {commits} 件のコミットが積み上がっています"

    print(
        f"{reason}。\n"
        "作業の区切りとして、ユーザーに /handover（「ログを記録して」）の実行を提案するか検討してください。\n"
        "（ログへの追記は必ずユーザーの明示的な依頼を受けてから行うこと。このメッセージは提案の要否を検討するための"
        "合図であり、自動での追記を指示するものではない）",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
