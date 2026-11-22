import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenRouterError(Exception):
    pass


class OpenRouterClient:
    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, model=None, timeout=90):
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        self.model = model or os.environ.get("OPENROUTER_MODEL")
        self.timeout = timeout

        if not self.api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set.")

        if not self.model:
            raise OpenRouterError("OPENROUTER_MODEL is not set.")

    def chat(self, messages, tools=None):
        payload = {
            "model": self.model,
            "messages": messages,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "Ilan Bootstrap",
        }

        site_url = os.environ.get("OPENROUTER_SITE_URL")
        if site_url:
            headers["HTTP-Referer"] = site_url

        request = Request(
            self.API_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))

        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise OpenRouterError(
                f"OpenRouter HTTP error {exc.code}: {details}"
            ) from exc

        except URLError as exc:
            raise OpenRouterError(
                f"Could not connect to OpenRouter: {exc.reason}"
            ) from exc

        except json.JSONDecodeError as exc:
            raise OpenRouterError(
                "OpenRouter returned invalid JSON."
            ) from exc
