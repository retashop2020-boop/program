class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name, description, parameters, execute):
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")

        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "execute": execute,
        }

    def get(self, name):
        return self._tools[name]

    def definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in self._tools.values()
        ]
