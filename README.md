# Python implementation of the cnf format

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