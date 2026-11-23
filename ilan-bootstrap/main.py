import os
import subprocess
from pathlib import Path

from agent.loop import AgentLoop
from core.docker_executor import DockerTestExecutor
from core.authorization import AuthorizationManager
from core.file_tools import FileTools
from core.test_execution import TestExecutionService
from core.test_executor import ExecutionLimits
from core.test_profiles import create_default_test_profile_registry
from core.workspace import WorkspaceBoundary
from model.openrouter import OpenRouterClient, OpenRouterError
from model.gemini import GeminiClient, GeminiError
from model.ollama_agent_client import OllamaAgentClient, OllamaError
from tools.dispatcher import ToolDispatcher
from tools.read_file import register_read_file
from tools.list_files import register_list_files
from tools.registry import ToolRegistry
from tools.run_tests import register_run_tests
from tools.apply_patch import register_apply_patch


from core.relay_lifecycle import RelayLifecycle, RelayLifecycleConfig
from core.relay_server import RelayHTTPServer
from core.relay_session import RelaySessionManager


def discover_eth0_ipv4():
    result = subprocess.run(
        ["/usr/sbin/ip", "-4", "-o", "addr", "show", "dev", "eth0"],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        fields = line.split()
        if "inet" in fields:
            return fields[fields.index("inet") + 1].split("/", 1)[0]
    raise RuntimeError("Could not discover eth0 IPv4 address")


def request_authorization(operation):
    print("\nدرخواست مجوز مدیریتی برای:")
    print(operation)
    answer = input("اجازه می‌دهید؟ [y/N]: ").strip().lower()
    return answer in {"y", "yes"}

def request_patch_approval(preview):
    print("\nپیش‌نمایش تغییرات:")
    print(f"File: {preview['path']}")
    print(preview["diff"])

    answer = input("Apply this patch? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def main():
    workspace_path = Path(
        os.environ.get(
            "ILAN_WORKSPACE",
            str(Path.home() / "ilan-lab" / "ilan-workbench" / "workspace"),
        )
    ).expanduser()

    workspace_path.mkdir(parents=True, exist_ok=True)
    workspace = WorkspaceBoundary(workspace_path)

    relay = None
    relay_started = False

    try:
        relay_config = RelayLifecycleConfig(
            bind_host=discover_eth0_ipv4(),
            port=18765,
        )

        relay = RelayLifecycle(
            relay_config,
            server_factory=lambda *, config, session_manager, on_shutdown_requested: (
                RelayHTTPServer(
                    (config.bind_host, config.port),
                    session_manager,
                    on_shutdown_requested=on_shutdown_requested,
                )
            ),
            session_manager_factory=lambda config: RelaySessionManager(
                suspect_after_seconds=config.suspect_after_seconds,
                recoverable_after_seconds=config.recoverable_after_seconds,
                lease_timeout_seconds=config.lease_timeout_seconds,
            ),
        )

        relay.start()
        relay_started = True
        print(f"Relay listening at {relay.server_address}")

        file_tools = FileTools(workspace)

        profile_registry = create_default_test_profile_registry()
        limits = ExecutionLimits(
            timeout_seconds=120,
            memory_bytes=512 * 1024 * 1024,
            cpu_cores=1.0,
        )

        authorization_manager = AuthorizationManager(
            approval_callback=request_authorization
        )
        executor = DockerTestExecutor(
            authorization_manager=authorization_manager
        )

        test_service = TestExecutionService(
            registry=profile_registry,
            executor=executor,
            limits=limits,
        )

        tool_registry = ToolRegistry()
        register_read_file(tool_registry, file_tools)
        register_list_files(tool_registry, file_tools)
        register_apply_patch(tool_registry, file_tools, request_patch_approval)
        register_run_tests(tool_registry, test_service, workspace, profile_registry)

        dispatcher = ToolDispatcher(tool_registry)

        model_provider = os.environ.get(
            "ILAN_MODEL_PROVIDER", "ollama"
        ).strip().lower()

        if model_provider == "ollama":
            model_client = OllamaAgentClient()
        elif model_provider == "openrouter":
            model_client = OpenRouterClient()
        elif model_provider == "gemini":
            model_client = GeminiClient()
        else:
            raise ValueError(
                f"Unsupported ILAN_MODEL_PROVIDER: {model_provider}"
            )

        print(f"Model provider: {model_provider}")

        agent = AgentLoop(
            model_client=model_client,
            tool_registry=tool_registry,
            tool_dispatcher=dispatcher,
            system_prompt=(
                "You are Ilan, an AI agent working with the user. "
                "The user is the project architect and decision-maker. "
                "Help with analysis, architecture design, and technical work. "
                "Use the available tools when useful. "
                "You may read files, list files, run the registered pytest profile, "
                "and propose file changes using the apply_patch tool. "
                "When asked to inspect a file and suggest an improvement, "
                "analyze the actual file contents and identify a specific, "
                "small, justified improvement yourself. "
                "Explain the problem or opportunity, the proposed change, "
                "and its expected benefit. "
                "Do not ask the user to choose the type of improvement "
                "unless an important ambiguity genuinely prevents a sound decision. "
                "If the user asks only for a suggestion, do not modify the file. "
                "Every proposed patch requires explicit user approval before it is applied. "
                "You cannot execute arbitrary shell commands. "
                "Never claim a tool action succeeded unless its result confirms it. "
                "Respond in Persian unless the user requests another language."
            ),
        )

        print("\nIlan is ready.")
        print(f"Workspace: {workspace_path}")
        
        available_tools = [
            item["function"]["name"]
            for item in tool_registry.definitions()
        ]
        print(f"Available tools: {', '.join(available_tools)}")

        print("Type 'exit' to stop.\n")

        while True:
            try:
                user_message = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nIlan stopped.")
                break

            if user_message.lower() in {"exit", "quit"}:
                print("Ilan stopped.")
                break

            if not user_message:
                continue

            try:
                answer = agent.run(user_message)
                print(f"\nIlan: {answer}\n")
            except (OpenRouterError, GeminiError, OllamaError, ConnectionError, TimeoutError) as exc:
                print(f"\nIlan: درخواست متوقف شد. خطای ارتباط با {model_provider}:")
                print(exc)
                print("هیچ تلاش مجدد خودکاری انجام نمی‌شود.")
                print("منتظر پیام بعدی شما هستم.\n")

            except Exception as exc:
                print(f"\nRunner error: {type(exc).__name__}: {exc}\n")

    finally:
        try:
            if relay_started:
                relay.stop()
        finally:
            workspace.close()


if __name__ == "__main__":
    main()
