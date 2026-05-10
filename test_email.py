"""Verify Gmail SMTP settings by sending a real test email.

Run once before the first real booking:
    python test_email.py

Reads NOTIFY_EMAIL_FROM / NOTIFY_EMAIL_PASSWORD / NOTIFY_EMAIL from .env.
"""

from __future__ import annotations

import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    sender = os.getenv("NOTIFY_EMAIL_FROM", "").strip()
    password = os.getenv("NOTIFY_EMAIL_PASSWORD", "").strip()
    recipient = os.getenv("NOTIFY_EMAIL", "").strip()

    if not (sender and password and recipient):
        print("FAIL: NOTIFY_EMAIL_FROM / NOTIFY_EMAIL_PASSWORD / NOTIFY_EMAIL must be set in .env",
              file=sys.stderr)
        return 1

    subject = "🎾 PPTC Bot — Email Test"
    body = (
        f"This is a test email from the PPTC booking system.\n\n"
        f"Sent at: {datetime.now().isoformat(timespec='seconds')}\n"
        f"From:    {sender}\n"
        f"To:      {recipient}\n\n"
        f"If you received this, Gmail SMTP is configured correctly."
    )
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
            s.login(sender, password)
            s.sendmail(sender, [recipient], msg.as_string())
    except Exception as exc:
        print(f"FAIL: SMTP error — {exc}", file=sys.stderr)
        return 2

    print(f"OK: test email sent to {recipient}. Check your inbox.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
