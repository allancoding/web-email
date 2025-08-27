# Web Automation Bot

Welcome to the **Web Automation Bot**! 🚀  
This tool lets you automate the web by sending simple emails.  
It supports running **automation scripts** or **one-off queries**, and returns results (PDFs, screenshots, downloads) via email.

---

## 📦 Features
- Fetch latest emails and process commands automatically.
- Two modes:
  - **SCRIPT mode** → full automation with step-by-step commands.
  - **Simple Query mode** → quick searches or PDFs of websites.
- Supports screenshots, PDF export, text extraction, file downloads, and navigation.
- Handles oversized files gracefully (skips attachments >25 MB).
- Only processes emails from whitelisted senders.

---

## ⚙️ Setup

### 1. Clone the project
```bash
git clone https://github.com/allancoding/web-email.git
cd web-email
```

### 2. Create a virtual environment
```bash
python -m venv .venv
``` 

### 3. Activate the virtual environment
```bash
source .venv/bin/activate
```

#### Linux/macOS (bash/zsh):
```bash
source .venv/bin/activate
```

#### Windows (cmd):
```bash
.venv\Scripts\activate
```

#### Windows (PowerShell):
```bash
.venv\Scripts\Activate.ps1
```

### 4. Install dependencies
```bash
pip install -r requirements.txt
```

Note: `chrome` (google-chrome) must be installed and accessible in your PATH.

---

## 🚀 Usage

You can use this bot in two ways: **SCRIPT mode** or **Simple Query mode**.

### 1. SCRIPT MODE (advanced)
- Start your email body with `SCRIPT:` and list commands line by line.
- Commands:
  - `go <url>` → Open a webpage
  - `click <text> [n]` → Click the nth occurrence of a link/button containing text (default 1)
  - `pdf [filename]` → Export the current page as a PDF (default: output.pdf)
  - `download <url>` → Download a file from the given URL
  - `screenshot [filename]` → Capture a full-page screenshot (default: screenshot.png)
  - `screenshot_area <sel> [f]` → Screenshot a specific element (selector + optional filename)
  - `fill <selector> <text>` → Fill an input field with text
  - `wait <seconds>` → Pause the script for a set number of seconds
  - `extract_text <selector>` → Extract text from an element and save it to a .txt file
  - `scroll <x> <y>` → Scroll the page to position (x,y)
  - `type <text>` → Type text at the current focus
  - `key <key> [count]` → Press a key (Enter, ArrowUp, Tab, etc.), optionally repeat [count] times, also things like (Control+Enter) work

- **Example SCRIPT email:**
  ```
  SCRIPT:
  go https://www.python.org
  click "Documentation"
  screenshot docs.png
  pdf python_docs.pdf
  ```

### 2. SIMPLE QUERY MODE (basic)
- Just type your queries line by line in the email body (no SCRIPT: needed).
- Each line will generate a PDF of the Google search or URL.

- **Example:**
  ```
  Python documentation
  https://www.python.org/downloads
  ```

### 3. HELP
- Just send an email with `HELP` in the body.
- This will send this help message.

---

## 📝 Notes
- Only emails sent to `{VALID_RECIPIENT}` will be processed.
- Only whitelisted senders are accepted.
- For SCRIPT mode, commands are executed sequentially.
- PDF attachments will be sent back via email.

---

Enjoy automating the web! 🎉
