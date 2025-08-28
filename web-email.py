import imaplib, smtplib, email, os, re
from email.message import EmailMessage
from patchright.sync_api import sync_playwright
from patchright._impl._errors import TimeoutError as PyTimeoutError
from patchright._impl._errors import Error as PyError
from urllib.parse import urlparse, urlunparse

# ==== CONFIG ====
from config import (
    IMAP_SERVER, SMTP_SERVER, SMTP_PORT,
    EMAIL_ACCOUNT, EMAIL_PASSWORD,
    CHECK_FOLDER, VALID_RECIPIENT, WHITELIST,
    WEB_PAGE_EXTENSIONS, MAX_EMAIL_SIZE
)

# --- EMAIL FETCH ---
def fetch_latest_email():
    """Fetch newest unread email sent to VALID_RECIPIENT, mark as read, return sender, body, UID."""
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
    mail.select(CHECK_FOLDER)

    # Use UID search for consistency
    status, data = mail.uid('search', None, 'UNSEEN')
    if status != "OK":
        mail.logout()
        return None, None, None

    email_uids = data[0].split()
    if not email_uids:
        mail.logout()
        return None, None, None

    # Iterate from newest to oldest
    for uid in email_uids[::-1]:
        status, msg_data = mail.uid('fetch', uid, "(RFC822)")
        if status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        recipient = email.utils.parseaddr(msg["To"])[1]
        if recipient.lower() != VALID_RECIPIENT.lower():
            continue

        sender = email.utils.parseaddr(msg["From"])[1]

        # Whitelist check
        if sender.lower() not in [addr.lower() for addr in WHITELIST]:
            print(f"Rejected email from {sender} (not in whitelist)")
            continue

        # Extract body text
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        # Mark as read using UID
        mail.uid('STORE', uid, '+FLAGS', '\\Seen')

        mail.logout()
        return sender, body.strip(), uid  # Return UID for deletion/trash

    mail.logout()
    return None, None, None

# --- PARSING ---
def is_script(body):
    return body.strip().upper().startswith("SCRIPT:")

def parse_script(body):
    lines = body.splitlines()
    return [line.strip() for line in lines if line.strip() and not line.upper().startswith("SCRIPT:")]

def parse_queries(body):
    return [line.strip() for line in body.splitlines() if line.strip()]

def strip_filename(url):
    parsed = urlparse(url)
    base_path = os.path.dirname(parsed.path) + "/"  # keep trailing slash
    return urlunparse((parsed.scheme, parsed.netloc, base_path, "", "", ""))

# --- PDF GENERATION ---
def make_pdf(query, filename="results.pdf", who="profile"):
    if query.startswith("http://") or query.startswith("https://"):
        url = query.strip()
    elif re.match(r"^[\w.-]+\.[a-z]{2,}", query):
        url = "http://" + query.strip()
    else:
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=os.path.join(os.getcwd(), who),   # persistent profile dir
            channel="chrome",                        # use system Chrome instead of bundled Chromium
            headless=False,                          # show the browser
            no_viewport=True,                        # use OS window size instead of Playwright's default
        )

        page = context.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.emulate_media(media="screen")
        page.pdf(path=filename, width="1920px", height="1080px", print_background=True)
        context.close()
    return filename

def download_via_browser(url, who):
    os.makedirs("downloads", exist_ok=True)
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=os.path.join(os.getcwd(), who),   # persistent profile dir
                channel="chrome",                        # use system Chrome instead of bundled Chromium
                headless=False,                          # show the browser
                no_viewport=True,                        # use OS window size instead of Playwright's default
                accept_downloads=True,
            )
            page = context.new_page()
            page.goto(strip_filename(url), wait_until="domcontentloaded")

            try:
                page.evaluate(f"""
                    const a = document.createElement('a');
                    a.href = '{url}';
                    a.download = '';
                    document.body.appendChild(a);
                    a.click();
                """)
            except PyError:
                print("Download Failed Trying Different Method")

            # Wait for the download event
            with page.expect_download(timeout=5000) as download_info:
                pass
            download = download_info.value

            save_path = os.path.join("downloads", download.suggested_filename)
            download.save_as(save_path)

            context.close()
            return save_path
    except PyTimeoutError:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=os.path.join(os.getcwd(), who),   # persistent profile dir
                channel="chrome",                        # use system Chrome instead of bundled Chromium
                headless=False,                          # show the browser
                no_viewport=True,                        # use OS window size instead of Playwright's default
                accept_downloads=True,
            )
            page = context.new_page()
            page.goto(url)
            # Trigger download with a temporary <a> tag
            page.evaluate(f"""
                const a = document.createElement('a');
                a.href = '{url}';
                a.download = '';
                document.body.appendChild(a);
                a.click();
            """)

            # Wait for the download event
            with page.expect_download() as download_info:
                pass  # The click triggers it

            download = download_info.value
            save_path = os.path.join("downloads", download.suggested_filename)
            download.save_as(save_path)

            context.close()
            return save_path

# --- SCRIPT PROCESSING ---
def process_navigation_commands(commands, default_pdf="output.pdf", who="profile"):
    results = []  # list of (desc, filename) for sending back

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=os.path.join(os.getcwd(), who),
            channel="chrome",
            headless=False,
            no_viewport=True,
        )
        page = context.new_page()

        for line in commands:
            parts = line.strip().split(" ", 2)
            if not parts:
                continue
            cmd = parts[0].lower()

            try:
                if cmd == "go":
                    url = parts[1]
                    page.goto(url)

                elif cmd == "click":
                    text = parts[1].strip('"')
                    index = int(parts[2]) - 1 if len(parts) > 2 else 0
                    elements = page.locator(f"text={text}")
                    elements.nth(index).click()

                elif cmd == "pdf":
                    filename = parts[1] if len(parts) > 1 else default_pdf
                    page.emulate_media(media="screen")
                    page.pdf(path=filename, width="1920px", height="1080px", print_background=True)
                    results.append((line, filename))

                elif cmd == "download":
                    url = parts[1]
                    saved_file = download_via_browser(url, who)
                    results.append((line, saved_file))

                elif cmd == "screenshot":
                    filename = parts[1] if len(parts) > 1 else "screenshot.png"
                    page.screenshot(path=filename, full_page=True)
                    results.append((line, filename))

                elif cmd == "screenshot_area":
                    selector = parts[1]
                    filename = parts[2] if len(parts) > 2 else "area.png"
                    page.locator(selector).screenshot(path=filename)
                    results.append((line, filename))

                elif cmd == "fill":
                    selector = parts[1]
                    value = parts[2] if len(parts) > 2 else ""
                    page.fill(selector, value)

                elif cmd == "wait":
                    seconds = float(parts[1])
                    page.wait_for_timeout(seconds * 1000)

                elif cmd == "extract_text":
                    selector = parts[1]
                    text = page.locator(selector).inner_text()
                    filename = f"{selector.replace('#','').replace('.','')}.txt"
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(text)
                    results.append((line, filename))

                elif cmd == "scroll":
                    x, y = int(parts[1]), int(parts[2])
                    page.evaluate(f"window.scrollTo({x},{y})")

                elif cmd == "key":
                    key_name = parts[1]
                    count = int(parts[2]) if len(parts) > 2 else 1
                    for _ in range(count):
                        page.keyboard.press(key_name)

                elif cmd == "type":
                    text = " ".join(parts[1:]) # everything after "type"
                    page.keyboard.type(text)

                elif cmd == "help":
                    return "HELP"

            except Exception as e:
                print(f"Command failed: {line} → {e}")

        context.close()

    return results

# --- EMAIL REPLY ---
def send_reply(recipient, pdf_files, search):
    """Send PDFs in batches if needed, including warnings for oversized files, with proper logging."""
    too_big_files = []
    attachments = []

    # Separate oversized files and normal attachments
    for desc, filename in pdf_files:
        file_size = os.path.getsize(filename)
        if file_size > MAX_EMAIL_SIZE:
            too_big_files.append((desc, filename, file_size))
        else:
            attachments.append((desc, filename, file_size))

    # --- batch attachments ---
    batches = []
    current_batch = []
    current_size = 0

    for desc, filename, size in attachments:
        if current_size + size > MAX_EMAIL_SIZE:
            batches.append(current_batch)
            current_batch = []
            current_size = 0
        current_batch.append((desc, filename))
        current_size += size

    if current_batch:
        batches.append(current_batch)

    total_sent_files = 0  # Track total files sent

    # --- send each batch ---
    for i, batch in enumerate(batches, start=1):
        msg = EmailMessage()
        msg["From"] = EMAIL_ACCOUNT
        msg["To"] = recipient
        msg["Reply-To"] = VALID_RECIPIENT

        if len(batches) > 1:
            msg["Subject"] = f"Web-Email: Your search results for \"{sanitize_header(str(search))}\" ({i}/{len(batches)} email(s))"
        else:
            msg["Subject"] = f"Web-Email: Your search results for \"{sanitize_header(str(search))}\" ({len(batch)} attachment(s))"

        # Email body
        body_text = "Here are your results:\n\n"
        for desc, filename in batch:
            body_text += f"- {desc} → {os.path.basename(filename)}\n"

        # Include warning about oversized files in every email
        if too_big_files:
            body_text += "\nWARNING: The following file(s) were too large to send via email (>25 MB):\n"
            for desc, filename, size in too_big_files:
                body_text += f"- {desc} → {os.path.basename(filename)} ({size / 1024 / 1024:.2f} MB)\n"

        msg.set_content(body_text)

        # Attach the files
        for _, filename in batch:
            with open(filename, "rb") as f:
                msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(filename))

        # Send email
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
            smtp.send_message(msg)

        total_sent_files += len(batch)

        # Immediately move this sent email to Trash
        move_last_sent_to_trash(msg["Subject"])

    print(f"Sent {total_sent_files} File(s) to {recipient}")

def sanitize_header(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ").strip()

# --- HELP EMAIL ---
def handle_help_command(sender):
    help_text = f"""
Welcome to the Web Automation Bot!

You can use this bot in two ways: SCRIPT mode or simple queries.

1. SCRIPT MODE (advanced):
   - Start your email body with "SCRIPT:" and list commands line by line.
   - Commands:
     - go <url>                  → Open a webpage
     - click <text> [n]          → Click the nth occurrence of a link/button containing text (default 1)
     - pdf [filename]            → Export the current page as a PDF (default: output.pdf)
     - download <url>            → Download a file from the given URL
     - screenshot [filename]     → Capture a full-page screenshot (default: screenshot.png)
     - screenshot_area <sel> [f] → Screenshot a specific element (selector + optional filename)
     - fill <selector> <text>    → Fill an input field with text
     - wait <seconds>            → Pause the script for a set number of seconds
     - extract_text <selector>   → Extract text from an element and save it to a .txt file
     - scroll <x> <y>            → Scroll the page to position (x,y)
     - type <text>               → Type text at the current focus
     - key <key> [count]         → Press a key (Enter, ArrowUp, Tab, etc.), optionally repeat [count] times, also things like (Control+Enter) work

   - Example SCRIPT email:
     SCRIPT:
     go https://www.python.org
     click "Documentation"
     screenshot docs.png
     pdf python_docs.pdf

2. SIMPLE QUERY MODE (basic):
   - Just type your queries line by line in the email body (no SCRIPT: needed).
   - Each line will generate a PDF of the Google search or URL.
   - Example:
     Python documentation
     https://www.python.org/downloads

3. HELP:
   - Just send an email with "HELP" in the body.
   - This will send this help message.

Notes:
- Only emails sent to {VALID_RECIPIENT} will be processed.
- Only whitelisted senders are accepted.
- For SCRIPT mode, commands are executed sequentially.
- PDF attachments will be sent back via email.

Enjoy automating the web!
"""
    msg = EmailMessage()
    msg["From"] = EMAIL_ACCOUNT
    msg["To"] = sender
    msg["Subject"] = "Web Automation Bot Help"
    msg["Reply-To"] = VALID_RECIPIENT
    msg.set_content(help_text)

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        smtp.send_message(msg)

def process_query(query, filename="result.pdf", who="profile"):
    if query.startswith(("http://", "https://")):
        parsed = urlparse(query)
        path = parsed.path.strip()
        ext = os.path.splitext(path)[1].lower()  # get extension including dot

        # If path is empty, just "/", or ends with "/", treat as web page → PDF
        if path == "" or path == "/" or path.endswith("/"):
            return ("pdf", make_pdf(query, filename, who))

        # If it has a file extension that is NOT a known web page → download
        if ext and ext not in WEB_PAGE_EXTENSIONS:
            return ("media", download_via_browser(query, who))

    return ("pdf", make_pdf(query, filename, who))

def move_last_sent_to_trash(subject):
    """Move the most recent sent email with the given subject to Gmail's Trash folder."""
    # Sanitize subject for Gmail search
    subject_ascii = subject.replace('"', '\\"')  # escape quotes
    subject_ascii = subject_ascii.encode('ascii', errors='ignore').decode('ascii')

    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
    mail.select('"[Gmail]/Sent Mail"')  # Gmail Sent folder

    # Search for the most recent email with that subject
    status, data = mail.uid('search', None, f'(HEADER Subject "{subject_ascii}")')
    if status != "OK":
        mail.logout()
        return

    email_ids = data[0].split()
    if not email_ids:
        mail.logout()
        return

    last_email_id = email_ids[-1]  # get the latest sent
    # Move it to Trash
    mail.uid('STORE', last_email_id, '+X-GM-LABELS', '\\Trash')
    mail.expunge()
    mail.logout()
    print(f"Moved sent email '{subject}' to Trash.")

# --- MAIN LOOP ---
def main():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
    mail.select(CHECK_FOLDER)

    sender, body, email_id = fetch_latest_email()
    if not body:
        print("No new emails.")
        return

    print(f"Processing email from {sender}...")
    print(f"Email body:\n{body}\n{'-'*40}")

    # --- check HELP first ---
    if body.strip().upper() == "HELP":
        handle_help_command(sender)
        print("Sent help reply.")
    else:
        if is_script(body):
            commands = parse_script(body)
            result = process_navigation_commands(commands, "output.pdf", sender)
            if result:
                send_reply(sender, result, body)
                for _, f in result:
                    os.remove(f)
        else:
            queries = parse_queries(body)
            pdf_files = []
            for i, query in enumerate(queries, start=1):
                filename = f"result_{i}.pdf"
                type_, result_file = process_query(query, filename, sender)
                pdf_files.append((query, result_file))
            send_reply(sender, pdf_files, body)
            for _, f in pdf_files:
                os.remove(f)

    # --- Mark email for deletion ---
    if email_id:
        # Move the processed email to Gmail Trash
        mail.uid('STORE', email_id, '+X-GM-LABELS', '\\Trash')
        mail.expunge()
        print(f"Moved email from {sender} to Trash.")

    mail.logout()

if __name__ == "__main__":
    main()
