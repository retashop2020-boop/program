
import json
import os
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaError(Exception):
    """Base exception for Ollama client errors."""


class OllamaAgentClient:
    API_PATH = "/api/chat"

    def __init__(
        self,
        model=None,
        base_url=None,
        timeout=None,
        thinking_mode=None,
    ):
        self.model = (
            model
            or os.environ.get(
                "ILAN_OLLAMA_MODEL",
                "gpt-oss-20b-local:latest",
            )
        )

        self.base_url = (
            base_url
            or os.environ.get(
                "ILAN_OLLAMA_URL",
                "http://172.24.32.1:18765",
            )
        ).rstrip("/")

        self.relay_token = os.environ.get("ILAN_RELAY_TOKEN")

        self.timeout = (
            timeout
            if timeout is not None
            else int(os.environ.get("ILAN_OLLAMA_TIMEOUT", "2000"))
        )

        self.thinking_mode = (
            thinking_mode
            or os.environ.get("ILAN_THINKING_MODE", "auto")
        ).lower()

        if self.thinking_mode not in ("auto", "on", "off"):
            raise ValueError(
                "ILAN_THINKING_MODE must be auto, on, or off"
            )

        if not self.model:
            raise ValueError("Ollama model is not configured")

        if self.timeout <= 0:
            raise ValueError("Ollama timeout must be positive")

    @staticmethod
    def _parse_arguments(arguments):
        if arguments is None:
            return {}

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError as exc:
                raise OllamaError(
                    "Invalid JSON in tool-call arguments"
                ) from exc

        if not isinstance(arguments, dict):
            raise OllamaError(
                "Tool-call arguments must be a JSON object"
            )

        return arguments

    def _prepare_messages(self, messages):
        """Convert OpenAI-style tool history to Ollama message format."""
        if not isinstance(messages, list):
            raise OllamaError("Messages must be a list")

        prepared = []
        tool_names_by_id = {}

        for message in messages:
            if not isinstance(message, dict):
                raise OllamaError("Every message must be an object")

            item = dict(message)
            role = item.get("role")

            # Ollama expects message content to be a string.
            if item.get("content") is None:
                item["content"] = ""

            if not isinstance(item.get("content"), str):
                raise OllamaError(
                    "Message content must be a string"
                )

            if role == "assistant":
                raw_calls = item.get("tool_calls") or []

                if not isinstance(raw_calls, list):
                    raise OllamaError(
                        "Assistant tool_calls must be a list"
                    )

                converted_calls = []

                for call in raw_calls:
                    if not isinstance(call, dict):
                        raise OllamaError(
                            "Each tool call must be an object"
                        )

                    converted_call = dict(call)
                    function = dict(call.get("function") or {})

                    name = function.get("name")
                    if not isinstance(name, str) or not name:
                        raise OllamaError(
                            "Tool call is missing a valid function name"
                        )

                    function["arguments"] = self._parse_arguments(
                        function.get("arguments", {})
                    )

                    converted_call["function"] = function
                    converted_calls.append(converted_call)

                    call_id = call.get("id")
                    if call_id is not None:
                        tool_names_by_id[call_id] = name

                if converted_calls:
                    item["tool_calls"] = converted_calls

            elif role == "tool":
                # AgentLoop supplies tool_call_id but not tool_name.
                # Recover the name from the preceding assistant message.
                call_id = item.get("tool_call_id")
                tool_name = item.get("tool_name")

                if not tool_name and call_id is not None:
                    tool_name = tool_names_by_id.get(call_id)

                if not isinstance(tool_name, str) or not tool_name:
                    raise OllamaError(
                        "Could not determine tool_name for tool result"
                    )

                item["tool_name"] = tool_name

            prepared.append(item)

        return prepared

    def _normalize_tool_calls(self, raw_tool_calls):
        if raw_tool_calls is None:
            return []

        if not isinstance(raw_tool_calls, list):
            raise OllamaError(
                "Ollama tool_calls must be a list"
            )

        normalized = []

        for index, call in enumerate(raw_tool_calls):
            if not isinstance(call, dict):
                raise OllamaError(
                    "Ollama returned an invalid tool call"
                )

            function = call.get("function")
            if not isinstance(function, dict):
                raise OllamaError(
                    "Ollama tool call has no valid function object"
                )

            name = function.get("name")
            if not isinstance(name, str) or not name:
                raise OllamaError(
                    "Ollama tool call has no valid function name"
                )

            arguments = self._parse_arguments(
                function.get("arguments", {})
            )

            call_id = call.get("id")
            if not isinstance(call_id, str) or not call_id:
                call_id = f"ollama_call_{index}"

            normalized.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(
                        arguments,
                        ensure_ascii=False,
                    ),
                },
            })

        return normalized

    def chat(self, messages, tools=None):
        payload = {
            "model": self.model,
            "messages": self._prepare_messages(messages),
            "stream": False,
        }

        if tools:
            payload["tools"] = tools

        # In auto mode, omit "think" and let Ollama use the model default.
        if self.thinking_mode == "on":
            payload["think"] = True
        elif self.thinking_mode == "off":
            payload["think"] = False

        url = self.base_url + self.API_PATH

        headers = {
            "Content-Type": "application/json",
        }
        if self.relay_token:
            headers["X-Relay-Token"] = self.relay_token

        request = Request(
            url,
            data=json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        started = time.monotonic()

        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw_response = response.read().decode("utf-8")

            result = json.loads(raw_response)

        except HTTPError as exc:
            details = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            raise OllamaError(
                f"Ollama HTTP {exc.code}: {details}"
            ) from exc

        except (TimeoutError, socket.timeout) as exc:
            raise TimeoutError(
                f"Ollama request timed out after "
                f"{self.timeout} seconds"
            ) from exc

        except URLError as exc:
            if isinstance(
                exc.reason,
                (TimeoutError, socket.timeout),
            ):
                raise TimeoutError(
                    f"Ollama request timed out after "
                    f"{self.timeout} seconds"
                ) from exc

            raise ConnectionError(
                f"Could not connect to Ollama at "
                f"{self.base_url}: {exc.reason}"
            ) from exc

        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OllamaError(
                "Ollama returned invalid JSON or text encoding"
            ) from exc

        elapsed = time.monotonic() - started

        if not isinstance(result, dict):
            raise OllamaError(
                "Invalid Ollama response format"
            )

        message = result.get("message")

        if not isinstance(message, dict):
            raise OllamaError(
                "Ollama response does not contain a valid message"
            )

        role = message.get("role", "assistant")
        if role != "assistant":
            raise OllamaError(
                "Ollama response message role is not assistant"
            )

        content = message.get("content")
        if content is None:
            content = ""

        if not isinstance(content, str):
            raise OllamaError(
                "Ollama response content must be a string"
            )

        tool_calls = self._normalize_tool_calls(
            message.get("tool_calls")
        )

        normalized_message = {
            "role": "assistant",
            "content": content,
        }

        if tool_calls:
            normalized_message["tool_calls"] = tool_calls
            finish_reason = "tool_calls"
        else:
            # Preserve Ollama's actual completion reason when available.
            done_reason = result.get("done_reason")

            finish_reason = (
                done_reason
                if isinstance(done_reason, str) and done_reason
                else "stop"
            )

        response_data = {
            "choices": [
                {
                    "index": 0,
                    "message": normalized_message,
                    "finish_reason": finish_reason,
                }
            ],
            "model": result.get("model", self.model),
        }

        print(
            f"Ollama response completed in {elapsed:.1f} seconds."
        )

        return response_data
