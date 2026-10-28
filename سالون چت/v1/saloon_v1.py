#!/usr/bin/env python3
"""Saloon Chat v1 — dynamic multi-agent discussion prototype.

Requirements: Python 3.10+; standard library only.
API key: OPENROUTER_API_KEY environment variable, or hidden prompt.
Run: python saloon_v1.py
"""
from __future__ import annotations

import getpass
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

API_URL = "https://openrouter.ai/api/v1/chat/completions"
CONFIG_PATH = Path("saloon_members.json")
LOG_DIR = Path("saloon_results")
MAX_HISTORY_MESSAGES = 24


@dataclass
class Member:
    name: str
    model: str
    role: str
    enabled: bool = True
    max_tokens: int = 900
    temperature: float = 0.7


DEFAULT_MEMBERS = [
    Member(
        name="Skeptic",
        model="openrouter/free",
        role="Be a rigorous skeptic. Identify assumptions, counterexamples, and uncertainty. Do not disagree merely for performance.",
    ),
    Member(
        name="Analyst",
        model="openrouter/free",
        role="Analyze the issue independently. Separate facts, assumptions, inferences, and open questions. Do not imitate other members.",
    ),
]


def load_members() -> list[Member]:
    if not CONFIG_PATH.exists():
        save_members(DEFAULT_MEMBERS)
        print(f"Created starter configuration: {CONFIG_PATH}")
        return [Member(**asdict(m)) for m in DEFAULT_MEMBERS]
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        members = [Member(**item) for item in raw]
        if not members:
            raise ValueError("the member list is empty")
        return members
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError(f"Cannot read {CONFIG_PATH}: {exc}") from exc


def save_members(members: list[Member]) -> None:
    CONFIG_PATH.write_text(
        json.dumps([asdict(m) for m in members], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def prompt_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        key = getpass.getpass("OpenRouter API key (input hidden): ").strip()
    if not key:
        raise RuntimeError("No API key provided.")
    return key


def call_model(api_key: str, member: Member, messages: list[dict[str, str]]) -> str:
    payload = {
        "model": member.model,
        "messages": [{"role": "system", "content": member.role}, *messages],
        "temperature": member.temperature,
        "max_tokens": member.max_tokens,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost/saloon-chat",
            "X-Title": "Saloon Chat v1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"Provider returned no choices: {json.dumps(data)[:800]}")
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "\n".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    content = str(content or "").strip()
    finish_reason = choice.get("finish_reason", "unknown")
    if not content:
        raise RuntimeError(f"Empty response (finish_reason={finish_reason}).")
    if finish_reason == "length":
        content += "\n\n[WARNING: response may be truncated because max_tokens was reached.]"
    return content


def choose_members(members: list[Member]) -> None:
    while True:
        print("\nMembers:")
        for i, m in enumerate(members, 1):
            status = "ON" if m.enabled else "OFF"
            print(f" {i}. [{status}] {m.name} — {m.model}")
            print(f"    Role: {m.role}")
        print("\nCommands: add | edit N | toggle N | remove N | save | back")
        cmd = input("members> ").strip()
        if cmd == "back":
            return
        if cmd == "save":
            save_members(members)
            print(f"Saved to {CONFIG_PATH}.")
        elif cmd == "add":
            name = input("Display name: ").strip()
            model = input("OpenRouter model ID (e.g. openrouter/free): ").strip()
            role = input("Role / instructions: ").strip()
            if name and model and role:
                members.append(Member(name=name, model=model, role=role))
                print(f"Added {name}.")
            else:
                print("Name, model, and role are required.")
        else:
            match = re.fullmatch(r"(edit|toggle|remove)\s+(\d+)", cmd)
            if not match:
                print("Unknown command.")
                continue
            action, num = match.group(1), int(match.group(2))
            if not 1 <= num <= len(members):
                print("No member with that number.")
                continue
            idx = num - 1
            if action == "toggle":
                members[idx].enabled = not members[idx].enabled
            elif action == "remove":
                removed = members.pop(idx)
                print(f"Removed {removed.name}.")
            else:
                m = members[idx]
                value = input(f"Name [{m.name}]: ").strip()
                if value:
                    m.name = value
                value = input(f"Model [{m.model}]: ").strip()
                if value:
                    m.model = value
                value = input("Role (blank keeps current): ").strip()
                if value:
                    m.role = value
                value = input(f"Max tokens [{m.max_tokens}]: ").strip()
                if value:
                    try:
                        m.max_tokens = max(100, min(8000, int(value)))
                    except ValueError:
                        print("Invalid token limit; kept previous value.")
                value = input(f"Temperature [{m.temperature}]: ").strip()
                if value:
                    try:
                        m.temperature = max(0.0, min(2.0, float(value)))
                    except ValueError:
                        print("Invalid temperature; kept previous value.")
        if not members:
            print("Warning: no members remain. Add one before starting a discussion.")


def history_for(member_name: str, transcript: list[dict[str, Any]]) -> list[dict[str, str]]:
    # Keep a bounded, readable context window; preserve who said each message.
    selected = transcript[-MAX_HISTORY_MESSAGES:]
    messages: list[dict[str, str]] = []
    for item in selected:
        if item["kind"] == "user":
            messages.append({"role": "user", "content": item["text"]})
        elif item["kind"] == "reply":
            messages.append({
                "role": "assistant",
                "content": f"[{item['member']}]: {item['text']}",
            })
    messages.append({
        "role": "user",
        "content": (
            f"You are speaking as {member_name} in an ongoing group discussion. "
            "Respond to the latest user message or relevant prior claims. "
            "Refer to names or quote a short claim when useful. Preserve justified disagreement. "
            "Do not repeat the entire discussion."
        ),
    })
    return messages


def save_transcript(topic: str, transcript: list[dict[str, Any]]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"saloon_{stamp}.md"
    lines = [f"# Saloon Chat — {topic}", ""]
    for item in transcript:
        if item["kind"] == "user":
            lines.extend(["## User", item["text"], ""])
        elif item["kind"] == "reply":
            lines.extend([f"## {item['member']} ({item['model']})", item["text"], ""])
        else:
            lines.extend([f"## System — {item.get('member', 'event')}", item["text"], ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def discussion(members: list[Member], api_key: str) -> None:
    active = [m for m in members if m.enabled]
    if not active:
        print("No enabled members. Use 'members' from the main menu first.")
        return
    topic = input("Topic / opening message: ").strip()
    if not topic:
        print("No topic entered.")
        return
    transcript: list[dict[str, Any]] = [{"kind": "user", "text": topic}]
    print("\nDiscussion started. Commands: /all, /to NAME, /members, /save, /quit")
    print("Any ordinary text you enter becomes a new user message and interrupts the current flow.")
    while True:
        try:
            raw = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raw = "/quit"
        if not raw:
            continue
        if raw == "/quit":
            break
        if raw == "/save":
            path = save_transcript(topic, transcript)
            print(f"Saved: {path}")
            continue
        if raw == "/members":
            for m in members:
                print(f"{'[ON]' if m.enabled else '[OFF]'} {m.name}: {m.model}")
            continue

        if raw.startswith("/to "):
            target = raw[4:].strip().casefold()
            chosen = [m for m in active if m.name.casefold() == target]
            if not chosen:
                print("No enabled member with that exact name. Use /members.")
                continue
            user_text = f"@{chosen[0].name}: respond to this message.\n{input('message> ').strip()}"
        elif raw == "/all":
            user_text = input("message to all> ").strip()
            chosen = active[:]
        else:
            user_text = raw
            chosen = active[:]
        if not user_text:
            continue
        transcript.append({"kind": "user", "text": user_text})
        # A user message is one event. Each selected member gets one response;
        # another round happens only after the user sends another message.
        for member in chosen:
            print(f"\n{member.name} [{member.model}] is thinking...")
            try:
                answer = call_model(api_key, member, history_for(member.name, transcript[:-1] + [{"kind": "user", "text": user_text}]))
                print(f"\n{member.name}> {answer}")
                transcript.append({
                    "kind": "reply", "member": member.name, "model": member.model, "text": answer
                })
            except RuntimeError as exc:
                message = f"Model call failed; other members can still respond. {exc}"
                print(f"\n[ERROR: {member.name}] {message}")
                transcript.append({"kind": "error", "member": member.name, "text": message})
        path = save_transcript(topic, transcript)
        print(f"\n[Transcript auto-saved: {path}]")


def main() -> None:
    print("=" * 62)
    print(" SALOON CHAT v1 — dynamic multi-agent discussion")
    print("=" * 62)
    print("Model availability and free-tier limits depend on OpenRouter/providers.")
    try:
        members = load_members()
        while True:
            command = input("\nMenu: discuss | members | quit > ").strip().casefold()
            if command in {"quit", "q", "exit"}:
                save_members(members)
                break
            if command == "members":
                choose_members(members)
                save_members(members)
            elif command == "discuss":
                try:
                    key = prompt_api_key()
                    discussion(members, key)
                except RuntimeError as exc:
                    print(f"Could not start discussion: {exc}")
            elif command:
                print("Use discuss, members, or quit.")
    except (RuntimeError, OSError) as exc:
        print(f"Startup error: {exc}")


if __name__ == "__main__":
    main()
