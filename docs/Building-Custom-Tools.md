# Building Custom Tools

Cascade tools are regular Python classes that subclass `BaseTool`.

## Minimum Shape

```python
from cascade.tools.base import BaseTool, ToolCapability, ToolResult, ToolScope

class HelloTool(BaseTool):
    name = "hello_tool"
    description = "Return a greeting."
    capabilities = (ToolCapability.READ,)
    scope = ToolScope.META
    parameters_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
    }

    async def execute(self, **kwargs):
        return ToolResult(output=f"Hello {kwargs.get('name', 'world')}")
```

## Mutating Tools

Mutating tools should:

- set `mutating = True`
- implement a meaningful `dry_run()`
- describe reversibility correctly

## Distribution

Expose plugin tools through the `cascade.tools` entry-point group and enable the package in `cascade.yaml`.
