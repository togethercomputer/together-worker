# together-worker

## Example

```console
cat examples/echo.py
```

```python
from together_worker.fast_inference import FastInferenceInterface

class Echo(FastInferenceInterface):
    def setup(self, args):
        self.message = " to you too."

    def dispatch_request(self, args, env):
        prompt = args[0]["prompt"]
        return {
            "choices": [ { "text": prompt + self.message } ],
        }
```

### Test with local REST server

```console
pip install --upgrade together-worker
together-worker examples.echo Echo
```

```console
curl -X POST http://127.0.0.1:5001/ -d '{ "prompt": "test123" }'
{"choices": [{"text": "test123 to you too."}]}
```

## Setup dev

```console
make install
```

## Publish to PyPi

GitHub repo > Releases > Draft a new Release > Choose a tag > Create new tag on publish >

Name the tag using the current version from pyproject.toml with a "v" e.g. `v1.0.9`.

> Publish Release

In the repo toolbar select > Actions

- Verify the publish workflow is running and completes successfully

