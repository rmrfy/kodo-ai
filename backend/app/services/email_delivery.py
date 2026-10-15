"""Optional SMTP delivery; callers must surface a not-sent result when unconfigured."""
from email.message import EmailMessage
import smtplib
import ssl
from urllib.parse import quote

from .. import config


def email_delivery_configured() -> bool:
    return bool(config.EMAIL_FROM and config.SMTP_HOST)


def send_email(to_address: str, subject: str, body: str) -> bool:
    if not email_delivery_configured():
        return False
    message = EmailMessage()
    message["From"] = config.EMAIL_FROM
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context, timeout=20) as smtp:
            _login_if_configured(smtp)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.ehlo()
            if config.SMTP_STARTTLS:
                smtp.starttls(context=context)
                smtp.ehlo()
            _login_if_configured(smtp)
            smtp.send_message(message)
    return True


def _login_if_configured(smtp) -> None:
    if config.SMTP_USERNAME:
        smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)


def send_verification_email(to_address: str, token: str) -> bool:
    verify_url = f"{config.FRONTEND_ORIGIN.rstrip('/')}/verify-email#token={quote(token, safe='')}"
    return send_email(
        to_address,
        "Verify your email for kodai",
        "Use this one-time link to verify your email address and continue to kodai:\n\n"
        f"{verify_url}\n\nThis link expires in 30 minutes. If you did not request this, ignore this email.",
    )


def send_organization_invite(to_address: str, organization_name: str, inviter: str, expires_at, invite_id: int) -> bool:
    invite_url = f"{config.FRONTEND_ORIGIN.rstrip('/')}/login"
    return send_email(
        to_address,
        f"Invitation to join {organization_name} on kodai",
        f"{inviter} invited you to join {organization_name} on kodai.\n\n"
        "Sign in or create a kodai account using this invited email address. You will need to verify control of the address before joining:\n\n"
        f"{invite_url}\n\nInvitation expires {expires_at:%Y-%m-%d %H:%M UTC}.",
    )
