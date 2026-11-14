"""Read and change single keys of an INI file (OptiScaler.ini) in place,
keeping comments, order and line endings."""

import re

SECTION_RE = re.compile(r"^\s*\[(.+?)\]\s*$")


def get(text, section, key):
    cur = None
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            cur = m.group(1).strip().lower()
            continue
        if cur == section.lower():
            m = re.match(r"^\s*%s\s*=(.*)$" % re.escape(key), line, re.I)
            if m:
                return m.group(1).strip()
    return None


def set(text, section, key, value):  # noqa: A001 - mirrors get
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    out, cur, done, last_of_section = [], None, False, None
    for line in lines:
        m = SECTION_RE.match(line)
        if m:
            cur = m.group(1).strip().lower()
        elif cur == section.lower() and not done and re.match(r"^\s*%s\s*=" % re.escape(key), line, re.I):
            out.append("%s=%s" % (key, value))
            done = True
            last_of_section = len(out)
            continue
        out.append(line)
        if cur == section.lower() and line.strip():
            last_of_section = len(out)
    if not done:
        if last_of_section is None:
            if out and out[-1].strip():
                out.append("")
            out += ["[%s]" % section, "%s=%s" % (key, value)]
        else:
            out.insert(last_of_section, "%s=%s" % (key, value))
    return nl.join(out) + (nl if text.endswith(("\n", "\r")) or not text else "")
