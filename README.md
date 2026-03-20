<p align="center">
  <img src="banner.png" alt="Tele-Trace Intelligence Banner" width="100%">
</p>


       ◈  TELE-TRACE  INTELLIGENCE

A local web-based Telegram OSINT tool built with Flask + Telethon.
Runs entirely on your device — no cloud, no data sharing.
<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-blue?style=for-the-badge&logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/Linux-Compatible-yellow?style=for-the-badge&logo=linux&logoColor=black">
  <img src="https://img.shields.io/badge/Open%20Source-MIT-green?style=for-the-badge&logo=open-source-initiative&logoColor=white">
  <img src="https://img.shields.io/badge/Flask-Backend-grey?style=for-the-badge&logo=flask&logoColor=white">
  <img src="https://img.shields.io/badge/Telethon-Powered-blue?style=for-the-badge&logo=telegram&logoColor=white">
  <img src="https://img.shields.io/badge/Termux-Supported-black?style=for-the-badge&logo=android&logoColor=white">
  <img src="https://img.shields.io/badge/OSINT-Tool-red?style=for-the-badge&logo=searchengin&logoColor=white">
  <img src="https://img.shields.io/badge/Platform-Telegram-blue?style=for-the-badge&logo=telegram&logoColor=white">
</p>

---

## Requirements 📌

- Python 3.8+
- Termux (Android) or Linux/macOS
- Telegram account + API credentials

---

## Installation 🛠️

```bash
# Clone the repository
git clone https://github.com/anubhavanonymous/Tele-Trace
cd Tele-Trace

# Install dependencies
pip install -r requirements.txt

# On Termux
pip install -r requirements.txt --break-system-packages
```

---

## Getting API Credentials ⚙️

1. Visit https://my.telegram.org and log in
2. Click **API Development Tools**
3. Create a new app (any name)
4. Copy your **API ID** and **API Hash**

> ⚠ Use an aged Telegram account (1+ years old) for best results. New accounts are heavily restricted by Telegram and may fail to resolve phone number lookups or get temporarily banned from making API requests.

---

## Running 🚀

```bash
python tele-trace.py
```

Open **http://localhost:7777** in your browser.

---

## Login 🔑

1. Enter your API ID, API Hash, and phone number
2. Select your country code from the dropdown
3. Click **Continue** — you'll receive a code in Telegram
4. Enter the code. If you have 2FA enabled, enter your password too
5. Session is saved locally — next launch skips login automatically

To switch accounts, click **Switch Account** in the top bar.

---

## 💠 Features

### 👤 Profile Scan
Search by **phone number** or **@username**. Extracts:
- Name, bio, last seen status
- User ID, phone, all active usernames
- Account flags: Bot, Fake, Scam, Premium, Verified
- Profile photos and video DPs with upload dates

### 🧓🏻 Account Age Estimate
Estimates account creation date from the user ID using
Telegram's sequential ID system. Accurate to ±1-2 months.

### 🔰 Trust Score
0–100% confidence score based on 9 factors:
username pattern, bio presence, photo count, account age,
status visibility, name history, premium/verified status,
no flags, and platform presence.

### 🔍 Username Intelligence
- Pattern detection (name_surname, CamelCase, gaming style, etc.)
- **Type** — Likely real name vs Nickname/Handle (detects shadow, ghost, king, wolf, hacker, cyber, etc.)
- Possible real name extraction
- **Name Origin** — Indian, Arabic/Muslim, Russian/Slavic, Western, Chinese/Korean
- **Name Meaning** — dictionary of common names (e.g. Aditya = Sun/First, Arjun = Bright, Ali = High/Exalted)
- Possible region from name roots
- Birth year detection (extended range: 1970–2022)
- **Name Match** — compares username tokens vs display name, shows consistency score
- Entropy score

### 📝 Bio Analysis
- Language detection (Hindi, Arabic, Russian, Chinese, Korean, English + mixed)
- Possible name extraction
- **Age detection** — patterns like `21 y.o`, `born 2002`, `class of 2020`
- **Gender signals** — pronouns (he/him, she/her, they/them) + gender emojis
- **Occupation** — 11 categories: Developer, Designer, Student, Content Creator, Entrepreneur, Trader, Writer, Artist, Gamer, Cybersecurity, Doctor/Medical
- **Location hints** — flag emojis + 40+ city/country name detection
- **Relationship status** — Single, In a relationship, Engaged, Married, Parent
- **Religion signals** — Islam, Christianity, Hinduism, Sikhism via keywords + symbols
- **Email in bio** — extracts any email address present
- **Phone in bio** — extracts phone numbers present
- **Crypto presence** — keyword detection + BTC/ETH wallet address extraction
- External links (Instagram, GitHub, bare domains like site.com, etc.)
- Emotion score (Positive / Negative / Neutral)
- **Emoji usage** — flags heavy emoji use (5+ emojis)
- Hashtags and @mentions

### ✍🏻 Name & Username History
Queries SangMata bot for recorded name/username changes with timestamps.
History request is sent before photo downloads so the reply is ready
by the time scanning completes.

### 🔭 Cross-Platform Search
Checks the username across 9 platforms simultaneously:

| Platform  | Detection Method                        |
|-----------|-----------------------------------------|
| GitHub    | Signup check API                        |
| Instagram | web_profile_info API + page fallback    |
| Reddit    | Body text check                         |
| TikTok    | statuscode 10202 = not found            |
| Snapchat  | HTTP 200/404                            |
| Pinterest | Body text check                         |
| Discord   | POST API — JSON `taken` field           |
| LinkedIn  | Twitterbot UA trick                     |
| Medium    | Profile meta tag + body detection       |

Found profiles show as clickable links.

### 🔎 Reverse Image Search
Each photo card has Google Lens and Yandex buttons.
Photos are pre-uploaded to catbox.moe in the background
after scan — clicking opens results instantly.

### 📑 Exports
- **JSON** — full structured data including trust score,
  username intel, bio analysis, history, cross-platform results, media
- **PDF** — printable HTML report with all sections.
  Open in browser → Print → Save as PDF

---

## Troubleshooting 💡

| Problem | Fix |
|---------|-----|
| OTP fails | Check API ID and Hash are correct |
| No account found for phone | Number has no Telegram or privacy blocked. Try username search |
| Photos not loading | WebP issue on Android. Use Save button to download |
| History shows no data | Bot quota may be exceeded. Check reset time shown in UI |
| Platform scan all errors | Some platforms block your network. Try a VPN |
| Reverse image upload fails | catbox.moe may be down. Save photo and upload manually |

---

## Project Structure 📁

```
tg_osint_tool/
├── app.py              # Flask backend + Telethon logic
├── requirements.txt    # Python dependencies
├── README.md
├── templates/
│   └── index.html      # Frontend (HTML + CSS + JS)
└── static/             # Static assets
```

---

## Disclaimer ⚠️

This tool is for **educational and authorized research purposes only**.

- Only interacts with publicly accessible Telegram data
- Does not bypass any privacy settings or authentication
- Users are responsible for compliance with applicable laws
- Author assumes no liability for misuse

---

## Author 👤

**Anubhav Kashyap**

Telegram / GitHub: [@anubhavanonymous](https://t.me/anubhavanonymous)
