# Python support for the cnf format

## Packages

- `cnfembed` - Text-preserving cnf to json, a single file for embedding.
- `cnftest` - Harness to run the conformance tests.


## Specification

Consult the [full specification](https://github.com/canonical/cnf) for examples and details of the format.


## Running tests

The `cnftest` harness runs the full conformance corpus, from a local
copy of the spec kept for the tests. To run the tests:

```shell
python3 -m unittest discover
```


## Performance

The following table offers a vague data point on the performance of the
implementation. It's as fair as I could make it: the two documents spell
the same data in the same indentation shape. Both documents decode to the
identical tree: 6721 maps, 11833 lists, 24605 scalars.

| Test                                   | Parser                | Best (ms) |  MB/s |
|----------------------------------------|-----------------------|----------:|------:|
| yaml => map (`CSafeLoader`)            | pyyaml, libyaml C     |     105.1 | 10.73 |
| yaml => map (`SafeLoader`)             | pyyaml, pure Python   |     988.5 |  1.14 |
| cnf => json (`to_json`)                | cnfembed, pure Python |     238.3 |  7.10 |
| cnf => map (`to_json` + `json.loads`)  | cnfembed, pure Python |     247.7 |  6.84 |

The json decode comes almost for free in relative terms given that the
format is much simpler and the stdlib one is written in C.


## Example

This simple example shows the conversion of cnf to json:

```cnf
key: "value"
nested.key: 0xff
string:
    """
    Hello
    world
    """
```

One call decodes it to JSON:

```python
from cnfembed import to_json

json = to_json(doc)
```

This results in:

```json
{"key":"value","nested":{"key":255},"string":"Hello\nworld\n"}
```

For the time being this port converts one direction only: cnf to json.

A string that fails to parse raises `Error` with the message
including the line and column of the problem:

```python
from cnfembed import Error, to_json

try:
    to_json("a: bare\n")
except Error as err:
    print(err)  # 1:4: cannot parse unquoted value `bare`
```

For actual embedding into your project, you may opt to copy the `cnfembed/cnf.py`
file alone.
