import json
from dataclasses import asdict, is_dataclass
from pathlib import Path


class ToolDispatcher:
    def __init__(self, registry):
        self.registry = registry

    def execute(self, name, arguments):
        tool = self.registry.get(name)

        if isinstance(arguments, str):
            arguments = json.loads(arguments)

        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")

        result = tool["execute"](arguments)

        if is_dataclass(result):
            result = asdict(result)
        elif isinstance(result, Path):
            result = str(result)

        return result
