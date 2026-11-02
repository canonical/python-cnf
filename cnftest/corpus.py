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

"""The conformance-corpus reader: the case files under spec/cases."""

import glob
import json
import os
import re


class Topic:
    """One cases/<name>.md file: a name and its Cases."""

    def __init__(self, name):
        self.name = name
        self.cases = []


class Data:
    """One expected text a case carries: a literal, or a regexp."""

    def __init__(self, text, regexp=False):
        self.text = text
        self.regexp = regexp


class Directive:
    """One direction's expected outcome: "" when the direction is absent."""

    def __init__(self, kind=""):
        self.kind = kind

    def is_error(self):
        return self.kind == "error"


class Reformat:
    """The reformat settings a case declares, the corpus's vocabulary."""

    def __init__(self):
        self.unfold_list_from_items = 0
        self.unfold_map_from_items = 0
        self.fold_list_upto_items = 0
        self.fold_map_upto_items = 0
        self.fold_path_upto_depth = 0
        self.fold_path_from_depth = 0
        self.unfold_path_from_depth = 0
        self.unfold_path_upto_depth = 0
        self.soft_wrap_string_from_width = 0
        self.hard_wrap_string_from_width = 0
        self.reindent = ""
        self.ignore_comments = False

    def set(self, name, val):
        names = {
            "unfold-list-from-items": "unfold_list_from_items",
            "unfold-map-from-items": "unfold_map_from_items",
            "fold-list-upto-items": "fold_list_upto_items",
            "fold-map-upto-items": "fold_map_upto_items",
            "fold-path-upto-depth": "fold_path_upto_depth",
            "fold-path-from-depth": "fold_path_from_depth",
            "unfold-path-from-depth": "unfold_path_from_depth",
            "unfold-path-upto-depth": "unfold_path_upto_depth",
            "soft-wrap-string-from-width": "soft_wrap_string_from_width",
            "hard-wrap-string-from-width": "hard_wrap_string_from_width",
        }
        if name == "reindent":
            raise ValueError(f"reformat setting {name!r} is not an int")
        if name not in names:
            raise ValueError(f"unknown reformat setting {name!r}")
        setattr(self, names[name], val)


class Case:
    """One ## Case section: a name, directives, and its blocks."""

    def __init__(self, name):
        self.name = name
        self.to_json = Directive()
        self.from_json = Directive()
        self.to_ast = Directive()
        self.from_ast = Directive()
        self.error = Data("")
        self.vars = {}
        self.reformat = Reformat()
        self.parse_ast = False
        self.cnf = []
        self.json = []
        self.ast = []

    def directive(self, direction):
        return {
            "to-json": self.to_json,
            "from-json": self.from_json,
            "to-ast": self.to_ast,
            "from-ast": self.from_ast,
        }[direction]


def read_all(directory):
    """Read every *.md file under directory (skipping README)."""
    files = sorted(glob.glob(os.path.join(directory, "*.md")))
    if not files:
        raise ValueError(f"no case files found in {directory}")
    topics = []
    for file in files:
        name = os.path.basename(file)[:-3]
        if name == "README":
            continue  # documentation, not a case
        topic = _read_topic(file, name)
        if not topic.cases:
            raise ValueError(f"{name}: no cases found")
        for case in topic.cases:
            _validate_blocks(case)
        topics.append(topic)
    return topics


def _validate_blocks(case):
    """Check the machine-read blocks of a case.

    Each ast/json block is exactly one JSON value, and a directive
    reads every block.
    """
    if not case.parse_ast:
        for block in case.ast:
            _one_json_value("ast", block)
    for block in case.json:
        _one_json_value("json", block)
    reads_cnf = (case.to_json.kind != "" or case.to_ast.kind != ""
                 or (case.from_json.kind != "" and not case.from_json.is_error())
                 or (case.from_ast.kind != "" and not case.from_ast.is_error()))
    reads_json = case.from_json.kind != "" or (
        case.to_json.kind != "" and not case.to_json.is_error())
    reads_ast = case.from_ast.kind != "" or (
        case.to_ast.kind != "" and not case.to_ast.is_error())
    if case.cnf and not reads_cnf:
        raise ValueError("cnf block without a directive that reads it")
    if case.json and not reads_json:
        raise ValueError("json block without a directive that reads it")
    if case.ast and not reads_ast:
        raise ValueError("ast block without a directive that reads it")


def _one_json_value(kind, text):
    """text holds exactly one JSON value, nothing but blanks from it."""
    try:
        _, end = json.JSONDecoder().raw_decode(text)
    except ValueError as err:
        raise ValueError(f"{kind} block is not JSON: {err}")
    rest = text[end:].strip()
    if rest:
        raise ValueError(
            f"{kind} block has trailing content after the value: {rest[:40]!r}")


def _read_topic(file, name):
    """Parse one case file: the header, the prose, the case sections."""
    with open(file, encoding="utf-8") as f:
        data = f.read()
    topic = Topic(name)
    lines = data.split("\n")
    if not lines or not lines[0].startswith("# "):
        raise ValueError("cannot find opening # header")
    case = None
    section = ""
    block = []
    in_fence = False
    vars_mode = False
    pretty_mode = False
    pretty_seen = set()

    def flush():
        nonlocal block
        if not section:
            return
        # An empty cnf block is meaningful: the empty file.
        if not block and section != "cnf":
            return
        text = "\n".join(block) + "\n"
        if section == "cnf" and not block:
            text = ""
        getattr(case, section).append(text)
        block = []

    for ln in lines[1:]:
        if ln.startswith("## Case"):
            case_name = _case_name(ln)
            for prev in topic.cases:
                if prev.name == case_name:
                    raise ValueError(f"duplicate case name {case_name!r}")
            # No flush here: every content fence flushes at its close.
            case = Case(case_name)
            pretty_seen = set()
            topic.cases.append(case)
            section = ""
            in_fence = False
        elif case is None:
            continue  # prose before the first case
        elif in_fence:
            if ln.startswith("```"):
                flush()
                in_fence = False
                vars_mode = False
                pretty_mode = False
            elif section:
                block.append(ln)
            elif not ln.strip():
                continue
            elif vars_mode and ln[:1] in (" ", "\t"):
                var_name, var_data = _parse_header_value(ln)
                if not _is_var_name(var_name):
                    raise ValueError(f"var name {var_name!r} is not [a-z]+")
                if var_name in case.vars:
                    raise ValueError(f"duplicate var {var_name!r}")
                case.vars[var_name] = var_data
            elif pretty_mode and ln[:1] in (" ", "\t"):
                colon = ln.find(":")
                if colon < 0:
                    raise ValueError(f"{ln}: cannot find key-value separator")
                setting = ln[:colon].strip()
                if setting in pretty_seen:
                    raise ValueError(f"duplicate reformat setting {setting!r}")
                pretty_seen.add(setting)
                if setting == "reindent":
                    # The one string setting, a cnf double-quoted string.
                    _, val = _parse_header_pair(ln)
                    case.reformat.reindent = val
                elif setting == "ignore-comments":
                    # The one bool setting.
                    val = ln[colon + 1:].strip()
                    if val not in ("true", "false"):
                        raise ValueError(
                            f"{ln}: reformat setting {setting!r}: cannot parse {val!r}")
                    case.reformat.ignore_comments = val == "true"
                else:
                    val = ln[colon + 1:].strip()
                    try:
                        num = int(val)
                    except ValueError:
                        raise ValueError(
                            f"{ln}: reformat setting {setting!r}: cannot parse {val!r}")
                    try:
                        case.reformat.set(setting, num)
                    except ValueError as err:
                        raise ValueError(f"{ln}: {err}")
            elif ln.strip() == "vars:":
                vars_mode = True
                pretty_mode = False
            elif ln.strip() == "reformat:":
                pretty_mode = True
                vars_mode = False
            elif ln.startswith("parse-ast:"):
                val = ln[len("parse-ast:"):].strip()
                if val != "true":
                    raise ValueError(f"{ln}: parse-ast expects true, got {val!r}")
                case.parse_ast = True
            else:
                key, header_data = _parse_header_value(ln)
                # Only error: and the vars take the regexp map.
                if header_data.regexp and key != "error":
                    raise ValueError(f"{ln}: a regexp map is not allowed here")
                if key == "to-json":
                    case.to_json = Directive(header_data.text)
                elif key == "from-json":
                    case.from_json = Directive(header_data.text)
                elif key == "to-ast":
                    case.to_ast = Directive(header_data.text)
                elif key == "from-ast":
                    case.from_ast = Directive(header_data.text)
                elif key == "error":
                    case.error = header_data
                else:
                    raise ValueError(f"unknown header key {key!r}")
        elif ln.startswith("### "):
            # No flush here either: the closing fence already flushed.
            section = ln[len("### "):].strip()
        elif ln.startswith("```"):
            in_fence = True
    # The final flush catches a file that ends inside a fence.
    if in_fence:
        flush()
    return topic


def _case_name(ln):
    """Read the name from a "## Case: <name>" header."""
    name = ln[len("## Case:"):].strip()
    if not name:
        raise ValueError("case header without a name")
    for ch in name:
        if not _is_bare_rune(ch):
            raise ValueError(f"case name {name!r} is not a bare word")
    return name


def _is_var_name(name):
    return bool(name) and all("a" <= ch <= "z" for ch in name)


def _is_bare_rune(ch):
    return (ch == "-" or ch == "_"
            or "a" <= ch <= "z" or "A" <= ch <= "Z" or "0" <= ch <= "9")


def _parse_header_value(ln):
    """Split one `key: value` header line.

    The value is a cnf double-quoted string, or a {regexp: "..."} map.
    """
    colon = ln.find(":")
    if colon < 0:
        raise ValueError("cannot find key-value separator")
    key = ln[:colon].strip()
    rest = ln[colon + 1:].strip()
    if rest.startswith("{"):
        # The map form: {regexp: "..."} exactly - one key, nothing else.
        if not rest.startswith("{regexp:"):
            raise ValueError(
                f"cannot parse value {rest!r}: the map key must be regexp")
        val = rest[len("{regexp:"):]
        if not val.endswith("}"):
            raise ValueError(f"cannot parse value {rest!r}: the map does not close")
        val = val[:-1].strip()
        if not val:
            raise ValueError(f"cannot parse value {rest!r}: the map value is empty")
        text = _unquote(val)
        try:
            re.compile(text)
        except re.error as err:
            raise ValueError(f"bad regexp {text!r}: {err}")
        return key, Data(text, regexp=True)
    return key, Data(_unquote(rest))


def _parse_header_pair(ln):
    """Split one `key: "value"` header line: the plain-string form."""
    key, header_data = _parse_header_value(ln)
    if header_data.regexp:
        raise ValueError(
            "cannot parse value %r: a regexp map is not allowed here"
            % header_data.text)
    return key, header_data.text


def _unquote(rest):
    """Read one cnf double-quoted string, its escapes decoded."""
    if len(rest) < 2 or rest[0] != '"' or rest[-1] != '"':
        raise ValueError(f"cannot parse value {rest!r}")
    out = []
    i = 1
    while i < len(rest) - 1:
        ch = rest[i]
        if ch == "\\" and i + 1 < len(rest) - 1:
            i += 1
            esc = rest[i]
            if esc == "n":
                out.append("\n")
            elif esc == "t":
                out.append("\t")
            elif esc == "u":
                # \u takes exactly four hex digits, all inside the quotes.
                if not _is_hex_run(rest[i + 1:i + 5]):
                    raise ValueError(
                        f"cannot parse escape \\u{rest[i + 1:i + 5]}: wants four hex digits")
                out.append(chr(int(rest[i + 1:i + 5], 16)))
                i += 4
            elif esc == "U":
                if not _is_hex_run(rest[i + 1:i + 9]):
                    raise ValueError(
                        f"cannot parse escape \\U{rest[i + 1:i + 9]}: wants eight hex digits")
                n = int(rest[i + 1:i + 9], 16)
                if n > 0x10FFFF:
                    raise ValueError(
                        f"cannot parse escape \\U{rest[i + 1:i + 9]}: out of range")
                out.append(chr(n))
                i += 8
            elif esc in ('"', "\\"):
                out.append(esc)
            else:
                raise ValueError(f"cannot parse escape \\{esc}")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _is_hex_run(s):
    return bool(s) and all(c in "0123456789abcdefABCDEF" for c in s)
