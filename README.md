# 🎮 BGMI ID INFO

A powerful and lightweight CLI tool to fetch the in-game username linked
to a given **BGMI (Battlegrounds Mobile India) UID**.

The tool automatically generates a fresh authorization token, manages
session cookies dynamically, and securely retrieves player information
in real time.

------------------------------------------------------------------------

## ⚡ Features

-   🎯 Fetch BGMI username using UID\
-   🔐 Automatic token & cookie handling\
-   🎨 Stylish colored CLI interface\
-   ⚡ Fast and lightweight\
-   🖥️ Works on Linux, Windows & Termux\
-   🔄 Fresh token generated on every run

------------------------------------------------------------------------

## 📸 Preview

    ██████╗  ██████╗ ███╗   ███╗██╗
    ██╔══██╗██╔════╝ ████╗ ████║██║
    ██████╔╝██║  ███╗██╔████╔██║██║
    ██╔══██╗██║   ██║██║╚██╔╝██║██║
    ██████╔╝╚██████╔╝██║ ╚═╝ ██║██║
    ╚═════╝  ╚═════╝ ╚═╝     ╚═╝╚═╝

    BGMI ID INFO
    Developer : Anubhav Kashyap
    GitHub/Telegram : @anubhavanonymous

------------------------------------------------------------------------

# 🚀 Installation Guide

## 1️⃣ Clone Repository

``` bash
git clone https://github.com/yourusername/bgmi-id-info.git
cd bgmi-id-info
```

Or download the ZIP file and extract it.

------------------------------------------------------------------------

## 2️⃣ Install Requirements

Make sure Python 3.8+ is installed.

Install dependencies:

``` bash
pip install requests colorama
```

For Termux:

``` bash
pkg install python
pip install requests colorama
```

------------------------------------------------------------------------

# ▶️ Usage

Run the tool with a BGMI UID:

``` bash
python bgmi_id_info.py <BGMI_UID>
```

Example:

``` bash
python bgmi_id_info.py 1234567890
```

------------------------------------------------------------------------

# 📌 Output Example

    =========== RESULT ===========
    [✓] Username : ANUBHAV_OP
    [✓] UID      : 1234567890
    [✓] Server   : BGMI
    [✓] Region   : India
    ==============================

------------------------------------------------------------------------

# 🛠 Requirements

-   Python 3.8+
-   requests
-   colorama
-   Internet connection

------------------------------------------------------------------------

# 🔒 How It Works

1.  Creates a secure session.
2.  Automatically fetches authorization token.
3.  Manages cookies dynamically.
4.  Queries backend API.
5.  Displays username linked to UID.

No manual cookie or token input required.

------------------------------------------------------------------------

# ⚠ Disclaimer

This tool is created for educational and informational purposes only.\
Use responsibly and in accordance with applicable laws and platform
terms of service.

The developer is not responsible for misuse.

------------------------------------------------------------------------

# 👨‍💻 Developer

**Anubhav Kashyap**\
GitHub / Telegram: `@anubhavanonymous`
