# Copyright 2026 Canonical Inc.
# Originally by Gustavo Niemeyer.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Variable expansion and error matching for the conformance corpus."""

import re

# One ${name} or ${name:form} reference; the forms are l, c, lc.
_VAR_REF = re.compile(r"\$\{([a-z]+)(?::([a-z]+))?\}")


def expand_vars(case, source, target):
    """Substitute the case's variables into target, from source.

    Returns (expanded, error): a reference to an undefined name,
    an unknown form, or a locator that finds nothing is the error.
    """
    if "${" not in target:
        return target, None
    out = []
    prev = 0
    broken = None
    for m in _VAR_REF.finditer(target):
        ref, name = m.group(0), m.group(1)
        form = m.group(2) or ""
        out.append(target[prev:m.start()])
        data = case.vars.get(name)
        if data is None:
            if not broken:
                broken = f"reference {ref} is not a defined var"
            out.append(ref)
        elif form == "" and not data.regexp:
            out.append(data.text)
        else:
            text, line, col, err = _locate(source, data)
            if err:
                if not broken:
                    broken = err
                out.append(ref)
            elif form in ("", "l", "c", "lc"):
                out.append({"": text, "l": str(line), "c": str(col),
                            "lc": f"{line}:{col}"}[form])
            else:
                if not broken:
                    broken = f"reference {ref} has an unknown form"
                out.append(ref)
        prev = m.end()
    out.append(target[prev:])
    expanded = "".join(out)
    if broken:
        return "", broken
    # Any ${...} left over - a reference whose name part is
    # not [a-z]+ - is undefined by the same rule.
    if "${" in expanded:
        rest = expanded[expanded.index("${"):]
        end = rest.find("}")
        ref = rest if end < 0 else rest[:end + 1]
        return "", f"reference {ref} is not a defined var"
    return expanded, None


def match_error(want, msg):
    """Check an error message against a case's error expectation.

    A literal compares for equality, a regexp matches anywhere.
    Returns (ok, error): the error reports a broken case - an
    undefined reference or a locator that matches nothing.
    """
    if not want[1]:  # a literal
        return msg == want[0], None
    try:
        return bool(re.search(want[0], msg)), None
    except re.error as err:
        return False, f"bad error regexp: {err}"


def _locate(source, data):
    """Find the expectation in the source; return (text, line, col, err).

    A literal is pinned at its first occurrence; a regexp matches
    anywhere, its first group the pin. Columns count characters,
    1-based within the line.
    """
    if not data.regexp:
        start = source.find(data.text)
        if start < 0:
            return "", 0, 0, f"literal {data.text!r} matches nothing in the block"
        end = start + len(data.text)
        text = data.text
    else:
        try:
            pattern = re.compile(data.text, re.M)
        except re.error as err:
            return "", 0, 0, f"bad locator regexp: {err}"
        m = pattern.search(source)
        if not m:
            return "", 0, 0, f"locator regexp {data.text!r} matches nothing in the block"
        start, end = m.span(1) if m.groups() else m.span()
        if start < 0:
            start, end = m.span()
        text = source[start:end]
    before = source[:start]
    line = before.count("\n") + 1
    line_start = before.rfind("\n") + 1
    col = len(source[line_start:start]) + 1
    return text, line, col, None
