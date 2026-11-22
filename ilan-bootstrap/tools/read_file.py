def register_read_file(registry, file_tools):
    registry.register(
        name="read_file",
        description="Read a UTF-8 text file inside the assigned workspace.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path of the file inside the workspace",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        execute=lambda arguments: file_tools.read_file(arguments["path"]),
    )
