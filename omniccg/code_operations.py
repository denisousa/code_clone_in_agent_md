from pathlib import Path

def get_code_without_comments_and_blank_lines(file: str, ls: int, le: int) -> str:
    """
    Generate a SHA-256 hash from the code between lines ls and le (inclusive),
    ignoring blank lines and comments.
    """
    path = Path(file)
    ext = path.suffix.lower()

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    # slice only the requested segment
    segment = "".join(lines[ls - 1:le])

    # remove comments depending on file extension
    if ext in {".c", ".cs", ".java"}:
        cleaned = _strip_c_style_comments(segment)
    elif ext == ".php":
        cleaned = _strip_c_style_comments(segment, hash_comment=True)
    elif ext == ".py":
        cleaned = _strip_hash_comments(segment)
    elif ext == ".rb":
        cleaned = _strip_hash_comments(segment, ruby_block_comments=True)
    else:
        # if extension is unknown, only remove blank lines later
        cleaned = segment

    # normalize: drop blank lines and trailing spaces
    norm_lines = [
        line.rstrip()
        for line in cleaned.splitlines()
        if line.strip() != ""
    ]
    normalized_code = "\n".join(norm_lines)
    return normalized_code


def _strip_c_style_comments(code: str, hash_comment: bool = False) -> str:
    """
    Remove C-style comments:
    // line comment
    /* block comment */
    If hash_comment=True, also treat '#' as line comment (for PHP).
    """
    result = []
    i = 0
    n = len(code)
    in_block = False
    in_line = False
    in_string = False
    string_char = ""
    escaping = False

    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""

        if in_block:
            # end of block comment
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
            else:
                # preserve newlines
                if ch == "\n":
                    result.append("\n")
                i += 1
            continue

        if in_line:
            # end of line comment
            if ch == "\n":
                in_line = False
                result.append("\n")
            i += 1
            continue

        if in_string:
            result.append(ch)
            if escaping:
                escaping = False
            elif ch == "\\":
                escaping = True
            elif ch == string_char:
                in_string = False
            i += 1
            continue

        # outside string/comment: handle strings
        if ch in ("'", '"'):
            in_string = True
            string_char = ch
            result.append(ch)
            i += 1
            continue

        # handle // and /* */
        if ch == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue

        # handle '#' as comment start (PHP)
        if hash_comment and ch == "#":
            in_line = True
            i += 1
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def _strip_hash_comments(code: str, ruby_block_comments: bool = False) -> str:
    """
    Remove '#' based comments:
    - Python: '#' to end of line (respecting simple strings)
    - Ruby: same + =begin/=end block comments when enabled.
    """
    import re

    lines = code.splitlines(keepends=True)
    result_lines = []
    in_ruby_block = False

    for line in lines:
        stripped = line.lstrip()

        # Ruby block comments =begin / =end
        if ruby_block_comments:
            if not in_ruby_block and re.match(r"^=begin\b", stripped):
                in_ruby_block = True
                continue
            if in_ruby_block:
                if re.match(r"^=end\b", stripped):
                    in_ruby_block = False
                continue

        new_line = _remove_hash_comment_line(line)
        result_lines.append(new_line)

    return "".join(result_lines)


def _remove_hash_comment_line(line: str) -> str:
    """
    Remove everything after '#' in a single line,
    ignoring '#' that appear inside simple/double-quoted strings.
    """
    result = []
    in_string = False
    string_char = ""
    escaping = False
    in_comment = False

    for ch in line:
        # If we're already in a comment, keep only the newline (if any)
        if in_comment:
            if ch in ("\n", "\r"):
                result.append(ch)
                in_comment = False
            continue

        if in_string:
            result.append(ch)
            if escaping:
                escaping = False
            elif ch == "\\":
                escaping = True
            elif ch == string_char:
                in_string = False
            continue

        # Outside string / comment
        if ch in ("'", '"'):
            in_string = True
            string_char = ch
            result.append(ch)
            continue

        if ch == "#":
            # Start of a comment: ignore everything until newline
            in_comment = True
            continue

        result.append(ch)

    return "".join(result)
