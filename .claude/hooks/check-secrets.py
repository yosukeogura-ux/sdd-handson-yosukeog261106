#!/usr/bin/env python3
"""PreToolUse(Edit|Write) フック: 書き込み内容の秘密情報らしきパターンをブロックする。

exit 2 でツール実行を拒否し、stderr のメッセージが Claude に渡る
（security.md の規約を「文章による約束」ではなく「機械的な強制」に変える仕組み）。
※ 完全な検出ではなく事故防止のガード。PR 前の /review・security-auditor と併用する。
チェックするのは新しく書き込む内容（content / new_string）のみ。既存の秘密情報を
環境変数参照へ置き換える削除・修正の Edit は妨げない。
"""
from __future__ import annotations

import json
import re
import sys

# 秘密情報らしき代入を検知するキーワード。
# 先頭に語境界(\b)を付けない: db_password= / auth_token= のような接頭辞付き変数名を取りこぼさない
# ため。一方、キーワードの直後は区切り（= :）かクオートのみ許容する: 接尾辞まで許すと
# tokenizer= / token_endpoint= / password_field= のような別語・別用途の変数まで誤検知するため、
# 拾いたい複合語（secret_key 等）はここに明示的に追加する
_ASSIGN_KEYWORDS = r"(?:password|passwd|secret[_-]?key|secret|token|api[_-]?key)"
# クオートなしの値として許容する文字（シェルメタ文字・括弧類・引用符を除外）。
# 先読み（英数字混在の判定）と本体で同じクラスを使い、値の範囲判定を一致させる
_UNQUOTED_VALUE = r"[^\s\"'`;|&<>()\[\]{},]"

# (正規表現, 説明) のリスト。プロジェクトで利用するサービスのキー形式に合わせて追加・削除する
SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS アクセスキー"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "API キー（sk- 形式）"),
    (r"\bsk-(?:ant|proj)-[A-Za-z0-9_-]{24,}", "API キー（sk-ant- / sk-proj- 形式）"),
    (r"\bghp_[A-Za-z0-9]{36}\b", "GitHub トークン（ghp_）"),
    (r"\bgithub_pat_[A-Za-z0-9_]{22,}", "GitHub トークン（github_pat_）"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY( BLOCK)?-----", "秘密鍵"),
    # クオート付きの値。区切りは = と :（YAML / JSON）の両対応で、キー側のクオート（"password":）も
    # 許容する。値がプレースホルダ（<...> / ${...} / {{...}} / **** 等）の場合は誤検知しないよう除外する
    (
        r"(?i)" + _ASSIGN_KEYWORDS + r"[\"']?\s*[=:]\s*[\"'](?![<{$*])[^\"']{8,}",
        "パスワード等の秘密情報のハードコード",
    ),
    # クオートなしの値（.env / YAML 形式）。英字と数字が混在する8文字以上に限定し、
    # 関数呼び出し・環境変数参照・純数値の設定（get_token(32) / os.environ / max_tokens=100000 等）
    # への誤検知を防ぐ（純数字のみの値は対象外となる設計判断）
    (
        r"(?i)" + _ASSIGN_KEYWORDS + r"[\"']?\s*[=:][ \t]*(?![<{$*])"
        + r"(?=" + _UNQUOTED_VALUE + r"*\d)(?=" + _UNQUOTED_VALUE + r"*[a-zA-Z])"
        + _UNQUOTED_VALUE + r"{8,}",
        "パスワード等の秘密情報のハードコード",
    ),
)


def configure_utf8() -> None:
    """Windows のロケール既定（cp932 等）による文字化けを防ぐ。"""
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
    if not isinstance(tool_input, dict):
        return 0
    # Write は content、Edit は new_string に新しく書き込む内容が入る
    text = "\n".join(
        value
        for value in (tool_input.get("content"), tool_input.get("new_string"))
        if isinstance(value, str)
    )
    if not text:
        return 0

    for pattern, reason in SECRET_PATTERNS:
        if re.search(pattern, text):
            print(
                f"書き込みをブロックしました: {reason}らしきパターンを検出（security.md）。\n"
                "秘密情報の実値はコード・ドキュメント・コミットに含めず、環境変数経由で参照してください"
                "（実値の設定はユーザー自身が .env 等へ行い、.env.example にはキー名とダミー値のみ書く）。\n"
                "誤検知の場合は、検出箇所と理由を説明してユーザーに実行可否を確認してください。",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
