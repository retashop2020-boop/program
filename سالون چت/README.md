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
