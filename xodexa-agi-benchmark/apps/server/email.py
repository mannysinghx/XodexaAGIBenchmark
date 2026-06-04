"""
apps.server.email
===================
Pluggable transactional email. Default transport is SMTP over SSL to privateemail.com
(``info@xodexabenchmark.com``); when SMTP credentials are absent (local dev) it falls
back to logging the message + link to the console so the verification flow still works.

Only stdlib ``smtplib`` + ``ssl`` + ``email`` — no extra dependency.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from apps.server.config import get_settings

_settings = get_settings()


def _send(to_email: str, subject: str, text: str, html: str | None = None) -> bool:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((_settings.mail_from_name, _settings.mail_from))
    msg["To"] = to_email
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    if not _settings.email_configured:
        # Dev fallback — make the flow usable with no SMTP creds.
        print("\n" + "=" * 64)
        print("  [DEV EMAIL — SMTP not configured; would send]")
        print(f"  To     : {to_email}")
        print(f"  Subject: {subject}")
        print("  " + "-" * 60)
        for line in text.splitlines():
            print("  " + line)
        print("=" * 64 + "\n")
        return False

    ctx = ssl.create_default_context()
    timeout = 20  # never hang the request on a slow/unreachable SMTP server
    try:
        if _settings.smtp_port == 465:  # implicit SSL (privateemail.com default)
            with smtplib.SMTP_SSL(_settings.smtp_host, _settings.smtp_port,
                                  context=ctx, timeout=timeout) as s:
                s.login(_settings.smtp_user, _settings.smtp_password)
                s.send_message(msg)
        else:  # 587 STARTTLS
            with smtplib.SMTP(_settings.smtp_host, _settings.smtp_port,
                              timeout=timeout) as s:
                s.starttls(context=ctx)
                s.login(_settings.smtp_user, _settings.smtp_password)
                s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001 — never let email break registration
        # Don't 500 the signup; the account is created and the link is recoverable here
        # (and via /api/auth/resend). Common cause: wrong SMTP_PASSWORD.
        print("\n" + "=" * 64)
        print(f"  [EMAIL SEND FAILED: {type(e).__name__}: {e}]")
        print(f"  To     : {to_email}")
        print(f"  Subject: {subject}")
        print("  Verification link (deliver manually / fix SMTP_PASSWORD):")
        for line in text.splitlines():
            if line.strip().startswith("Verify:") or "http" in line:
                print("  " + line.strip())
        print("=" * 64 + "\n")
        return False


def send_verification(to_email: str, username: str, link: str) -> bool:
    subject = "Verify your Xodexa AI Benchmark account"
    text = (
        f"Hi {username},\n\n"
        "Confirm your email to activate your Xodexa AI Benchmark account and start "
        "running real benchmarks against your own models.\n\n"
        f"Verify: {link}\n\n"
        f"This link expires in {_settings.verification_ttl_hours} hours. "
        "If you didn't sign up, you can ignore this email.\n\n"
        "— Xodexa AI Benchmark"
    )
    html = (
        f"<p>Hi {username},</p>"
        "<p>Confirm your email to activate your <b>Xodexa AI Benchmark</b> account and "
        "start running real benchmarks against your own models.</p>"
        f'<p><a href="{link}" style="background:#2563eb;color:#fff;padding:10px 18px;'
        'border-radius:8px;text-decoration:none;font-weight:600">Verify my email</a></p>'
        f'<p style="color:#5a6b85;font-size:13px">Or paste this link: {link}<br>'
        f"This link expires in {_settings.verification_ttl_hours} hours.</p>"
    )
    return _send(to_email, subject, text, html)
