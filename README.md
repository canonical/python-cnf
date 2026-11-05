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
implementation. The benchmark was run using the data of a real yaml file
with ~67k nodes in a diversified distribution totaling ~800kb. The same
file was converted to cnf in the same structure, and also compact json.

| Test                                     | Parser                | Best (ms) |  MB/s |
|------------------------------------------|-----------------------|----------:|------:|
| yaml => map (`safe_load`)                | YAML 1.2, pure Python |   1,441.7 |  0.53 |
| cnf => map (`to_json` + `json.loads`)    | cnfembed, pure Python |     142.6 |  7.72 |
| cnf => map (`ToJSON` + `json.Unmarshal`) | cnfembed, Go          |      23.4 | 47.24 |

A conformant YAML 1.2 pure Python implementation was selected, not named
here as this is just supposed to show that the performance is not so bad,
even being a pure Python implementation, and even if we opt to translate
first into json rather than doing a direct map decode.


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
