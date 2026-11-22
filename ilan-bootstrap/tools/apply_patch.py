def register_apply_patch(registry, file_tools, approval_callback):
    def execute_patch(arguments):
        preview = file_tools.preview_patch(arguments)

        approved = approval_callback(preview)

        if not approved:
            return {
                "status": "rejected",
                "path": preview["path"],
                "diff": preview["diff"],
            }

        result = file_tools.apply_patch(arguments)
        result["status"] = "applied"
        return result

    registry.register(
        name="apply_patch",
        description=(
            "Propose exact text changes to an existing workspace file. "
            "A preview diff will be shown to the user and explicit approval "
            "is required before any change is applied. "
            "Never claim the patch was applied unless status is 'applied'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path of the file to modify",
                },
                "expected_sha256": {
                    "type": "string",
                    "description": "SHA-256 hash of the original file",
                },
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_text": {"type": "string"},
                            "new_text": {"type": "string"},
                        },
                        "required": ["old_text", "new_text"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["path", "expected_sha256", "changes"],
            "additionalProperties": False,
        },
        execute=execute_patch,
    )
