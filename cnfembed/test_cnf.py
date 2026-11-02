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

"""The conformance corpus against cnfembed.

to-json parses each cnf block and renders it as json. The other
directions skip: the package renders, it does not parse json or
write cnf.
"""

import os

import cnftest
from cnfembed import Error, to_json


def convert(direction, source, reformat):
    if direction != "to-json":
        raise cnftest.Skip("unsupported direction: " + direction)
    try:
        return to_json(source)
    except Error as err:
        raise err


def check(fmt, kind, want, got):
    """Compare after trimming the whitespace between tokens.

    The case files write their json pretty-printed, to_json emits
    compact json.
    """
    if fmt == "json":
        want, got = trim_json(want), trim_json(got)
    if got.rstrip("\n") != want.rstrip("\n"):
        return f"mismatch:\nwant:\n{want}\ngot:\n{got}"
    return None


def trim_json(text):
    return "".join(line.strip() for line in text.split("\n") if line.strip())


_SPEC = os.path.join(os.path.dirname(__file__), "..", "spec", "cases")


def load_tests(loader, tests, pattern):
    return cnftest.tests(
        loader, tests, _SPEC, cnftest.Harness(convert, check))
