"""Steam launch options: add and remove single environment settings without
touching anything else on the line.

Decky-Framegen's own panel replaces a game's whole launch options with
``WINEDLLOVERRIDES=dxgi=n,b SteamDeck=0 %command%``; that drops whatever
other tools (a frame limiter, gamemoderun, the user) put there. Here the two
settings are merged in instead, and removed again exactly.
"""

import re
import shlex

COMMAND_RE = re.compile(r"%command%", re.I)
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
MERGE_KEYS = ("WINEDLLOVERRIDES",)   # values are ';'-separated lists that can be combined


def split_tokens(text):
    """Split like a shell would, but keep every token's original spelling."""
    text = text or ""
    tokens, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        start, quote = i, None
        while i < n:
            c = text[i]
            if quote:
                if c == "\\" and quote == '"' and i + 1 < n:
                    i += 1
                elif c == quote:
                    quote = None
            elif c in "'\"":
                quote = c
            elif c == "\\" and i + 1 < n:
                i += 1
            elif c.isspace():
                break
            i += 1
        if i > start:
            tokens.append(text[start:i])
    return tokens


def _unquote(value):
    try:
        parts = shlex.split(value)
    except ValueError:
        return value
    return parts[0] if len(parts) == 1 else value


def parse_env(text):
    """The leading ``NAME=value`` settings of a launch-options line, in order."""
    out = []
    for tok in split_tokens(text):
        if COMMAND_RE.search(tok) or not ENV_RE.match(tok):
            break
        name, value = tok.split("=", 1)
        out.append((name, _unquote(value)))
    return out


def env_prefix_len(tokens):
    n = 0
    for tok in tokens:
        if COMMAND_RE.search(tok) or not ENV_RE.match(tok):
            break
        n += 1
    return n


def _merge_list(old, new):
    parts = [p for p in old.split(";") if p]
    for p in new.split(";"):
        if p and p not in parts:
            parts.append(p)
    return ";".join(parts)


def _unmerge_list(old, gone):
    drop = [p for p in gone.split(";") if p]
    return ";".join(p for p in old.split(";") if p and p not in drop)


def _quote(value):
    return value if re.fullmatch(r"[A-Za-z0-9_.,:;=/+@%-]*", value) else shlex.quote(value)


def add_env(text, env):
    """Returns (new_text, added). ``added`` lists what was really put there,
    as ``[name, value, previous_or_None, previous_as_written]``; hand it to
    ``remove_env`` to undo."""
    tokens = split_tokens(text)
    has_command = any(COMMAND_RE.search(t) for t in tokens)
    if tokens and not has_command:
        # Steam appends such text to the game's command line: keep it there.
        tokens = ["%command%"] + tokens
    elif not tokens:
        tokens = ["%command%"]
    n = env_prefix_len(tokens)
    added = []
    for name, value in env.items():
        idx = next((i for i in range(n) if tokens[i].split("=", 1)[0] == name), None)
        if idx is None:
            tokens.insert(n, "%s=%s" % (name, _quote(value)))
            n += 1
            added.append([name, value, None])
            continue
        raw = tokens[idx].split("=", 1)[1]
        current = _unquote(raw)
        if name in MERGE_KEYS:
            merged = _merge_list(current, value)
            if merged != current:
                tokens[idx] = "%s=%s" % (name, _quote(merged))
                added.append([name, value, current, raw])
        elif current != value:
            tokens[idx] = "%s=%s" % (name, _quote(value))
            added.append([name, value, current, raw])
    return " ".join(tokens), added


def remove_env(text, added):
    """Undo ``add_env``: take out what was added, put back what was replaced.
    A setting the user changed in between is left alone."""
    tokens = split_tokens(text)
    n = env_prefix_len(tokens)
    for item in added or []:
        name, value, previous = item[0], item[1], item[2]
        spelled = item[3] if len(item) > 3 else None
        idx = next((i for i in range(n) if tokens[i].split("=", 1)[0] == name), None)
        if idx is None:
            continue
        current = _unquote(tokens[idx].split("=", 1)[1])
        if name in MERGE_KEYS:
            rest = _unmerge_list(current, value)
            if rest:
                keep = spelled if spelled is not None and rest == previous else _quote(rest)
                tokens[idx] = "%s=%s" % (name, keep)
            else:
                del tokens[idx]
                n -= 1
        elif current == value:
            if previous is None:
                del tokens[idx]
                n -= 1
            else:
                tokens[idx] = "%s=%s" % (name, spelled if spelled is not None else _quote(previous))
    if len(tokens) == 1 and COMMAND_RE.fullmatch(tokens[0]):
        return ""
    return " ".join(tokens)


def has_env(text, env):
    have = dict(parse_env(text))
    for name, value in env.items():
        if name not in have:
            return False
        if name in MERGE_KEYS:
            parts = have[name].split(";")
            if any(p and p not in parts for p in value.split(";")):
                return False
        elif have[name] != value:
            return False
    return True


def uses_fgmod_wrapper(text):
    """Decky-Framegen's older wrapper method (``~/fgmod/fgmod %command%``)."""
    return bool(re.search(r"(^|[\s/])fgmod(\s|$)", text or ""))


# --- a wrapper command right before %command% (MAKO's mako-run) -------------------------------

def _base(tok):
    return tok.strip("'\"").replace("\\", "/").rsplit("/", 1)[-1]


def has_wrapper(text, name):
    return any(_base(t) == name for t in split_tokens(text))


def add_wrapper(text, path):
    """Put `path` right before %command% (after every setting and other wrapper).
    Returns (new_text, added)."""
    name = _base(path)
    tokens = split_tokens(text)
    if any(_base(t) == name for t in tokens):
        return text or "", False
    idx = next((i for i, t in enumerate(tokens) if COMMAND_RE.search(t)), None)
    if idx is None:
        # Text without %command% are arguments for the game: they go after it.
        tokens = [_quote(path), "%command%"] + tokens
    else:
        tokens.insert(idx, _quote(path))
    return " ".join(tokens), True


def remove_wrapper(text, name):
    tokens = [t for t in split_tokens(text) if _base(t) != name]
    if len(tokens) == 1 and COMMAND_RE.fullmatch(tokens[0]):
        return ""
    return " ".join(tokens)
