"""
通过 SMTP 发送每日推送邮件。
- 默认 163 邮箱（SSL 465）
- HTML 正文 + 附件（HTML + Markdown）
"""
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def _attach_file(msg, file_path):
    """将文件作为附件添加到邮件。"""
    p = Path(file_path)
    if not p.exists():
        return
    subtype = "html" if p.suffix.lower() == ".html" else "markdown"
    with open(p, "rb") as f:
        att = MIMEApplication(f.read(), _subtype=subtype)
        att.add_header("Content-Disposition", "attachment", filename=p.name)
        msg.attach(att)


def send_email(cfg, subject, html_body, html_file_path=None, md_file_path=None):
    """发送邮件。"""
    email_cfg = cfg["email"]
    sender = email_cfg["sender"]
    receivers = email_cfg["receivers"]
    auth_code = email_cfg["auth_code"]
    smtp_host = email_cfg["smtp_host"]
    smtp_port = email_cfg.get("smtp_port", 465)
    use_ssl = email_cfg.get("use_ssl", True)

    if not auth_code or "REPLACE" in str(auth_code):
        raise ValueError("请先在 config/config.json 中填入邮箱授权码 (auth_code)")

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(receivers)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    _attach_file(msg, html_file_path)
    _attach_file(msg, md_file_path)

    print(f"[email] 连接 SMTP {smtp_host}:{smtp_port} (SSL={use_ssl})")
    if use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=30) as server:
            server.login(sender, auth_code)
            server.sendmail(sender, receivers, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(sender, auth_code)
            server.sendmail(sender, receivers, msg.as_string())

    print(f"[email] 已发送: {', '.join(receivers)}")