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

"""A standalone single-file conformant implementation of cnf.

Translates cnf to json, preserving order and text style where
possible. This layout makes it optimal for copying and embedding
into projects that would like to use cnf for reading configuration
files but would rather not add an additional external dependency.
"""

import re


class Options:
    """Reserved for future parse and render settings; none exist."""


class Error(Exception):
    """One parse or render failure."""


def to_json(data, options=None):
    """Translate cnf text to json text."""
    if isinstance(data, str):
        data = data.encode()
    root, err = _parse(data)
    if err is not None:
        raise err
    return _write_node_string(root)


#
# The tree: the whole document in map scopes
#

_UNQUOTED, _DOUBLE_QUOTED, _SINGLE_QUOTED = range(3)


class _KeyNode:
    """One key of one map scope and the value under it.

    A map, a list, or a scalar's pre-encoded json. A bare list
    element carries no key; a map's sub is never None.
    """

    __slots__ = ("key", "quote", "pos", "sub", "is_list", "json", "expanded", "offset")

    def __init__(self, key="", quote=_UNQUOTED, pos=None, sub=None,
                 is_list=False, json="", expanded=False, offset=0):
        self.key = key
        self.quote = quote
        self.pos = pos or _Pos(0, 0)
        self.sub = sub
        self.is_list = is_list
        self.json = json
        self.expanded = expanded
        self.offset = offset

    def find(self, key):
        for entry in self.sub or ():
            if entry.key == key:
                return entry
        return None


class _Pos:
    """A source position for errors: 1-based line and column."""

    __slots__ = ("line", "col")

    def __init__(self, line, col):
        self.line = line
        self.col = col


def _err_at(pos, msg):
    return Error(f"{pos.line}:{pos.col}: {msg}")


class _ScanError(Exception):
    """A scanner error, carrying the offender's offset within the text."""

    def __init__(self, offset, msg):
        super().__init__(msg)
        self.offset = offset
        self.msg = msg


def _err_at_scan(pos, text, scan_err):
    """Wrap a scan error at pos, advanced over the text the offset names."""
    if not isinstance(scan_err, _ScanError):
        return _err_at(pos, str(scan_err))
    offset = min(scan_err.offset, len(text))
    delta = text[:offset]
    line = pos.line + delta.count("\n")
    last = delta.rfind("\n")
    if last >= 0:
        col = len(delta[last + 1:]) + 1
    else:
        col = pos.col + len(delta)
    return _err_at(_Pos(line, col), scan_err.msg)


def _quote_key_path(path):
    """Spell a key path for an error: dot-joined segments in backquotes.

    A lone segment is one key: it takes its own quoting, no
    backticks around it.
    """
    if len(path) == 1:
        return _quote_key(path[0])
    parts = [_quote(k.key, k.quote) for k in path]
    return "`" + ".".join(parts) + "`"


def _quote_key(seg):
    """Spell one key segment for an error message.

    A key is a string however it was spelled, so the forced
    quoting spells it: a bare word escalates to double-quoted,
    a quoted one keeps its recorded family.
    """
    if seg.quote == _UNQUOTED and _is_bare_word(seg.key):
        return '"' + _escape_cnf(seg.key) + '"'
    return _quote(seg.key, seg.quote)


def _quote(s, q):
    """Return s quoted in the q family - one of the three families."""
    if q == _UNQUOTED:
        if _is_bare_word(s):
            return s
        q = _DOUBLE_QUOTED
        if '"' in s or "\\" in s:
            # The single family spells both raw - when it holds the rest.
            q = _SINGLE_QUOTED
            if "'" in s or "\n" in s:
                q = _DOUBLE_QUOTED
    if q == _SINGLE_QUOTED:
        if "'" in s or "\n" in s:
            q = _DOUBLE_QUOTED
    if q == _DOUBLE_QUOTED:
        return '"' + _escape_cnf(s) + '"'
    if q == _SINGLE_QUOTED:
        return "'" + s + "'"
    return s


def _is_bare_word(s):
    return bool(s) and all(_is_bare_rune(c) for c in s)


def _escape_cnf(s):
    """Spell s inside a double-quoted cnf string."""
    out = []
    for r in s:
        if r == '"':
            out.append('\\"')
        elif r == "\\":
            out.append("\\\\")
        elif r == "\n":
            out.append("\\n")
        elif r == "\r":
            out.append("\\r")
        elif r == "\t":
            out.append("\\t")
        elif r == "\b":
            out.append("\\b")
        elif r == "\f":
            out.append("\\f")
        elif ord(r) < 0x20:
            out.append("\\x%02x" % ord(r))
        elif r in ("\u2028", "\u2029"):
            out.append("\\u%04x" % ord(r))
        else:
            out.append(r)
    return "".join(out)


def _walk(scope, path):
    """Descend the path's inner segments, creating pass-through maps.

    Only a definition - a scalar or a list - blocks a path; a map is
    traversed, however spelled.
    """
    for seg in path[:-1]:
        node = scope.find(seg.key)
        if node is None:
            node = _KeyNode(seg.key, seg.quote, seg.pos, sub=[])
            scope.sub.append(node)
        elif node.json != "" or node.is_list:
            return None, _err_at(seg.pos, "cannot redefine previous key " + _quote_key(node))
        scope = node
    return scope, None


def _define(scope, path, val):
    """Place a non-map value: the tip must carry nothing yet."""
    parent, err = _walk(scope, path)
    if err is not None:
        return err
    tip = path[-1]
    if parent.find(tip.key) is not None:
        return _redefine_path(tip)
    parent.sub.append(_KeyNode(tip.key, tip.quote, tip.pos,
                              json=val.json, is_list=val.is_list, sub=val.sub))
    return None


def _expand(scope, path):
    """Open the tip's map for its items, once only."""
    parent, err = _walk(scope, path)
    if err is not None:
        return None, err
    tip = path[-1]
    node = parent.find(tip.key)
    if node is None:
        node = _KeyNode(tip.key, tip.quote, tip.pos, sub=[])
        parent.sub.append(node)
    elif node.json != "" or node.is_list:
        return None, _redefine_path(tip)
    elif node.expanded:
        return None, _expand_path_err(tip)
    node.expanded = True
    return node, None


def _redefine_path(seg):
    return _err_at(seg.pos, "cannot redefine previous key " + _quote_key(seg))


def _expand_path_err(seg):
    return _err_at(seg.pos,
                   "cannot expand map key " + _quote_key(seg) + " more than once")


def _wrap_path(path, val):
    """Wrap a keyed element's path around its value.

    One single-pair level per segment, the tip holding it.
    """
    node = _KeyNode(path[-1].key, path[-1].quote, path[-1].pos,
                    json=val.json, is_list=val.is_list, sub=val.sub)
    for seg in reversed(path[:-1]):
        node = _KeyNode(seg.key, seg.quote, seg.pos, sub=[node])
    return node


def _write_node_string(node):
    return _write_node(node)


def _write_node(node):
    """Write the value face.

    A list's elements, a map's pairs, or the scalar json. Keys
    are the parent's to write - a map writes them, a list does not.
    """
    if node.is_list:
        out = ["["]
        for i, entry in enumerate(node.sub or ()):
            if i:
                out.append(",")
            out.append(_write_list_element(entry))
        out.append("]")
        return "".join(out)
    if node.sub is not None:
        out = ["{"]
        for i, entry in enumerate(node.sub):
            if i:
                out.append(",")
            out.append(_json_string(entry.key))
            out.append(":")
            out.append(_write_node(entry))
        out.append("}")
        return "".join(out)
    return node.json


def _write_list_element(entry):
    # Nothing below the list writes keys: the head's own key
    # wraps its value here.
    if entry.key:
        return "{" + _json_string(entry.key) + ":" + _write_node(entry) + "}"
    return _write_node(entry)


#
# The document lines
#


def _split_lines(data):
    """Split data into lines: a 1-based number, indent, and content."""
    if not data:
        return []
    if data.endswith("\n"):
        data = data[:-1]  # the final newline ends the last line
    lines = []
    for num, raw in enumerate(data.split("\n"), 1):
        if raw.endswith("\r"):
            raw = raw[:-1]
        stripped = raw.lstrip(" \t")
        lines.append(_Line(num, raw[:len(raw) - len(stripped)], stripped))
    return lines


class _Line:
    __slots__ = ("num", "indent", "text")

    def __init__(self, num, indent, text):
        self.num = num
        self.indent = indent
        self.text = text


def _indent_pos(ln):
    return _Pos(ln.num, len(ln.indent) + 1)


def _quote_short(s):
    """Quote a short prefix of s for an error.

    Up to five characters as they stand, then ... when more follow.
    """
    return "`%s`" % escape(s[:5] + ("..." if len(s) > 5 else ""))


def escape(s):
    """Spell s by the double-quote rule, without the quotes.

    For the error messages that name a source fragment inside
    backquotes.
    """
    return _escape_cnf(s)


def _parse(data):
    """Read a cnf document into its root value node.

    An invalid UTF-8 byte names its line and column, both 1-based,
    counted in characters within the line.
    """
    try:
        text = data.decode()
    except UnicodeDecodeError as err:
        return None, _invalid_utf8(data)
    parser = _Parser(_split_lines(text))
    root, err = parser._parse_top()
    if err is not None:
        return None, err
    if parser.first is not None:
        return None, parser.first
    return root, parser.first


def _invalid_utf8(data):
    line, col, off = 1, 1, 0
    i = 0
    while i < len(data):
        if data[i] == 0x0A:
            line, col, off = line + 1, 1, i + 1
            i += 1
            continue
        try:
            # Decode one character; a lone continuation byte fails.
            ch = data[i:].decode()
            i += len(ch.encode())
        except UnicodeDecodeError:
            col += len(data[off:i].decode())
            return _err_at(_Pos(line, col),
                           "cannot decode byte %#x: not UTF-8" % data[i])
    # Unreachable: the caller only asks on invalid input.
    return Error("cannot decode document: not UTF-8")


#
# The parser: lines read into map scopes
#


class _Parser:
    def __init__(self, lines):
        self.lines = lines
        self.pos = 0
        self.pending = []  # comment and blank lines, not yet validated
        self.first = None  # the first key conflict, reported once the document parses whole

    def _save_err(self, err):
        """Record the first key conflict, for the parse's end."""
        if self.first is None:
            self.first = err

    def _peek_struct(self, prefix):
        """The next structural line.

        Skipped lines collect into the pending run. A shallower
        comment closes the block: returned unconsumed.
        """
        while self.pos < len(self.lines):
            ln = self.lines[self.pos]
            if ln.text == "":
                self.pending.append(ln)
                self.pos += 1
                continue
            if ln.text.startswith("#"):
                if len(ln.indent) < len(prefix):
                    return ln, True
                self.pending.append(ln)
                self.pos += 1
                continue
            return ln, True
        return None, False

    def _check_pending(self, prefix):
        """Validate the pending run at the block's exact prefix and drop it.

        json cannot carry comments, so only the indent rule stands.
        """
        err = _cmt_indent_ok(self.pending, prefix)
        self.pending = []
        return err

    def _parse_top(self):
        first, ok = self._peek_struct("")
        err = self._check_pending("")
        if err:
            return None, err
        if not ok:
            # An empty file is an empty map.
            return _KeyNode(sub=[]), None
        if _looks_like_item(first.text):
            # A pair-shaped line opens a map.
            root = _KeyNode(sub=[])
            err = self._parse_map(root, "")
            if err:
                return None, err
            return root, None
        # Any other value opens on its own line, at column zero.
        if first.indent:
            return None, _err_at(_indent_pos(first), "cannot indent a top-level value")
        root, err = self._parse_block_value(first)
        if err:
            return None, err
        ln, more = self._peek_struct("")
        if more:
            # Stray content after the top-level value.
            return None, _err_at(_indent_pos(ln),
                                  "cannot parse content after top-level value: "
                                  + _quote_short(ln.text))
        return root, None

    def _parse_block_value(self, first):
        """The block value opening at first, a peeked line."""
        v, err = None, None
        if _is_string_fence(first.text):
            s, err = self._parse_fence(first, first.text)
            v = _KeyNode(json=s)
        elif first.text == "---":
            v, err = self._parse_list_fence(first)
        elif _is_list_item(first.text):
            v, err = self._parse_block_list(first.indent)
        elif _looks_like_item(first.text):
            m = _KeyNode(sub=[])
            err = self._parse_map(m, first.indent)
            v = m
        else:
            # An inline value on its only line.
            self.pos += 1  # consume the value's own line
            v, err = self._parse_inline(first, first.text)
        if err:
            return None, err
        return v, None

    def _parse_map(self, scope, parent_indent):
        """One block map's pairs at the exact prefix, into the scope."""
        while True:
            ln, ok = self._peek_struct(parent_indent)
            if not ok:
                return self._check_pending(parent_indent)
            if ln.indent != parent_indent:
                if len(ln.indent) > len(parent_indent):
                    # The deeper line's own start: the pair that
                    # misses the block's prefix is named there.
                    return _err_at(_indent_pos(ln), "cannot mix indentation prefixes")
                # A shallower line closes the block; it stays in the
                # stream for the parent.
                return self._check_pending(parent_indent)
            err = self._check_pending(parent_indent)
            if err:
                return err
            self.pos += 1
            err = self._parse_item(ln, scope)
            if err:
                return err

    def _parse_item(self, ln, scope):
        """One "path: value" line into the scope.

        A token at offset i in the line's text sits at column
        len(indent)+1+i.
        """
        base = len(ln.indent) + 1
        path, after, err = _scan_key_path(ln.text)
        if err is not None:
            return _err_at_scan(_Pos(ln.num, base), ln.text, err)
        if after == "" or after[0] != ":":
            return _err_at(_Pos(ln.num, base + len(ln.text) - len(after)),
                           "cannot find key-value separator `:`")
        for seg in path:
            seg.pos = _Pos(ln.num, base + seg.offset)
        text = after[1:].lstrip(" \t")
        if text:
            rest, err = self._scan_pair_into(ln, scope, path, text)
            if err:
                return err
            return _trailing(ln, rest)
        nxt, ok = self._peek_struct(ln.indent)
        if not ok or len(nxt.indent) <= len(ln.indent):
            return _err_at(_indent_pos(ln),
                           "cannot omit the value for " + _quote_key_path(path))
        if _is_list_item(nxt.text):
            # A dashed block: a value defined under the path like
            # any other.
            pass
        elif _is_string_fence(nxt.text) or nxt.text == "---":
            # Nothing may sit between the pair and its fence.
            err = self._cmt_no_fence_prefix()
            if err:
                return err
        else:
            # A block map: the path expands once, and its items read
            # straight into the expansion. A conflict error is delayed
            # so parsing issues have precedence.
            tip, err = _expand(scope, path)
            if err:
                self._save_err(err)
                tip = _KeyNode(sub=[])
            return self._parse_map(tip, nxt.indent)
        val, err = self._parse_block_value(nxt)
        if err:
            return err
        err = _define(scope, path, val)
        if err:
            self._save_err(err)
        return None

    def _scan_pair_into(self, ln, scope, path, text):
        """A pair's inline value.

        An inline map expands the path, anything else is defined
        under it.
        """
        if text and text[0] == "{":
            tip, err = _expand(scope, path)
            if err:
                self._save_err(err)
                tip = _KeyNode(sub=[])
            pt = _Pos(ln.num, len(ln.text) - len(text) + len(ln.indent) + 1)
            return self._scan_inline_map_into(ln, text, pt, tip)
        val, rest, err = self._scan_value_at(ln, text)
        if err:
            return "", err
        err = _define(scope, path, val)
        if err:
            self._save_err(err)
        return rest, None

    def _parse_block_list(self, prefix):
        """One block list's "- item" lines at the exact prefix.

        Keyed elements' paths are wrapped around their values.
        """
        elems = []
        while True:
            ln, ok = self._peek_struct(prefix)
            if not ok or ln.indent != prefix or not _is_list_item(ln.text):
                err = self._check_pending(prefix)
                if err:
                    return None, err
                return _KeyNode(is_list=True, sub=elems), None
            err = self._check_pending(prefix)
            if err:
                return None, err
            self.pos += 1
            text = ln.text[1:].lstrip(" \t")
            if text == "":
                # A dash with nothing after it.
                return None, _err_at(_indent_pos(ln), "cannot omit the value")
            path = None
            # The inlinepair form: a path and a colon before the
            # value; without them the whole text is the value.
            k, rest, kerr = _scan_key_path(text)
            if kerr is None and rest and rest[0] == ":":
                off = len(ln.text) - len(text)
                for seg in k:
                    seg.pos = _Pos(ln.num, len(ln.indent) + 1 + off + seg.offset)
                path = k
                text = rest[1:].lstrip(" \t")
                if text == "":
                    # A path ending on its colon: the same omission
                    # parseItem reports.
                    return None, _err_at(
                        _indent_pos(ln),
                        "cannot omit the value for " + _quote_key_path(path))
            val, err = self._parse_inline(ln, text)
            if err:
                return None, err
            if path is not None:
                val = _wrap_path(path, val)
            elems.append(val)

    def _parse_fence(self, nxt, delim):
        """One fence block from its opening line, already peeked.

        In the escaped family a trailing backslash continues the line.
        """
        prefix = nxt.indent
        self.pos += 1  # consume the opening delimiter
        escaped = delim == '"""'
        out = []
        indent_char = " " if not prefix else prefix[0]
        continued = False
        while self.pos < len(self.lines):
            ln = self.lines[self.pos]
            self.pos += 1
            # The close wins even over a continuation: the escape ate
            # the newline, the value ends without one.
            if ln.indent == prefix and ln.text == delim:
                return _json_string("".join(out)), None
            if not continued and not _same_indent_char(ln.indent, indent_char):
                return "", _err_at(_indent_pos(ln),
                                   "cannot mix indentation prefixes in fence")
            if len(ln.indent) < len(prefix):
                if ln.text:
                    # Only the exact prefix closes the fence.
                    return "", _err_at(_indent_pos(ln),
                                       "cannot close fence at shallower prefix")
                # A blank line with a valid but shallower prefix:
                # the line contributes the newline only.
                out.append("\n")
                continue
            if ln.text == "":
                # A blank line at or deeper than the fence prefix: its
                # whitespace is content, with its terminator.
                out.append(ln.indent[len(prefix):])
                out.append("\n")
                continue
            if not ln.indent.startswith(prefix):
                return "", _err_at(_indent_pos(ln),
                                   "cannot mix indentation prefixes in fence")
            # The content following the valid prefix is the string,
            # including any excess indentation on deeper lines.
            content = ln.indent[len(prefix):] + ln.text
            content_pos = _Pos(ln.num, len(prefix) + 1)
            continued = False
            if escaped and _odd_trailing_backslashes(content):
                content = content[:-1]
                continued = True
            if escaped:
                unq, err = _unescape(content)
                if err:
                    return "", _err_at_scan(content_pos, content, err)
                content = unq
            out.append(content)
            if not continued:
                out.append("\n")
        return "", _err_at(_indent_pos(nxt), "cannot find closing fence")

    def _parse_list_fence(self, nxt):
        """One --- delimited list from its opening line.

        Each element is the lines between two --- at the fence's
        exact prefix.
        """
        prefix = nxt.indent
        self.pos += 1  # consume the opening ---
        elems = []
        nested = ""  # the indent of the fence's nested elements, once set
        while True:
            start = self.pos
            closed = False
            while self.pos < len(self.lines):
                cur = self.lines[self.pos]
                if cur.indent == prefix and cur.text == "---":
                    closed = True
                    break
                self.pos += 1
            if not closed:
                # The fence that never closes is named where it opened.
                return None, _err_at(_indent_pos(nxt),
                                     "cannot find closing list fence")
            elem = self.lines[start:self.pos]
            if not elem:
                # The error names the delimiter that opened the element:
                # the previous element's close, or the fence's own opening.
                open_ln = nxt if start == 0 else self.lines[start - 1]
                return None, _err_at(_indent_pos(open_ln),
                                     "cannot parse empty list fence element")
            # Nested fences must share one indent: the first sets it,
            # a mismatched one mixes indents inside the fence.
            if elem[0].text == "---" and len(elem[0].indent) > len(prefix):
                if nested == "":
                    nested = elem[0].indent
                elif elem[0].indent != nested:
                    return None, _err_at(_indent_pos(elem[0]),
                                         "cannot mix indents inside list fence")
            self.pos += 1
            sub = _Parser(elem)
            first, ok = sub._peek_struct(prefix)
            if not ok:
                open_ln = nxt if start == 0 else self.lines[start - 1]
                return None, _err_at(_indent_pos(open_ln),
                                     "cannot parse empty list fence element")
            # The fence's prefix delimits the element: a deeper line
            # opens a nested block only as a list fence.
            if first.indent != prefix and not (
                    first.text == "---" and len(first.indent) > len(prefix)):
                return None, _err_at(_indent_pos(first),
                                     "list element indent must align with fence")
            val, err = sub._parse_block_value(first)
            if err:
                return None, err
            # The element's own conflicts count too.
            self._save_err(sub.first)
            if sub.pos != len(sub.lines):
                # Content after the element's value.
                return None, _err_at(_indent_pos(sub.lines[sub.pos]),
                                     "cannot parse content in list fence element")
            elems.append(val)
            # The fence continues while the next line sits at its prefix
            # or deeper; a shallower line closes it and stays for the
            # parent.
            ln, ok = self._peek_struct(prefix)
            if not ok or len(ln.indent) < len(prefix):
                return _KeyNode(is_list=True, sub=elems), None

    def _parse_inline(self, ln, text):
        """One inline value on the item's line."""
        val, rest, err = self._scan_value_at(ln, text)
        if err:
            return None, err
        return val, _trailing(ln, rest)

    def _scan_value_at(self, ln, text):
        """One inline value from the front of text, and the remainder."""
        pt = _Pos(ln.num, len(ln.text) - len(text) + len(ln.indent) + 1)
        if text == "":
            # An empty scan: the usual source is an unclosed list's
            # spent tail.
            return None, "", _err_at(pt, 'cannot parse value at ""')
        c = text[0]
        if c == "{":
            # A fresh scope: nothing later reaches into a
            # value-position map.
            m = _KeyNode(sub=[])
            rest, err = self._scan_inline_map_into(ln, text, pt, m)
            if err:
                return None, "", err
            return m, rest, None
        if c == "[":
            return self._scan_inline_list(ln, text, pt)
        if c == '"':
            if text.startswith('"""'):
                return self._scan_fenced_line(ln, text, '"', pt)
            s, rest, err = _scan_double_quoted(text)
            if err:
                return None, "", _err_at_scan(pt, text, err)
            return _KeyNode(json=_json_string(s)), rest, None
        if c == "'":
            if text.startswith("'''"):
                return self._scan_fenced_line(ln, text, "'", pt)
            s, rest, err = _scan_single_quoted(text)
            if err:
                return None, "", _err_at(pt, str(err))
            return _KeyNode(json=_json_string(s)), rest, None
        tok, rest = _scan_scalar_token(text)
        if tok in ("null", "true", "false"):
            return _KeyNode(json=tok), rest, None
        if tok == "":
            # The text starts outside every scanned class.
            return None, "", _err_at(pt, "cannot parse value at `%s`" % escape(text))
        val, err = _scan_number(tok, pt)
        if err:
            return None, "", err
        return val, rest, None

    def _scan_inline_list(self, ln, text, at):
        """[1, 2] in the one-line form, into a list node."""
        elems = []
        text = text[1:].lstrip(" \t")
        if text.startswith("]"):
            return _KeyNode(is_list=True), text[1:], None
        while True:
            val, rest, err = self._scan_value_at(ln, text)
            if err:
                return None, "", err
            elems.append(val)
            rest = rest.lstrip(" \t")
            if rest == "":
                # Named where it opened, so nested lists tell apart.
                return None, "", _err_at(at, "cannot find closing `]`")
            if rest[0] == "]":
                return _KeyNode(is_list=True, sub=elems), rest[1:], None
            if rest[0] != ",":
                return None, "", _err_at(
                    _Pos(ln.num,
                         len(ln.indent) + 1 + len(ln.text) - len(rest)),
                    "cannot parse `%s` inside list" % escape(rest))
            text = rest[1:].lstrip(" \t")

    def _scan_inline_map_into(self, ln, text, at, scope):
        """{ a: 1, b: 2 } in the native item grammar, into the scope."""
        text = text[1:].lstrip(" \t")
        if text.startswith("}"):
            return text[1:], None
        while True:
            off = len(ln.text) - len(text)
            path, after, err = _scan_key_path(text)
            if err is not None:
                return "", _err_at_scan(
                    _Pos(ln.num, len(ln.indent) + 1 + off), text, err)
            if after == "" or after[0] != ":":
                return "", _err_at(
                    _Pos(ln.num,
                         len(ln.indent) + 1 + off + len(text) - len(after)),
                    "cannot find key-value separator `:`")
            for seg in path:
                seg.pos = _Pos(ln.num, len(ln.indent) + 1 + off + seg.offset)
            rest, err = self._scan_pair_into(
                ln, scope, path, after[1:].lstrip(" \t"))
            if err:
                return "", err
            rest = rest.lstrip(" \t")
            if rest == "":
                # Named where it opened, so nested maps tell apart.
                return "", _err_at(at, "cannot find closing `}`")
            if rest[0] == "}":
                return rest[1:], None
            if rest[0] != ",":
                return "", _err_at(
                    _Pos(ln.num,
                         len(ln.indent) + 1 + len(ln.text) - len(rest)),
                    "cannot parse `%s` inside map" % escape(rest))
            text = rest[1:].lstrip(" \t")

    def _scan_fenced_line(self, ln, text, quote, at):
        """A one-line fence.

        The first delimiter closes; in the escaped family the
        search skips escapes.
        """
        delim = quote * 3
        if quote == '"':
            end = -1
            i = 3
            while i <= len(text) - 3:
                if text[i] == "\\":
                    i += 2  # skip the escape; its quote is content
                    continue
                if text[i:i + 3] == delim:
                    end = i - 3
                    break
                i += 1
        else:
            idx = text.find(delim, 3)
            end = idx - 3 if idx >= 0 else -1
        if end < 0:
            return None, "", _err_at(at, "cannot find closing fence")
        inner = text[3:3 + end]
        inner_pos = _Pos(at.line, at.col + 3)
        rest = text[3 + end + 3:]
        if quote == '"':
            unq, err = _unescape(inner)
            if err:
                return None, "", _err_at_scan(inner_pos, inner, err)
            return _KeyNode(json=_json_string(unq)), rest, None
        # The raw family holds the interior as it stands.
        return _KeyNode(json=_json_string(text[3:3 + end])), rest, None

    def _cmt_no_fence_prefix(self):
        """Reject a pending run before a fence.

        Nothing may sit between the pair and the fence that opens
        under it.
        """
        for ln in self.pending:
            if ln.text:
                return _err_at(_indent_pos(ln),
                               "cannot comment between key and fence")
            return _err_at(_indent_pos(ln),
                           "cannot blank between key and fence")
        return None


def _trailing(ln, rest):
    """What follows a value on its line: nothing, or a comment."""
    left, _, ok = _strip_trail(rest)
    if ok or left == "":
        return None
    return _err_at(_Pos(ln.num, len(ln.indent) + 1 + len(ln.text) - len(left)),
                   "cannot parse trailing `%s`" % escape(left))


def _strip_trail(rest):
    """Split a trailing comment off the rest of a value.

    At least one blank, then #. A # glued to the value is
    content, not a comment.
    """
    i = 0
    while i < len(rest) and rest[i] in (" ", "\t"):
        i += 1
    if i == 0 or i >= len(rest) or rest[i] != "#":
        return rest, "", False
    return "", rest, True


def _same_indent_char(prefix, c):
    return all(ch == c for ch in prefix)


def _odd_trailing_backslashes(s):
    """Whether s ends on an odd run of backslashes."""
    n = len(s) - len(s.rstrip("\\"))
    return n % 2 == 1


#
# The byte scanners: the grammar's tokens, errors carrying the
# offender's offset within the scanned text.
#


def _scan_key_path(text):
    """A dotted path, each segment's offset recorded for positions.

    Spaces never separate path parts. Returns (path, rest, error).
    """
    if text == "" or text[0] == ".":
        return None, "", _ScanError(0, "cannot parse empty key segment")
    segs = []
    consumed = 0
    while True:
        seg, after, err = _scan_key(text)
        if err is not None:
            # The segment's offset must move into the whole
            # path's frame.
            if isinstance(err, _ScanError):
                return None, "", _ScanError(err.offset + consumed, err.msg)
            return None, "", err
        seg.offset = consumed
        segs.append(seg)
        consumed += len(text) - len(after)
        if after and after[0] == ".":
            if len(after) == 1:
                return None, "", _ScanError(consumed + 1,
                                            "cannot parse empty key segment")
            if after[1] in (" ", "\t"):
                return None, "", _ScanError(consumed + 1,
                                            "cannot parse space in path")
            text = after[1:]
            consumed += 1
            continue
        if after and after[0] in (" ", "\t"):
            return None, "", _ScanError(consumed, "cannot parse space in path")
        return segs, after, None


def _scan_key(text):
    """One key segment: a bare word or a quoted string."""
    if text == "":
        return None, "", _ScanError(0, "cannot parse empty key segment")
    c = text[0]
    if c == '"':
        s, rest, err = _scan_double_quoted(text)
        if err is not None:
            return None, "", err
        return _KeyNode(s, _DOUBLE_QUOTED), rest, None
    if c == "'":
        s, rest, err = _scan_single_quoted(text)
        if err is not None:
            return None, "", err
        return _KeyNode(s, _SINGLE_QUOTED), rest, None
    seg, rest = _scan_word(text)
    if seg == "":
        return None, "", _ScanError(0, "cannot parse empty key segment")
    for r in seg:
        if not _is_bare_rune(r):
            # Named at the segment start, so the path's consumed
            # count locates it.
            return None, "", _ScanError(0, "cannot parse key `%s`" % escape(seg))
    return _KeyNode(seg, _UNQUOTED), rest, None


def _scan_double_quoted(text):
    """A double-quoted string, processing escapes.

    Character-wise, not byte-wise: a multibyte character never holds
    an ASCII byte, so the delimiters meet at the same boundaries.
    """
    out = []
    i = 1
    while i < len(text):
        c = text[i]
        if c == '"':
            return "".join(out), text[i + 1:], None
        if c == "\\":
            if i + 1 >= len(text):
                return "", "", _ScanError(i, "cannot end string on an escape")
            r, n, err = _scan_escape(text[i:])
            if err:
                return "", "", _ScanError(i, str(err))
            out.append(r)
            i += n
            continue
        out.append(c)
        i += 1
    return "", "", Error("cannot find closing quote")


def _scan_single_quoted(text):
    """A single-quoted string: raw, no escapes."""
    end = text.find("'", 1)
    if end < 0:
        return "", "", Error("cannot find closing quote")
    return text[1:end], text[end + 1:], None


def _scan_escape(text):
    """One escaped character. Returns (rune, length, error)."""
    if len(text) < 2 or text[0] != "\\":
        return "", 0, Error("cannot parse escape")
    c = text[1]
    if c in ('"', "\\"):
        return c, 2, None
    simple = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
    if c in simple:
        return simple[c], 2, None
    if c == "u":
        return _scan_unicode(text)
    if c == "x":
        # Two hex digits must follow: text[2:4] slices them,
        # so four characters must be present.
        if len(text) >= 4:
            v, err = _parse_hex(text[2:4])
            if err is None:
                return chr(v), 4, None
        return "", 0, Error("cannot parse \\x escape")
    return "", 0, Error(f"cannot parse escape \\{c}")


def _scan_unicode(text):
    """One \\u escape, both \\u0000 and \\u{...}."""
    digits = ""
    n = 0
    if len(text) >= 5 and text[2] == "{":
        i = text.find("}")
        if 3 < i < 10:  # \u{0}
            n = i + 1
            digits = text[3:i]
    elif len(text) >= 6:  # \u0000
        n = 6
        digits = text[2:6]
    if n > 0:
        v, err = _parse_hex(digits)
        if err is None and _is_unicode_escape(v):
            return chr(v), n, None
    return "", 0, Error("cannot parse \\u escape")


def _is_unicode_escape(v):
    return v <= 0x10FFFF and not (0xD800 <= v <= 0xDFFF)


def _parse_hex(s):
    v = 0
    for c in s:
        d = _digit_val(c)
        if d < 0:
            return 0, Error("bad hex")
        v = v * 16 + d
    return v, None


def _scan_word(text):
    """The bare-word run at the front of text."""
    cut = 0
    while cut < len(text) and text[cut] not in " \t,]}.:":
        cut += 1
    return text[:cut], text[cut:]


def _is_bare_rune(r):
    return (r == "-" or r == "_"
            or "a" <= r <= "z" or "A" <= r <= "Z" or "0" <= r <= "9")


def _digit_val(c):
    if "0" <= c <= "9":
        return ord(c) - ord("0")
    if "a" <= c <= "f":
        return ord(c) - ord("a") + 10
    if "A" <= c <= "F":
        return ord(c) - ord("A") + 10
    return -1


def _scan_scalar_token(text):
    """The maximal token that could spell a scalar.

    The caller tells number, keyword, or bare word.
    """
    cut = 0
    if cut < len(text) and text[cut] == "-":
        cut += 1
    while cut < len(text):
        c = text[cut]
        if ("0" <= c <= "9" or "a" <= c <= "z" or "A" <= c <= "Z"
                or c == "."):
            cut += 1
        elif c in ("+", "-") and cut > 0 and text[cut - 1] in ("e", "E"):
            cut += 1
        else:
            return text[:cut], text[cut:]
    return text, ""


def _scan_number(tok, pt):
    """Validate a number-shaped token and encode its node.

    A bare word is never a value; based forms convert to decimal
    on the spot.
    """
    body = tok.removeprefix("-")
    if body == "" or not "0" <= body[0] <= "9":
        return None, _err_at(pt, "cannot parse unquoted value `%s`" % escape(tok))
    if len(body) > 2 and body[0] == "0":
        bases = {"x": 16, "o": 8, "b": 2}
        if body[1] in bases:
            base = bases[body[1]]
            digits = body[2:]
            for c in digits:
                if _digit_val(c) < 0 or _digit_val(c) >= base:
                    return None, _err_at(pt,
                                          "cannot parse number `%s`" % escape(tok))
            # Any width: Python ints carry the precision Go's
            # long division preserves.
            json_ = str(int(digits, base))
            if len(body) != len(tok):
                json_ = "-" + json_  # the sign the scanner cut off
            return _KeyNode(json=json_), None
    if "E" in body:
        return None, _err_at(pt, "cannot parse number `%s`: uppercase exponent"
                             % escape(tok))
    if len(body) > 1 and body[0] == "0" and body[1].isdigit():
        return None, _err_at(pt, "cannot parse number `%s`: redundant leading zero"
                             % escape(tok))
    if not _is_decimal_shape(body):
        return None, _err_at(pt, "cannot parse number `%s`" % escape(tok))
    return _KeyNode(json=tok), None


def _is_decimal_shape(body):
    """numint [ "." 1*DIGIT ] [ "e" ["+" / "-""] 1*DIGIT ].

    The redundant leading zero gets its own message.
    """
    mantissa = body
    i = body.find("e")
    if i >= 0:
        mantissa = body[:i]
        exp = body[i + 1:]
        if exp == "":
            return False
        if exp[0] in ("+", "-"):
            exp = exp[1:]
        if not _all_digits(exp):
            return False
    int_part = mantissa
    i = mantissa.find(".")
    if i >= 0:
        int_part = mantissa[:i]
        if not _all_digits(mantissa[i + 1:]):
            return False
    return int_part != "" and _all_digits(int_part)


def _all_digits(s):
    return bool(s) and all("0" <= c <= "9" for c in s)


def _unescape(s):
    """Decode the closed escape set over raw text.

    Errors carry the backslash's offset, for the caller to name
    the exact column.
    """
    out = []
    i = 0
    while i < len(s):
        if s[i] != "\\":
            out.append(s[i])
            i += 1
            continue
        if i + 1 >= len(s):
            return "", _ScanError(i, "cannot end line on an escape")
        r, n, err = _scan_escape(s[i:])
        if err:
            return "", _ScanError(i, str(err))
        out.append(r)
        i += n
    return "".join(out), None


#
# The json encoding of the leaf values
#


def _json_string(s):
    """A quoted json string: the closed set escaped, the rest verbatim."""
    return '"' + "".join(map(_json_escape, s)) + '"'


_JSON_ESCAPES = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r",
                 "\t": "\\t", "\b": "\\b", "\f": "\\f"}


def _json_escape(r):
    if r in _JSON_ESCAPES:
        return _JSON_ESCAPES[r]
    if r < " ":
        return "\\u%04x" % ord(r)
    return r


#
# The line-shape checks
#


def _cmt_indent_ok(run, parent):
    """A comment off the block's exact prefix mixes indentation."""
    for ln in run:
        if ln.text and ln.indent != parent:
            return _err_at(_indent_pos(ln), "cannot mix indentation prefixes")
    return None


def _looks_like_item(text):
    """A cheap check for a "path: value" line.

    The real scan names the path, not the value, on a bad line.
    """
    i = text.find(":")
    if i <= 0:
        return False
    c = text[0]
    return c in ('"', "'", ".") or _is_bare_rune(c)


def _is_list_item(text):
    """Whether text opens a block list item.

    A "-" followed by a blank or the end of the text.
    """
    return text == "-" or text.startswith(("- ", "-\t"))


def _is_string_fence(text):
    """Whether text is a fence delimiter."""
    return text == '"""' or text == "'''"
