<div align="center">

  <img src="assets/icon.png" width="120" height="120" alt="My Downloader Logo">

  # My Downloader

  **A high-performance, modular CLI toolkit for seamless video and audio extraction powered by `yt-dlp` and `FFmpeg`.**

  [![Latest Release](https://img.shields.io/github/v/release/Y2m777a5/My-Downloader?color=0078D4&label=Latest%20Release&style=flat-square)](https://github.com/Y2m777a5/My-Downloader/releases/latest)
  [![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey?style=flat-square)](#-system-requirements)
  [![License](https://img.shields.io/github/license/Y2m777a5/My-Downloader?style=flat-square)](LICENSE)

  [Quick Download](#-quick-start) • [Features](#-key-features) • [Installation](#-quick-start) • [Troubleshooting](#-important-notes--troubleshooting)

</div>

---

## 🚀 Quick Start

Get up and running in seconds. Download the latest pre-packaged zip bundle directly:

<div align="center">

[![Download Portable Package](https://img.shields.io/badge/Download-My__Downloader.zip-2ea44f?style=for-the-badge&logo=github)](https://github.com/Y2m777a5/My-Downloader/raw/main/My%20Downloader.zip)

*(Or grab the executable directly from the [Latest Release Page](https://github.com/Y2m777a5/My-Downloader/releases/latest))*

</div>

---

## ✨ Key Features

* **⚡ Configurable Multi-Threading:** Fine-tune download worker threads (1, 4, 8, or 16) for accelerated parallel extractions.
* **📂 Smart Workflow Engine:** Modular sub-menus tailored specifically for single videos, full playlists, or standalone audio extractions (MP3, M4A/AAC).
* **🎯 Precision Quality Selection:** Native support for standard format selection or advanced manual stream inspection (`-F`).
* **⚙️ Persistent Configurations:** Dynamic settings engine (`config.json`) saves custom output paths and user preferences automatically.
* **🖥️ Windows Native Integration:** Create or remove Start Menu and Desktop shortcuts directly from the app interface.
* **🛑 Instant Process Termination:** Multi-platform terminal control allowing real-time `Q`-key process cancellation.

---

## 📥 Installation & First-Time Setup

1. **Extract Files:** Download `My Downloader.zip` and extract its contents into a dedicated folder.
2. **Launch App:** Run `My Downloader.exe`.
3. **Initialize Core Binaries:** On your **first launch**, navigate to **`Option [4] (Install / Update)`** to automatically download the latest underlying runtime dependencies (`yt-dlp` and `FFmpeg`).

---

## ⚠️ Important Notes & Troubleshooting

> [!IMPORTANT]
> * **Directory Structure:** Keep the application executable and the generated `bin/` folder in the **exact same directory**.
> * **Do Not Delete `bin/`:** The `bin/` folder contains your configurations, runtime engines, and media utilities.

> [!TIP]
> **Windows Smart App Control / Defender Warnings:**
> Because this application is open-source and currently unsigned, Windows SmartScreen or Smart App Control may display a prompt. 
> * Click **More Info** $\rightarrow$ **Run Anyway** to bypass the prompt.
> * Alternatively, you can run the source script directly via Python.

---

## 🛠️ System Requirements

* **Operating System:** Windows 10/11 (macOS / Linux supported via raw Python execution)
* **Dependencies:** `yt-dlp` & `FFmpeg` *(Automatically installed and managed in-app)*
