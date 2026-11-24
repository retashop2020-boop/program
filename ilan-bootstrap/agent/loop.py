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
    ):
        self.model_client = model_client
        self.tool_registry = tool_registry
        self.tool_dispatcher = tool_dispatcher
        self.system_prompt = system_prompt

    def _log(self, request_id, event):
        print(
            f"[Ilan request={request_id}] {event}",
            file=sys.stderr,
            flush=True,
        )

    def run(self, user_message):
        request_id = uuid.uuid4().hex[:8]
        self._log(request_id, "request_started")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]

        self._log(request_id, "model_call_started")

        try:
            response = self.model_client.chat(
                messages,
                tools=self.tool_registry.definitions(),
            )
        except Exception as exc:
            self._log(
                request_id,
                f"model_call_failed error={type(exc).__name__}: {exc}",
            )
            self._log(request_id, "request_stopped")
            raise

        choices = response.get("choices") or []

        if not choices:
            self._log(request_id, "request_failed: no model choices")
            raise RuntimeError("Model returned no choices.")

        choice = choices[0]
        assistant_message = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")

        self._log(
            request_id,
            f"model_call_succeeded finish_reason={finish_reason}",
        )

        content = assistant_message.get("content") or ""
        tool_calls = assistant_message.get("tool_calls") or []

        report = []

        if content:
            if tool_calls:
                report.append(f"Model response:\n{content}")
            else:
                report.append(content)

        if tool_calls:
            report.append("Tool execution results:")

            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                name = function.get("name")
                arguments = function.get("arguments", "{}")
                call_id = tool_call.get("id")

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
                    tool_result = {
                        "success": True,
                        "result": result,
                    }
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

                report.append(
                    f"- Tool: {name} | Call ID: {call_id}\n"
                    f"{json.dumps(tool_result, ensure_ascii=False, default=str)}"
                )

        if not report:
            report.append("Model returned an empty response.")

        self._log(
            request_id,
            f"request_completed model_calls=1 tool_calls={len(tool_calls)}",
        )

        return "\n\n".join(report)
