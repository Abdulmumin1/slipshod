from __future__ import annotations

from email.message import EmailMessage
import hashlib
from email.utils import format_datetime, formataddr

from ..plans import EmailPlan


def _quote(q: dict) -> str:
    name, addr = q["from"]
    if q["style"] == "gmail":
        head = f"On {q['sent']:%a, %d %b %Y at %H:%M}, {name} <{addr}> wrote:"
        return head + "\n" + "\n".join("> " + line if line else ">" for line in q["body"].splitlines())
    if q["style"] == "forward":
        return (
            "---------- Forwarded message ---------\n"
            f"From: {name} <{addr}>\nDate: {q['sent']:%a, %d %b %Y at %H:%M}\nSubject: {q['subject']}\n\n{q['body']}"
        )
    return (
        "________________________________\n"
        f"From: {name} <{addr}>\nSent: {q['sent']:%d %B %Y %H:%M}\nSubject: {q['subject']}\n\n{q['body']}"
    )


def email_text(plan: EmailPlan, attachment_sentence: str) -> str:
    paras = [attachment_sentence if p == "{attachments}" else p for p in plan.paragraphs]
    body = "\n\n".join(p for p in paras if p)
    body += "\n\n" + "\n".join(plan.signature)
    for q in plan.quoted:
        body += "\n\n" + _quote(q)
    return body + "\n"


def render_eml(plan: EmailPlan, body: str, attachments: list[tuple[str, bytes, str]]) -> bytes:
    msg = EmailMessage()
    msg["From"] = formataddr(plan.sender)
    msg["To"] = formataddr(plan.to)
    msg["Date"] = format_datetime(plan.sent)
    msg["Subject"] = plan.subject
    digest = hashlib.sha1(f"{plan.sent.isoformat()}|{plan.subject}|{plan.filename}".encode()).hexdigest()[:20]
    msg["Message-ID"] = f"<{digest}@{plan.sender[1].split('@')[1]}>"
    msg.set_content(body)
    for filename, data, mime in attachments:
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    if msg.is_multipart():
        msg.set_boundary(f"===============slipshod{digest}==")
    return bytes(msg)
