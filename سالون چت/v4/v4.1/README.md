# سالون چت

مخزن نسخه‌بندی کدهای تولیدی پروژهٔ سالون چت.

## نسخه‌ها

- `v1/saloon_web_v1.py` — نسخهٔ مبنای رابط وب، کپی‌شده از مخزن Tempo بدون تغییر.
- `v1/saloon_v1.py` — نسخهٔ مبنای CLI، کپی‌شده از مخزن Tempo بدون تغییر.
- `v2/saloon_web_v2.py` — اصلاح مدیریت قطع اتصال، نمایش زمان انتظار، و حذف چاپ متن خام reasoning در لاگ تشخیصی.

## اجرا

در پوشهٔ نسخهٔ موردنظر، با Python 3.10 یا جدیدتر:

```powershell
python saloon_web_v2.py
```

برنامه به کلید OpenRouter نیاز دارد؛ می‌توان آن را در متغیر محیطی `OPENROUTER_API_KEY` قرار داد یا هنگام اجرا در ترمینال وارد کرد. رابط محلی روی `http://127.0.0.1:8765` باز می‌شود.

## نکته

نمایش زمان انتظار فقط وضعیت رابط را به‌روزرسانی می‌کند؛ درخواست مدل سمت سرور همچنان ممکن است تا پایان timeout ادامه یابد. این تغییر، قابلیت لغو واقعی درخواست مدل نیست.


## v3 — bounded reasoning test

File: `v3/saloon_web_v3.py`

- Keeps the v2 wait timer and disconnect handling.
- For a controlled test, set Skeptic's model in the member editor to `dots-studio/dots-3-note-preview:free`.
- When that exact model is selected, the request adds OpenRouter reasoning controls: `max_tokens: 256` for reasoning and `exclude: true` so reasoning is not included as a visible response field.
- The ordinary answer budget remains the member's configured `max_tokens` (default 1200).
- This is an experiment, not a verified fix. The model's behavior and provider acceptance must be tested at runtime.


## v4 — recipient-aware routing

File: `v4/saloon_web_v4.py`

- Without an explicit recipient, all enabled members respond (existing group behavior).
- `@Analyst` or `@Skeptic` routes the message only to the named member.
- Multiple explicit mentions route only to those members.
- Names containing spaces can be addressed as `@"Red Team"`.
- Unknown, ambiguous, and disabled recipients return an explicit error; the program does not silently fall back to the group.
- Basic routing tests: `python -m unittest test_recipient_routing.py` from the `v4` directory.

V4 is preserved on branch `v4-recipient-routing`; V1–V3 and `main` remain unchanged.

## v4.1 — network and member-failure resilience

Branch: `v4.1-network-resilience` (based on V4; V4 remains unchanged)

- Converts raw connection-reset, other OS-level network errors, and HTTP protocol read errors from `call_model` into a member-level `RuntimeError`.
- Isolates each member call: an exception from one member is recorded as that member's error and does not stop later members.
- Preserves successful replies and member errors in the same event list, then saves the completed turn transcript.
- Adds focused tests for a first-member connection reset, preserving an earlier successful reply, passing prior member events into later context, and normalizing a raw connection reset.
- Does not change recipient routing, model configuration, or the interaction design.

Run tests from the `v4` directory:

```powershell
python -m unittest test_recipient_routing.py test_resilience.py
```

The V4.1 tests have been added but have not yet been executed in a Python runtime.
