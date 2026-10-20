import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from investiq.core.config import Settings


class Mailer(Protocol):
    async def send(self, recipient: str, purpose: str, token: str) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send(self, recipient: str, purpose: str, token: str) -> None:
        config = self.settings
        route = "verify-email" if purpose == "verification" else "reset-password"
        # Fragment tokens stay out of HTTP access logs and Referer headers.
        link = f"{config.frontend_url}/#/{route}?token={token}"
        message = EmailMessage()
        message["From"] = config.mail_from
        message["To"] = recipient
        message["Subject"] = (
            "Verify your InvestIQ email"
            if purpose == "verification"
            else ("Reset your InvestIQ password")
        )
        message.set_content(
            f"Open this link to continue:\n{link}\n\n"
            "This link expires and can be used once. If you did not request it, ignore this email."
        )

        def deliver() -> None:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10) as smtp:
                if config.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if config.smtp_username:
                    smtp.login(config.smtp_username, config.smtp_password.get_secret_value())
                smtp.send_message(message)

        await asyncio.to_thread(deliver)
