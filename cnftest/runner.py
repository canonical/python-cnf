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

"""The harness to run the conformance corpus against an implementation."""

import fnmatch
import unittest

from . import corpus, match

# The directions a case may declare, in the order they run.
DIRECTIONS = ("to-json", "from-json", "to-ast", "from-ast")


class Skip(Exception):
    """A harness's refusal to run one direction, in its own words."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class Harness:
    """One test binary's registration against the corpus.

    convert runs one direction: reading the source text, producing
    the target text, or raising the error the case's error directive
    advises - or Skip, for a direction the harness does not run.
    check decides whether a direction's output matches its
    expectation: a falsy return means equal, a string is the
    mismatch report.
    """

    def __init__(self, convert, check):
        self.convert = convert
        self.check = check


def tests(loader, tests_, directory, harness):
    """Build the corpus suite: one test per case, in discovery order.

    A suite module hands this to unittest's own load_tests hook,
    so every case shows as a test of its own - the runner counts,
    names, and filters them the way Go's subtests do. The loader's
    -k patterns select cases here too, as unittest cannot filter
    a suite the hook builds.
    """
    suite = unittest.TestSuite()
    for topic in corpus.read_all(directory):
        for case in topic.cases:
            name = f"{topic.name}/{case.name}"
            test = _case_test(name, case, harness)
            if _selected(loader, test.id()):
                suite.addTest(test)
    return suite


def _selected(loader, tid):
    """Whether the loader's -k patterns select the test named tid."""
    patterns = getattr(loader, "testNamePatterns", None)
    if not patterns:
        return True
    # The plain pattern, its fnmatch form, or a bare substring.
    return any(tid == p or fnmatch.fnmatchcase(tid, p) or p in tid
               for p in patterns)


def _case_test(name, case, harness):
    """One corpus case as one TestCase, named by its case."""

    def runTest(test):
        _run_case(test, name, case, harness)

    tid = f"cases/{name}"
    cls = type(f"cases.{name}", (_CaseTest,), {
        "runTest": runTest,
        "_case_tid": tid,
    })
    return cls("runTest")


class _CaseTest(unittest.TestCase):
    """The one corpus test's recording handle, outside any subTest."""

    _case_tid = "cases/?"  # the generated class spells the real one

    def id(self):
        return self._case_tid

    def __str__(self):
        return self._case_tid

    def shortDescription(self):
        return None  # the name is the description


def _run_case(test, name, case, harness):
    ran = False
    for direction in DIRECTIONS:
        directive = case.directive(direction)
        if directive.kind == "":
            continue
        if _run_direction(test, name, case, direction, directive, harness):
            ran = True
    if not ran:
        test.skipTest(f"{name}: skipping unsupported formats case: {_formats(case)}")


def _run_direction(test, name, case, direction, directive, harness):
    if not _known_kind(directive.kind):
        test.fail(f"{name}: {direction}: unknown directive kind {directive.kind!r}")
        return True
    inputs, expectations, skip = _blocks(case, direction, harness)
    if isinstance(skip, Skip):
        # The harness refuses every input of the direction.
        return False
    if skip is not None:
        test.fail(f"{name}: {direction}: broken case: {skip}")
        return True
    for i in range(len(inputs)):
        expanded, err = match.expand_vars(case, inputs[i], inputs[i])
        if err:
            test.fail(f"{name}: {direction}: {_source_name(direction)} "
                      f"block #{i + 1}: broken case: {err}")
            return True
        inputs[i] = expanded
    skip = None
    for block in inputs:
        try:
            harness.convert(direction, block, case.reformat)
        except Skip as s:
            skip = s
            break
        except Exception:
            pass  # a probe for refusal only; the verdict comes later
    if skip is not None:
        return False
    if directive.is_error():
        for i, block in enumerate(inputs):
            try:
                harness.convert(direction, block, case.reformat)
            except Exception as raised:  # noqa: BLE001 - the harness's own contract
                msg = str(raised)
            else:
                test.fail(f"{name}: {direction}: {_source_name(direction)} "
                          f"block #{i + 1}: no error, want {case.error.text!r}")
                continue
            expanded, xerr = match.expand_vars(case, block, case.error.text)
            if xerr:
                test.fail(f"{name}: {direction}: {_source_name(direction)} "
                          f"block #{i + 1}: broken case: {xerr}")
                continue
            ok, merr = match.match_error(expanded, msg)
            if merr:
                test.fail(f"{name}: {direction}: {_source_name(direction)} "
                          f"block #{i + 1}: broken case: {merr}")
                continue
            if not ok:
                test.fail(f"{name}: {direction}: {_source_name(direction)} "
                          f"block #{i + 1}: error:\n  got  {msg!r}\n"
                          f"  want {expanded!r}")
        return True
    if not expectations:
        test.fail(f"{name}: {direction} needs a "
                  f"{_expectation_name(direction)} block")
        return True
    for i, block in enumerate(inputs):
        want, err = match.expand_vars(case, block, expectations[0])
        if err:
            test.fail(f"{name}: {direction}: {_source_name(direction)} "
                      f"block #{i + 1}: broken case: {err}")
            continue
        try:
            got = harness.convert(direction, block, case.reformat)
        except Exception as err:  # noqa: BLE001
            test.fail(f"{name}: {direction}: {_source_name(direction)} "
                      f"block #{i + 1}: {err}")
            continue
        report = harness.check(_format_name(direction), directive.kind, want, got)
        if report:
            test.fail(f"{name}: {direction}: {_source_name(direction)} "
                      f"block #{i + 1}: {report}")
    return True


def _known_kind(kind):
    return kind in ("advised-text", "exact-value", "advised-value", "error")


def _blocks(case, direction, harness):
    """Return (inputs, expectations, err): the blocks of one direction.

    The from-ast inputs convert through the harness's own to-ast when
    the case's ast blocks are spelled as cnf. An entry the converter
    skips is dropped; a case whose every entry refuses skips its whole
    direction, returned as a Skip in the err slot.
    """
    if direction == "to-json":
        return case.cnf, case.json, None
    if direction == "from-json":
        return case.json, case.cnf, None
    if direction == "to-ast":
        return case.cnf, case.ast, None
    if direction == "from-ast" and not case.parse_ast:
        return case.ast, case.cnf, None
    # from-ast with parse-ast: the ast blocks convert to ast first.
    ast_blocks = []
    skip = None
    for block in case.ast:
        try:
            out = harness.convert("to-ast", block, case.reformat)
        except Skip as s:
            skip = s  # remember the refusal in case it is the only one
            continue
        except Exception as err:  # noqa: BLE001
            return None, None, err
        ast_blocks.append(out)
    if not ast_blocks and case.ast:
        return None, None, skip
    return ast_blocks, case.cnf, None


def _source_name(direction):
    if direction in ("to-json", "to-ast"):
        return "cnf"
    if direction == "from-json":
        return "json"
    if direction == "from-ast":
        return "ast"
    return "source"


def _format_name(direction):
    if direction == "to-json":
        return "json"
    if direction in ("from-json", "from-ast"):
        return "cnf"
    if direction == "to-ast":
        return "ast"
    return "expectation"


def _expectation_name(direction):
    return _format_name(direction)


def _formats(case):
    """The source formats of the case's declared directions, ", "-joined."""
    names = []
    for direction in DIRECTIONS:
        if case.directive(direction).kind != "":
            names.append(_source_name(direction))
    return ", ".join(names)
