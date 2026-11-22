import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GeminiError(Exception):
    pass


class GeminiClient:
    API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, model=None, timeout=90):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.timeout = timeout

        if not self.api_key:
            raise GeminiError("GEMINI_API_KEY is not set.")

        if not self.model:
            raise GeminiError("GEMINI_MODEL is not set.")

    def _clean_schema(self, schema):
        if isinstance(schema, dict):
            return {
                key: self._clean_schema(value)
                for key, value in schema.items()
                if key != "additionalProperties"
            }

        if isinstance(schema, list):
            return [self._clean_schema(item) for item in schema]

        return schema

    def _convert_tools(self, tools):
        declarations = []

        for tool in tools or []:
            function = tool.get("function") or {}

            declarations.append({
                "name": function["name"],
                "description": function.get("description", ""),
                "parameters": self._clean_schema(
                    function.get("parameters", {
                        "type": "object",
                        "properties": {},
                    })
                ),
            })

        return [{"functionDeclarations": declarations}] if declarations else []

    def _convert_messages(self, messages):
        system_parts = []
        contents = []
        pending_tool_calls = {}

        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "system":
                if content:
                    system_parts.append({"text": str(content)})
                continue

            if role == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": str(content or "")}],
                })
                continue

            if role == "assistant":
                parts = []

                if content:
                    parts.append({"text": str(content)})

                for call in message.get("tool_calls") or []:
                    function = call.get("function") or {}
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                    except json.JSONDecodeError as exc:
                        raise GeminiError(
                            "Invalid JSON in assistant tool-call arguments."
                        ) from exc

                    function_call_part = {
                        "functionCall": {
                            "name": function["name"],
                            "args": arguments,
                        }
                    }

                    if call.get("thought_signature") is not None:
                        function_call_part["thoughtSignature"] = call["thought_signature"]

                    parts.append(function_call_part)

                    pending_tool_calls[call.get("id")] = function["name"]

                if parts:
                    contents.append({"role": "model", "parts": parts})
                continue

            if role == "tool":
                tool_call_id = message.get("tool_call_id")
                name = pending_tool_calls.pop(tool_call_id, None)

                if not name:
                    raise GeminiError(
                        f"Unknown tool_call_id in tool message: {tool_call_id}"
                    )

                try:
                    result = json.loads(content or "{}")
                except json.JSONDecodeError:
                    result = {"result": content}

                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": name,
                            "response": result,
                        }
                    }],
                })

        return system_parts, contents

    def chat(self, messages, tools=None):
        system_parts, contents = self._convert_messages(messages)

        payload = {"contents": contents}

        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        converted_tools = self._convert_tools(tools)
        if converted_tools:
            payload["tools"] = converted_tools

        url = f"{self.API_BASE}/{self.model}:generateContent"

        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))

        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise GeminiError(
                f"Gemini HTTP error {exc.code}: {details}"
            ) from exc

        except URLError as exc:
            raise GeminiError(
                f"Could not connect to Gemini: {exc.reason}"
            ) from exc

        except json.JSONDecodeError as exc:
            raise GeminiError("Gemini returned invalid JSON.") from exc

        candidates = data.get("candidates") or []
        if not candidates:
            raise GeminiError(
                f"Gemini returned no candidates: {data.get('promptFeedback', {})}"
            )

        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []

        text_parts = []
        tool_calls = []

        for index, part in enumerate(parts):
            if part.get("text"):
                text_parts.append(part["text"])

            function_call = part.get("functionCall")
            if function_call:
                tool_call = {
                    "id": f"gemini_call_{index}",
                    "type": "function",
                    "function": {
                        "name": function_call["name"],
                        "arguments": json.dumps(
                            function_call.get("args") or {},
                            ensure_ascii=False,
                        ),
                    },
                }

                if part.get("thoughtSignature") is not None:
                    tool_call["thought_signature"] = part["thoughtSignature"]

                tool_calls.append(tool_call)

        assistant_message = {
            "role": "assistant",
            "content": "".join(text_parts) or None,
        }

        if tool_calls:
            assistant_message["tool_calls"] = tool_calls

        return {
            "choices": [{
                "message": assistant_message,
                "finish_reason": candidate.get("finishReason"),
            }]
        }
