def register_run_tests(registry, test_service, workspace, profile_registry):
    profile_ids = [profile.profile_id for profile in profile_registry.list_profiles()]
    registry.register(
        name="run_tests",
        description=(
            "Run an approved test profile in the assigned workspace. "
            f"Valid profile IDs: {chr(44).join(profile_ids)}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "profile_id": {
                    "type": "string",
                    "enum": profile_ids,
                    "description": "Registered test profile identifier",
                }
            },
            "required": ["profile_id"],
            "additionalProperties": False,
        },
        execute=lambda arguments: test_service.execute(
            arguments["profile_id"],
            workspace,
        ),
    )
