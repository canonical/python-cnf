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

"""
A trivial smoke test over cnfembed, meant to be copied with
cnfembed.py. The full conformance suite runs on the original
repository:

https://github.com/canonical/go-cnf
"""

import json
import unittest

from cnfembed import *


class TestSmokeExample(unittest.TestCase):

    def test_run(self):
        got = to_json(CNF_STR)
        self.assertEqual(got, trim_json(JSON_STR))
        json.loads(got)


class TestSmokeErrors(unittest.TestCase):

    def test_run(self):
        for cnf, error in CNF_ERRORS:
            with self.subTest(error):
                with self.assertRaises(Error) as caught:
                    to_json(cnf)
                self.assertEqual(str(caught.exception), error)


class TestEscape(unittest.TestCase):

    def test_run(self):
        self.assertEqual(escape('a"b\nc'), 'a\\"b\\nc')


def trim_json(text):
    """Trim each line's whitespace and join the rest compactly:
    the fixture is indented for reading, to_json emits compact
    json, and a json string value holds no newline, so the trim
    touches layout only.
    """
    return "".join(line.strip() for line in text.split("\n") if line.strip())


# The smoke fixture is the spec's own Example, holding most constructs.
CNF_STR = r"""
key: "value"
nested.key: "another value"

map:
    inline: {a: 1, b: 2}

    block:
        a: 1
        b: 2

    block.c: 3

list:
    inline: [1, 2, 3]

    block.strings:
        - "item 1"
        - "item 2"

    block.maps:
        - label: "map 1"
        - label: "map 2"

    block.list-of-maps:
        ---
        list1.map1:
            a: 1
            b: 2
        list1.map2:
            c: 3
            d: 4
        ---
        list2.map1:
            a: 1
            b: 2
        ---

    block.list-of-lists:
        ---
        - "list 1 item 1"
        - "list 1 item 2"
        ---
        - "list 2 item 1"
        ---

string:
    double: "line 1\nline 2\nline 3"

    # One line, no escaping, literal slash
    single: 'line 1\nline 1 still'

    # Three lines, with escaping support.
    fence.double.inline: @FENCE@line 1\nLine 2\nline 3\n@FENCE@
    fence.double.block:
        @FENCE@
        line 1\nline \
        2
        line 3
        @FENCE@

    # One line, no escaping, literal slash
    fence.single.inline: '''line 1\nline 1 still'''
    fence.single.block:
        '''
        line 1\n
        line 2
        '''

numbers:
    int: 123
    float: 1.23
    hex: 0x123
    octal: 0o777
    binary: 0b011
    exponent: 1e-23
""".replace("@FENCE@", '"""')

JSON_STR = r"""
{
    "key":"value",
    "nested":{"key":"another value"},
    "map":{
        "inline":{"a":1,"b":2},
        "block":{"a":1,"b":2,"c":3}
    },
    "list":{
        "inline":[1,2,3],
        "block":{
            "strings":["item 1","item 2"],
            "maps":[{"label":"map 1"},{"label":"map 2"}],
            "list-of-maps":[
                {"list1":{"map1":{"a":1,"b":2},"map2":{"c":3,"d":4}}},
                {"list2":{"map1":{"a":1,"b":2}}}
            ],
            "list-of-lists":[
                ["list 1 item 1","list 1 item 2"],
                ["list 2 item 1"]
            ]
        }
    },
    "string":{
        "double":"line 1\nline 2\nline 3",
        "single":"line 1\\nline 1 still",
        "fence":{
            "double":{
                "inline":"line 1\nLine 2\nline 3\n",
                "block":"line 1\nline 2\nline 3\n"
            },
            "single":{
                "inline":"line 1\\nline 1 still",
                "block":"line 1\\n\nline 2\n"
            }
        }
    },
    "numbers":{
        "int":123,
        "float":1.23,
        "hex":291,
        "octal":511,
        "binary":3,
        "exponent":1e-23
    }
}
"""

CNF_ERRORS = [
    ("a: \"x", "1:4: cannot find closing quote"),
    ("a: {b: 1\n", "1:4: cannot find closing `}`"),
    ("a: 1\n\tb: 2\n", "2:2: cannot mix indentation prefixes"),
    ("a:\n b:\n\t\tc: 1\n", "3:3: cannot mix indentation prefixes"),
    ("a:\n    \"\"\"\ncontent\n", "3:1: cannot close fence at shallower prefix"),
    ("1\nbogus\n", "2:1: cannot parse content after top-level value: `bogus`"),
    ("a 1\n", "1:1: cannot parse unquoted value `a`"),
    ("a: bare\n", "1:4: cannot parse unquoted value `bare`"),
    ("a..b: 1\n", "1:3: cannot parse empty key segment"),
    ("a .b: 1\n", "1:2: cannot parse space in path"),
    ("a:\n", '1:1: cannot omit the value for "a"'),
    ("a:\n    b.c:\n", "2:5: cannot omit the value for `b.c`"),
    ("a: 1\na: 2\n", '2:1: cannot redefine previous key "a"'),
    ("a: 1\na.b: 2\n", '2:1: cannot redefine previous key "a"'),
    ("a: {b: 1}\na: {c: 2}\n", '2:1: cannot expand map key "a" more than once'),
    ("a: \"x\\dy\"\n", "1:6: cannot parse escape \\d"),
    ("a: 02\n", "1:4: cannot parse number `02`: redundant leading zero"),
    ("a: 1E5\n", "1:4: cannot parse number `1E5`: uppercase exponent"),
]
