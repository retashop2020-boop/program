def register_list_files(registry, file_tools):
    registry.register(
        name="list_files",
        description=(
            "List files and directories inside the assigned workspace. "
            "Returns names only, without recursively listing subdirectories."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative directory path inside the workspace. "
                        "Defaults to the workspace root."
                    ),
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        execute=lambda arguments: file_tools.list_files(
            arguments.get("path", ".")
        ),
    )
