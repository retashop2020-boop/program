import json
import sys
import uuid


class AgentLoop:
    def __init__(
        self,
        model_client,
        tool_registry,
        tool_dispatcher,
        system_prompt="You are Ilan, an AI agent working inside an authorized workspace.",
        max_tool_rounds=2,
    ):
        self.model_client = model_client
        self.tool_registry = tool_registry
        self.tool_dispatcher = tool_dispatcher
        self.system_prompt = system_prompt
        self.max_tool_rounds = max_tool_rounds

    def _log(self, request_id, event):
        print(
            f"[Ilan request={request_id}] {event}",
            file=sys.stderr,
            flush=True,
        )

    def run(self, user_message):
        request_id = uuid.uuid4().hex[:8]
        model_call_count = 0

        self._log(request_id, "request_started")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]

        for round_index in range(self.max_tool_rounds + 1):
            tools = (
                self.tool_registry.definitions()
                if round_index < self.max_tool_rounds
                else None
            )

            model_call_count += 1
            self._log(
                request_id,
                f"model_call_started call={model_call_count} "
                f"round={round_index + 1}",
            )

            try:
                response = self.model_client.chat(messages, tools=tools)
            except Exception as exc:
                self._log(
                    request_id,
                    f"model_call_failed call={model_call_count} "
                    f"error={type(exc).__name__}: {exc}",
                )
                self._log(request_id, "request_stopped")
                raise

            choices = response.get("choices") or []
            finish_reason = choices[0].get("finish_reason") if choices else None
            
            self._log(
                request_id,
                f"model_call_succeeded call={model_call_count} finish_reason={finish_reason}",
            )

            if not choices:
                self._log(request_id, "request_failed: no model choices")
                raise RuntimeError("Model returned no choices.")

            assistant_message = choices[0].get("message") or {}
            messages.append(assistant_message)

            tool_calls = assistant_message.get("tool_calls") or []

            if not tool_calls:
                self._log(
                    request_id,
                    f"request_completed model_calls={model_call_count}",
                )
                return assistant_message.get("content") or ""

            if round_index >= self.max_tool_rounds:
                self._log(request_id, "tool_round_limit_reached")
                return (
                    "Ilan reached the tool-call limit "
                    "without producing a final answer."
                )

            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                name = function.get("name")
                arguments = function.get("arguments", "{}")

                try:
                    parsed_arguments = (
                        json.loads(arguments)
                        if isinstance(arguments, str)
                        else arguments
                    )
                    if not isinstance(parsed_arguments, dict):
                        parsed_arguments = {}
                except (TypeError, ValueError):
                    parsed_arguments = {}

                if name in {"list_files", "read_file"}:
                    path = parsed_arguments.get(
                        "path", "." if name == "list_files" else "<missing>"
                    )
                    self._log(
                        request_id,
                        f"tool_started name={name} path={path}",
                    )
                else:
                    self._log(request_id, f"tool_started name={name}")

                try:
                    result = self.tool_dispatcher.execute(name, arguments)
                    tool_result = {"success": True, "result": result}
                    self._log(request_id, f"tool_succeeded name={name}")

                except Exception as exc:
                    tool_result = {
                        "success": False,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                    self._log(
                        request_id,
                        f"tool_failed name={name} "
                        f"error={type(exc).__name__}: {exc}",
                    )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "content": json.dumps(
                        tool_result,
                        ensure_ascii=False,
                        default=str,
                    ),
                })

        self._log(request_id, "request_stopped: tool round limit")
        return "Ilan stopped because the tool-call limit was reached."
