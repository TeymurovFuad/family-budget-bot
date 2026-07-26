"""
tests/mdv2_helpers.py — shared MarkdownV2 validation helpers for tests.

Telegram MarkdownV2 rules enforced here:
- Outside code spans every reserved character must be backslash-escaped.
- Inside code spans, '`' and '\\' must be escaped; other characters are raw.
- '*' and '_' are excluded from the reserved set because handler texts
  legitimately use them as bold/italic markup — balance is asserted instead.

The scan is a single left-to-right pass that consumes '\\X' escape pairs and
tracks code-span state on the raw text. This avoids the trap of stripping
escapes first and locating code spans afterwards: a legal '\\`' inside a code
span must not toggle code-span state or mis-pair the remaining backticks.
"""

# Reserved MarkdownV2 characters that must be escaped in plain text.
RESERVED = set("[]()~>#+-=|{}.!")


def find_unescaped_reserved(text: str) -> list[str]:
    """Return a description of every reserved char left unescaped outside
    code spans. Empty list means the text is clean."""
    problems = []
    in_code = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            if i + 1 >= len(text):
                problems.append("stray trailing backslash")
                break
            i += 2  # escape pair — legal inside and outside code spans
            continue
        if ch == "`":
            in_code = not in_code
            i += 1
            continue
        if not in_code and ch in RESERVED:
            context = text[max(0, i - 25):i + 25].replace("\n", "⏎")
            problems.append(f"unescaped {ch!r} near: …{context}…")
        i += 1
    return problems


def assert_markup_balanced(text: str) -> None:
    """Assert backticks pair up and '*'/'_' are balanced outside code spans.
    Same single-pass escape/code-span logic as find_unescaped_reserved."""
    in_code = False
    stars = underscores = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            assert i + 1 < len(text), "stray trailing backslash"
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
            i += 1
            continue
        if not in_code:
            if ch == "*":
                stars += 1
            elif ch == "_":
                underscores += 1
        i += 1
    assert not in_code, "unbalanced backticks"
    assert stars % 2 == 0, "unbalanced asterisks"
    assert underscores % 2 == 0, "unbalanced underscores"


def assert_valid_markdown_v2(text: str, source: str = "reply") -> None:
    """Full check: no unescaped reserved chars + balanced markup."""
    problems = find_unescaped_reserved(text)
    assert not problems, f"MarkdownV2 violations in {source}:\n" + "\n".join(problems)
    assert_markup_balanced(text)
