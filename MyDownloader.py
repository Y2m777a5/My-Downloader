from __future__ import annotations

import os
import re
import ssl
import sys
import time
import signal
import shutil
import zipfile
import tempfile
import subprocess
import json
import threading
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures
from pathlib import Path

# Platform-specific imports for keyboard input and Win32 API calls
try:
    import msvcrt
except ImportError:
    msvcrt = None

try:
    import ctypes
    from ctypes import wintypes

    class _COORD(ctypes.Structure):
        _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

    class _SMALL_RECT(ctypes.Structure):
        _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short),
                    ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]

    class _CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
        _fields_ = [("dwSize", _COORD), ("dwCursorPosition", _COORD),
                    ("wAttributes", ctypes.c_ushort), ("srWindow", _SMALL_RECT),
                    ("dwMaximumWindowSize", _COORD)]
except ImportError:
    ctypes = None

# --- Configuration & Metadata ---
VERSION = "4.4.8.6"
CURRENT_VERSION = VERSION
REPO_OWNER = "Y2m777a5"
REPO_NAME = "My-Downloader"       
GITHUB_EXE_FILENAME = "My.Downloader.exe"  # Exact name uploaded on GitHub Releases
LOCAL_EXE_FILENAME = "My Downloader.exe"   # Exact name on local PC

# Default console dimensions
CONSOLE_COLS = 120
CONSOLE_LINES = 40
MAX_CONSOLE_COLS = 220  # Hard ceiling for screen width

WHITE = "\033[97m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
GREEN = "\033[38;2;0;254;0m"
RESET = "\033[0m"
DEFAULT_COLOR = "\033[38;2;238;128;32m"

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()
BIN_DIR = BASE_DIR / "bin"
CONFIG_FILE = BIN_DIR / "config.json"
YTDLP = BIN_DIR / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")

BIN_DIR.mkdir(exist_ok=True)

UPDATE_AVAILABLE = False

FULL = "█" * 25
EMPTY = "░" * 25


# --- App Configuration & Settings Helpers ---

DEFAULT_CONFIG = {
    "download_dir": str(BASE_DIR / "Downloads"),
    "desktop_shortcut": False,
    "start_shortcut": False,
    "update_threads": 4,
    "media_threads": 8
}

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(cfg)
                return merged
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True) 
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print(f"{RED}[ERROR] Could not save config: {e}{WHITE}")

def get_out_dir() -> Path:
    cfg = load_config()
    out_path = Path(cfg.get("download_dir", str(BASE_DIR / "Downloads")))
    out_path.mkdir(parents=True, exist_ok=True)
    return out_path


# --- Windows Shortcut Management ---

def get_current_exe_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return BASE_DIR / LOCAL_EXE_FILENAME

def get_desktop_shortcut_path(verbose: bool = False) -> Path:
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            desktop_val = winreg.QueryValueEx(key, "Desktop")[0]
            desktop_val = os.path.expandvars(desktop_val)
            if desktop_val:
                if verbose and "onedrive" in desktop_val.lower():
                    print(f"{YELLOW}[INFO] Your Desktop is redirected to OneDrive; creating the shortcut there.{WHITE}")
                return Path(desktop_val) / "My Downloader.lnk"
        except Exception:
            pass
    return Path.home() / "Desktop" / "My Downloader.lnk"

def get_start_shortcut_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "My Downloader.lnk"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "My Downloader.lnk"

def create_windows_shortcut(target_exe: Path, shortcut_path: Path):
    if os.name != "nt":
        return
    try:
        shortcut_path.parent.mkdir(parents=True, exist_ok=True)
        def ps_quote(p: Path) -> str:
            return str(p.resolve()).replace("'", "''")

        ps_script = (
            f"$WshShell = New-Object -ComObject WScript.Shell; "
            f"$Shortcut = $WshShell.CreateShortcut('{ps_quote(shortcut_path)}'); "
            f"$Shortcut.TargetPath = '{ps_quote(target_exe)}'; "
            f"$Shortcut.WorkingDirectory = '{ps_quote(target_exe.parent)}'; "
            f"$Shortcut.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, **get_sp_kwargs())
    except Exception as e:
        print(f"{RED}[ERROR] Failed to create shortcut: {e}{WHITE}")

def delete_windows_shortcut(shortcut_path: Path):
    try:
        if shortcut_path.exists():
            shortcut_path.unlink()
    except Exception as e:
        print(f"{RED}[ERROR] Failed to delete shortcut: {e}{WHITE}")

def sync_shortcuts():
    if os.name != "nt":
        return
    cfg = load_config()
    exe_path = get_current_exe_path()
    
    desktop_lnk = get_desktop_shortcut_path()
    start_lnk = get_start_shortcut_path()

    if cfg.get("desktop_shortcut") or desktop_lnk.exists():
        create_windows_shortcut(exe_path, desktop_lnk)
        cfg["desktop_shortcut"] = True

    if cfg.get("start_shortcut") or start_lnk.exists():
        create_windows_shortcut(exe_path, start_lnk)
        cfg["start_shortcut"] = True

    save_config(cfg)


# --- SSL Utilities ---

def create_secure_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()

def create_insecure_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_client)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def urlopen_with_fallback(req, ctx, timeout=30):
    try:
        return urllib.request.urlopen(req, context=ctx, timeout=timeout)
    except (ssl.SSLCertVerificationError, urllib.error.URLError) as e:
        reason = getattr(e, "reason", e)
        if not isinstance(reason, ssl.SSLError) and not isinstance(e, ssl.SSLCertVerificationError):
            raise
        print(f"{YELLOW}[WARNING] Certificate verification failed; retrying with an unverified connection.{WHITE}")
        insecure_ctx = create_insecure_ssl_context()
        return urllib.request.urlopen(req, context=insecure_ctx, timeout=timeout)


# --- Input & Console Helpers ---

def flush_input():
    if msvcrt:
        while msvcrt.kbhit():
            try:
                msvcrt.getch()
            except Exception:
                break
    else:
        try:
            import select
            while select.select([sys.stdin], [], [], 0.0)[0]:
                sys.stdin.read(1)
        except Exception:
            pass

def enable_unix_raw_mode():
    """Puts stdin into cbreak mode on Unix so a single keypress (like 'q')
    is available to read() immediately, instead of the terminal's default
    line-buffered (canonical) mode which withholds all input until Enter is
    pressed. Returns the original settings to restore later, or None on
    Windows / if unsupported. ALWAYS pair this with restore_unix_terminal_mode
    in a finally block -- leaving a user's shell in raw mode after the app
    exits is a much worse problem than the bug this fixes."""
    if os.name == "nt":
        return None
    try:
        import termios, tty
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        return old_settings
    except Exception:
        return None

def restore_unix_terminal_mode(old_settings):
    if os.name == "nt" or old_settings is None:
        return
    try:
        import termios
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
    except Exception:
        pass

def check_q_pressed() -> bool:
    q_found = False
    if msvcrt:
        while msvcrt.kbhit():
            try:
                ch = msvcrt.getch()
                if ch.lower() == b"q":
                    q_found = True
            except Exception:
                break
    else:
        try:
            import select
            while select.select([sys.stdin], [], [], 0.0)[0]:
                ch = sys.stdin.read(1)
                if ch.lower() == 'q':
                    q_found = True
        except Exception:
            pass
    return q_found

def kill_proc_tree(proc: subprocess.Popen | None):
    """Forcefully kills the process and all its child processes."""
    if proc is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        else:
            # Guard against accidentally SIGKILLing our own process group --
            # currently every caller spawns with start_new_session=True,
            # which already prevents this, but this makes the function safe
            # by construction rather than relying on every future caller
            # remembering that flag.
            pgid = os.getpgid(proc.pid)
            if pgid != os.getpgrp():
                os.killpg(pgid, signal.SIGKILL)
            else:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def get_sp_kwargs() -> dict:
    """Returns OS-specific subprocess arguments (hides window on Windows, inert on Linux/macOS)."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}

def enable_vt_mode():
    """Enables Virtual Terminal Processing for ANSI sequence rendering on Windows."""
    if os.name != "nt" or ctypes is None:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        h_stdout = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
            kernel32.SetConsoleMode(h_stdout, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass

def disable_quick_edit_mode():
    """Completely disables QuickEdit Mode, Insert Mode, and Mouse Selection to prevent input locks."""
    if os.name != "nt" or ctypes is None:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        h_stdin = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
            new_mode = (mode.value & ~0x0040 & ~0x0020 & ~0x0010) | 0x0080
            kernel32.SetConsoleMode(h_stdin, new_mode)
    except Exception:
        pass

def setup_console():
    if os.name == "nt":
        os.system("")
        enable_vt_mode()
        disable_quick_edit_mode()
    else:
        pass

def term_width() -> int:
    if os.name == "nt" and ctypes is not None:
        # shutil.get_terminal_size() can silently fall back to its default
        # tuple in some frozen-exe/ConPTY (Windows Terminal) situations rather
        # than raising, which centers text for the wrong (much narrower)
        # width. Query the real visible console window width directly via the
        # Win32 console API -- this is the same mechanism ConPTY implements to
        # support legacy console apps, so it's reliable under Windows Terminal.
        try:
            kernel32 = ctypes.windll.kernel32
            h_stdout = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            csbi = _CONSOLE_SCREEN_BUFFER_INFO()
            if kernel32.GetConsoleScreenBufferInfo(h_stdout, ctypes.byref(csbi)):
                width = csbi.srWindow.Right - csbi.srWindow.Left + 1
                if width > 0:
                    return width
        except Exception:
            pass
    return shutil.get_terminal_size((CONSOLE_COLS, CONSOLE_LINES)).columns

def strip_ansi(text: str) -> str:
    return re.sub(r'\033\[[0-9;]*[a-zA-Z]', '', text)

def ccenter(text: str, width: int) -> str:
    visible_len = len(strip_ansi(text))
    pad = max((width - visible_len) // 2, 0)
    return " " * pad + text

def cline(text: str = ""):
    width = term_width()
    vis_len = len(strip_ansi(text))
    pad = max((width - vis_len) // 2, 0)
    print(" " * pad + text)

def cblock(text: str):
    width = term_width()
    lines = text.splitlines()
    maxlen = max((len(strip_ansi(l)) for l in lines), default=0)
    pad = max((width - maxlen) // 2, 0)
    for line in lines:
        print(" " * pad + line)

def lblock(text: str):
    for line in text.splitlines():
        print(line)

def clear():
    """Clears the console screen using native ANSI control codes without spawning subshells."""
    if os.name == "nt":
        disable_quick_edit_mode()
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    else:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

def cleanup_partials():
    out_dir = get_out_dir()
    patterns = ("*.part", "*.ytdl", "*.part-*", "*.f[0-9]*.*")
    for pattern in patterns:
        for f in out_dir.glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass


# --- UI Elements ---

def print_header_prompt(title: str):
    print()
    lines = [
        "----------------------------------------------------",
        title.center(52),
        "----------------------------------------------------",
        " [0] Menu",
        " [1] Download",
        "----------------------------------------------------",
        "For multiple downloads: use space or separate lines".center(52),
    ]
    cblock("\n".join(lines))
    print()

def print_header_simple(title: str):
    print()
    lines = [
        "----------------------------------------------------",
        title.center(52),
        "----------------------------------------------------",
    ]
    cblock("\n".join(lines))
    print()

def print_logo():
    logo = r"""
 __  __         ____                      _                 _           
|  \/  |_   _  |  _ \  _____      ___ __ | | ___   __ _  __| | ___ _ __ 
| |\/| | | | | | | | |/ _ \ \ /\ / | '_ \| |/ _ \ / _` |/ _` |/ _ | '__|
| |  | | |_| | | |_| | (_) \ V  V /| | | | | (_) | (_| | (_| |  __| |   
|_|  |_|\__, | |____/ \___/ \_/\_/ |_| |_|_|\___/ \__,_|\__,_|\___|_|   
        |___/                                                            
"""
    cblock(f"\033[38;2;238;128;32m{logo}{WHITE}")

def print_menu():
    clear()
    print()
    print_logo()
    print()

    install_option = f" [4] Install / Update  {YELLOW}(Available){WHITE}" if UPDATE_AVAILABLE else " [4] Install / Update"

    menu_lines = [
        "====================================================",
        "Main Menu".center(52),
        "====================================================",
        " [1] Download Video",
        " [2] Download Audio",
        " [3] Download Playlist",
        install_option,
        " [5] Settings",
        " [6] Exit",
        "====================================================",
    ]
    cblock("\n".join(menu_lines))
    print()
    imp_lines = [
        "# First-time users: Choose option 4",
        "# N.B: Keep the app in a folder.",
        "# WARNING: Do not delete the 'bin' folder.",
    ]
    print(f"{YELLOW}")
    cblock("\n".join(imp_lines))
    print(f"\n\n{WHITE}")


# --- Settings Options Implementation ---

def action_settings_download_dir():
    while True:
        cfg = load_config()
        clear()
        print_header_simple("Download Directory Change")
        
        lines = [
            ccenter(f"{YELLOW}Select [0] to go to SETTINGS MENU{WHITE}", 52),
            "====================================================",
            " [1] change download folder",
            " [2] Set Default",
            "====================================================",
        ]
        cblock("\n".join(lines))

        curr_dir = cfg.get("download_dir", str(BASE_DIR / "Downloads"))
        print(f"\n{CYAN}")
        cline(f"Current Download Directory: {curr_dir}")
        print(f"{WHITE}\n")

        choice = input("Select an option (0-2): ").strip()
        if choice == "0":
            break
        elif choice == "1":
            print()
            new_path = input("Enter new download folder path: ").strip()
            if new_path:
                try:
                    p = Path(new_path).resolve()
                    p.mkdir(parents=True, exist_ok=True)
                    cfg["download_dir"] = str(p)
                    save_config(cfg)
                    print(f"\n{GREEN}[SUCCESS] Download directory updated to: {p}{WHITE}")
                except Exception as e:
                    print(f"\n{RED}[ERROR] Invalid path: {e}{WHITE}")
            else:
                print(f"\n{YELLOW}[!] Operation canceled.{WHITE}")
            time.sleep(1.5)
        elif choice == "2":
            cfg["download_dir"] = str(BASE_DIR / "Downloads")
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Download directory reset to default.{WHITE}")
            time.sleep(1.5)
        else:
            print(f"\n{RED}[ERROR] Invalid option!{WHITE}")
            time.sleep(1)

def action_settings_shortcuts():
    while True:
        cfg = load_config()
        clear()
        print_header_simple("Create Shortcuts")
        
        desk_status = " (Enabled)" if cfg.get("desktop_shortcut") else " (Disabled)"
        start_status = " (Enabled)" if cfg.get("start_shortcut") else " (Disabled)"

        lines = [
            ccenter(f"{YELLOW}Select [0] to go to SETTINGS MENU{WHITE}", 52),
            "====================================================",
            f"Desktop shortcut:{desk_status}",
            " [1] Create Desktop shortcut",
            " [2] Delete Desktop shortcut",
            "",
            f"Start menu shortcut:{start_status}",
            " [3] Create Start shortcut",
            " [4] Delete Start shortcut",
            "====================================================",
        ]
        cblock("\n".join(lines))
        print("\n")

        choice = input("Select an option (0-4): ").strip()
        if choice == "0":
            break
        elif choice == "1":
            exe_path = get_current_exe_path()
            lnk_path = get_desktop_shortcut_path(verbose=True)
            create_windows_shortcut(exe_path, lnk_path)
            cfg["desktop_shortcut"] = True
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Desktop shortcut created!{WHITE}")
            time.sleep(1.5)
        elif choice == "2":
            lnk_path = get_desktop_shortcut_path()
            delete_windows_shortcut(lnk_path)
            cfg["desktop_shortcut"] = False
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Desktop shortcut deleted!{WHITE}")
            time.sleep(1.5)
        elif choice == "3":
            exe_path = get_current_exe_path()
            lnk_path = get_start_shortcut_path()
            create_windows_shortcut(exe_path, lnk_path)
            cfg["start_shortcut"] = True
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Start Menu shortcut created!{WHITE}")
            time.sleep(1.5)
        elif choice == "4":
            lnk_path = get_start_shortcut_path()
            delete_windows_shortcut(lnk_path)
            cfg["start_shortcut"] = False
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Start Menu shortcut deleted!{WHITE}")
            time.sleep(1.5)
        else:
            print(f"\n{RED}[ERROR] Invalid option!{WHITE}")
            time.sleep(1)

def action_settings_parallel():
    while True:
        cfg = load_config()
        clear()
        print_header_simple("Parallel Download Settings")
        
        lines = [
            ccenter(f"{YELLOW}Select [0] to go to SETTINGS MENU{WHITE}", 52),
            "====================================================",
            "For updating:",
            " [1] single thread download",
            " [2] 4 thread download",
            " [3] 8 thread download",
            "",
            "For Media Download:",
            " [4] single thread download",
            " [5] 4 thread download",
            " [6] 8 thread download",
            " [7] 16 thread download",
            "====================================================",
        ]
        cblock("\n".join(lines))
        
        print(f"{YELLOW}")
        cline("Note: For media downloads, 4 or more threads are recommended.")
        print(f"{RED}")
        cline("But 16 threads? Do it at your own risk.")
        print(f"{WHITE}")

        up_th = cfg.get("update_threads", 4)
        me_th = cfg.get("media_threads", 8)
        print(f"{CYAN}")
        cline(f"Current Update Threads: {up_th} | Current Media Threads: {me_th}")
        print(f"{WHITE}\n")

        choice = input("Select an option (0-7): ").strip()
        if choice == "0":
            break
        elif choice == "1":
            cfg["update_threads"] = 1
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Update parallel downloads set to 1 thread.{WHITE}")
            time.sleep(1.5)
        elif choice == "2":
            cfg["update_threads"] = 4
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Update parallel downloads set to 4 threads (>15MB).{WHITE}")
            time.sleep(1.5)
        elif choice == "3":
            cfg["update_threads"] = 8
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Update parallel downloads set to 8 threads (>15MB).{WHITE}")
            time.sleep(1.5)
        elif choice == "4":
            cfg["media_threads"] = 1
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Media download threads set to 1.{WHITE}")
            time.sleep(1.5)
        elif choice == "5":
            cfg["media_threads"] = 4
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Media download threads set to 4.{WHITE}")
            time.sleep(1.5)
        elif choice == "6":
            cfg["media_threads"] = 8
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Media download threads set to 8.{WHITE}")
            time.sleep(1.5)
        elif choice == "7":
            cfg["media_threads"] = 16
            save_config(cfg)
            print(f"\n{GREEN}[SUCCESS] Media download threads set to 16.{WHITE}")
            time.sleep(1.5)
        else:
            print(f"\n{RED}[ERROR] Invalid option!{WHITE}")
            time.sleep(1)

def action_settings_menu():
    while True:
        cfg = load_config()
        clear()
        print_header_simple("Settings Menu")
        menu_lines = [
            ccenter(f"{YELLOW}Select [0] to go to MAIN MENU{WHITE}", 52),
            "====================================================",
            " [1] Download directory change",
            " [2] Create shortcuts",
            " [3] Parallel Download settings",
            "====================================================",
        ]
        cblock("\n".join(menu_lines))
        print("\n")

        choice = input("Select an option (0-3): ").strip()
        if choice == "0":
            break
        elif choice == "1":
            action_settings_download_dir()
        elif choice == "2":
            action_settings_shortcuts()
        elif choice == "3":
            action_settings_parallel()
        else:
            print(f"\n{RED}[ERROR] Invalid option!{WHITE}")
            time.sleep(1)


# --- Execution & Downloading ---

def ensure_ytdlp_exists() -> bool:
    if not YTDLP.exists():
        print(f"{RED}[ERROR] yt-dlp was not found in the 'bin' directory!{WHITE}")
        print(f"{YELLOW}[INFO] Please run Option [4] (Install / Update) first.{WHITE}\n")
        flush_input()
        input("Press Enter to return to main menu...")
        return False
    return True

def prompt_urls_input(title: str) -> list[str]:
    clear()
    print_header_prompt(title)
    
    raw_input = input("Enter your URL(s): ").strip()
    print("\n")
    
    if not raw_input or raw_input == "0":
        print(f"{YELLOW}[!] Returning to menu...{WHITE}")
        time.sleep(1)
        return []

    urls = [u.strip() for u in raw_input.split() if u.strip()]

    if not urls:
        print(f"{YELLOW}[!] No valid URL found in your input. Returning to menu...{WHITE}")
        time.sleep(1)
        return []

    for idx, u in enumerate(urls, 1):
        print(f"video link [{idx}]: {u}")

    print()

    while True:
        choice = input("Select an option to perform the actions (0-1): ").strip()
        if choice == "0":
            return []
        elif choice == "1":
            return urls
        else:
            print(f"{RED}[ERROR] Invalid option! Please enter 0 or 1.{WHITE}")

def read_progress_and_info(log_path: Path) -> tuple[int, int | None, int | None]:
    """Reads percentage and playlist index/total from yt-dlp log file."""
    pct = 0
    pl_idx = None
    pl_total = None
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("PG|"):
                        parts = line.strip().split("|")
                        if len(parts) >= 2:
                            raw_pct = parts[1].replace("%", "").strip()
                            try:
                                pct = int(float(raw_pct))
                            except ValueError:
                                pass
                        if len(parts) >= 4:
                            raw_idx = parts[2].strip()
                            raw_tot = parts[3].strip()
                            if raw_idx.isdigit():
                                pl_idx = int(raw_idx)
                            if raw_tot.isdigit():
                                pl_total = int(raw_tot)
                    else:
                        m = re.search(r"Downloading (?:video|item) (\d+) of (\d+)", line, re.IGNORECASE)
                        if m:
                            pl_idx = int(m.group(1))
                            pl_total = int(m.group(2))
        except OSError:
            pass
    return max(0, min(100, pct)), pl_idx, pl_total

def draw_progress(pct: int, pl_idx: int | None = None, pl_total: int | None = None):
    filled = pct // 4
    bar = FULL[:filled] + EMPTY[:25 - filled]
    info_str = f" (Item {pl_idx}/{pl_total})" if pl_idx and pl_total else ""
    
    raw_str = f"Progress:  [{bar}] {pct}%{info_str}"
    
    max_len = max(10, term_width() - 2)
    if len(raw_str) > max_len:
        raw_str = raw_str[:max_len - 3] + "..."

    sys.stdout.write(f"\033[2A\r\033[K{CYAN}{raw_str}\033[0m\n\033[1B")
    sys.stdout.flush()

def parse_playlist_log_stats(content: str, reported_total: int | None) -> tuple[int, int, int]:
    """Parses log content to report total, succeeded, and failed items in a playlist."""
    lines = content.splitlines()
    failed_items = set()
    succeeded_items = set()
    current_item = None

    for line in lines:
        m = re.search(r"\[(?:download|youtube)\] Downloading (?:video|item) (\d+) of (\d+)", line, re.IGNORECASE)
        if m:
            current_item = int(m.group(1))

        if "ERROR:" in line or "unable to download" in line.lower():
            if current_item is not None:
                failed_items.add(current_item)
            else:
                failed_items.add(f"err_{len(failed_items)}")

        if ("100%" in line and "of" in line) or "Destination:" in line or "has already been downloaded" in line:
            if current_item is not None and current_item not in failed_items:
                succeeded_items.add(current_item)

    succeeded = len(succeeded_items - failed_items)
    failed = len(failed_items)
    
    tot = reported_total if reported_total else (succeeded + failed)
    if tot < (succeeded + failed):
        tot = succeeded + failed

    return tot, succeeded, failed

def download_batch_with_bar(urls: list[str], title: str, extra_args: list[str]):
    if not ensure_ytdlp_exists() or not urls:
        return

    out_dir = get_out_dir()
    cfg = load_config()
    media_threads = str(cfg.get("media_threads", 8))

    total = len(urls)
    clear()
    print_header_simple(title)

    successful_count = 0
    canceled_count = 0
    failed_count = 0
    stop_all_batch = False

    for idx, url in enumerate(urls, 1):
        if stop_all_batch:
            break

        log_path = Path(tempfile.gettempdir()) / f"ytdlp_progress_{os.getpid()}_{idx}.txt"
        cleanup_log(log_path)

        cmd = [
            str(YTDLP),
            "--ffmpeg-location", str(BIN_DIR),
            "--no-colors",
            "-N", media_threads,
            *extra_args,
            "--newline",
            "--progress-template", "PG|%(progress._percent_str)s|%(info.playlist_index)s|%(info.playlist_count)s",
            "-o", str(out_dir / "%(title)s.%(ext)s"),
            url,
        ]

        log_file = open(log_path, "w", encoding="utf-8", errors="ignore")
        
        popen_kwargs = get_sp_kwargs()
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            cmd, 
            stdout=log_file, 
            stderr=subprocess.STDOUT,
            **popen_kwargs
        )

        url_prefix = f"URL [{idx}/{total}]: "
        max_url_len = max(10, term_width() - len(url_prefix) - 2)
        display_url = url if len(url) <= max_url_len else url[:max_url_len - 3] + "..."
        print(f"{url_prefix}{display_url}")
        print(f"{CYAN}Progress:  [" + EMPTY + f"] 0%{RESET}")
        print(f"{YELLOW}[INFO] Press 'Q' or 'Ctrl+C' to cancel downloads.{RESET}")

        canceled = False
        last_pct = -1
        last_pl_idx = None
        last_pl_tot = None
        _term_settings = enable_unix_raw_mode()

        try:
            while True:
                if check_q_pressed():
                    kill_proc_tree(proc)
                    canceled = True
                    stop_all_batch = True
                    break

                if proc.poll() is not None:
                    break

                pct, pl_idx, pl_tot = read_progress_and_info(log_path)
                if pct != last_pct or pl_idx != last_pl_idx or pl_tot != last_pl_tot:
                    draw_progress(pct, pl_idx, pl_tot)
                    last_pct = pct
                    if pl_idx: last_pl_idx = pl_idx
                    if pl_tot: last_pl_tot = pl_tot

                time.sleep(0.25)

        except KeyboardInterrupt:
            kill_proc_tree(proc)
            canceled = True
            stop_all_batch = True
            print(f"\n{RED}[!] Batch process interrupted by user (Ctrl+C).{WHITE}")

        except Exception:
            pass

        finally:
            log_file.close()
            restore_unix_terminal_mode(_term_settings)

        content = ""
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8", errors="ignore")

        if canceled:
            sys.stdout.write("\033[2A\r")
            filled = max(0, last_pct) // 4
            bar = FULL[:filled] + EMPTY[:25 - filled]
            info_str = f" (Item {last_pl_idx}/{last_pl_tot})" if last_pl_idx and last_pl_tot else ""
            sys.stdout.write(f"\033[K{CYAN}Progress:  [{bar}] {max(0, last_pct)}%{info_str}\033[0m\n")
            sys.stdout.write(f"\033[K{RED}[{idx}/{total}] Canceled by user.{WHITE}\n\n")
            sys.stdout.flush()
            cleanup_log(log_path)
            canceled_count += 1
            stop_all_batch = True
            break

        return_code = proc.returncode
        success = (return_code == 0) and ("error" not in content.lower() and "unable" not in content.lower())
        final_pct = 100 if success else (last_pct if last_pct >= 0 else 0)

        filled = final_pct // 4
        bar = FULL[:filled] + EMPTY[:25 - filled]
        info_str = f" (Item {last_pl_idx}/{last_pl_tot})" if last_pl_idx and last_pl_tot else ""
        sys.stdout.write(f"\033[2A\r{CYAN}Progress:  [{bar}] {final_pct}%{info_str}\033[0m\033[K\n")

        pl_tot_parsed, pl_succ_parsed, pl_fail_parsed = parse_playlist_log_stats(content, last_pl_tot)

        if last_pl_tot and last_pl_tot > 1:
            print(f"{CYAN}[PLAYLIST DETAILS] Total: {pl_tot_parsed} | Succeeded: {pl_succ_parsed} | Failed: {pl_fail_parsed}{WHITE}")

        if not success:
            sys.stdout.write(f"{RED}[{idx}/{total}] Download failed!{WHITE}\n\n")
            failed_count += 1
        else:
            sys.stdout.write(f"{GREEN}[{idx}/{total}] Downloaded successfully!{WHITE}\n\n")
            successful_count += 1

        sys.stdout.flush()
        cleanup_log(log_path)

    print(f"{GREEN}[DONE] Processed {total} item(s): {successful_count} succeeded, {failed_count} failed, {canceled_count} canceled.{WHITE}")
    flush_input()
    input("Press Enter to continue...")
    flush_input()

def cleanup_log(log_path: Path):
    try:
        if log_path.exists():
            log_path.unlink()
    except OSError:
        pass


# --- Download Sub-Menus ---

def menu_download_video():
    while True:
        clear()
        print_header_simple("Download Video Menu")
        lines = [
            ccenter(f"{YELLOW}Select [0] to go to MAIN MENU{WHITE}", 52),
            "====================================================",
            " [1] Best Quality - MKV",
            " [2] Best Quality - MP4",
            " [3] Custom (Advance Video Download)",
            "====================================================",
        ]
        cblock("\n".join(lines))
        print("\n")

        choice = input("Select an option (0-3): ").strip()
        if choice == "0":
            break
        elif choice == "1":
            action_video_mkv()
        elif choice == "2":
            action_video_mp4()
        elif choice == "3":
            action_custom(audio_only=False)
        else:
            print(f"\n{RED}[ERROR] Invalid option!{WHITE}")
            time.sleep(1)

def menu_download_audio():
    while True:
        clear()
        print_header_simple("Download Audio Menu")
        lines = [
            ccenter(f"{YELLOW}Select [0] to go to MAIN MENU{WHITE}", 52),
            "====================================================",
            " [1] Best Quality - MP3",
            " [2] Best Quality - M4A",
            " [3] Custom (Advance Audio Download)",
            "====================================================",
        ]
        cblock("\n".join(lines))
        print("\n")

        choice = input("Select an option (0-3): ").strip()
        if choice == "0":
            break
        elif choice == "1":
            action_audio_mp3()
        elif choice == "2":
            action_audio_m4a()
        elif choice == "3":
            action_custom(audio_only=True)
        else:
            print(f"\n{RED}[ERROR] Invalid option!{WHITE}")
            time.sleep(1)

def menu_download_playlist():
    while True:
        clear()
        print_header_simple("Download Playlist Menu")
        lines = [
            ccenter(f"{YELLOW}Select [0] to go to MAIN MENU{WHITE}", 52),
            "====================================================",
            " [1] Videos (Best Quality - MP4)",
            " [2] Audios (Best Quality - MP3)",
            " [3] Audios (Best Quality - M4A)",
            "====================================================",
        ]
        cblock("\n".join(lines))
        print("\n")

        choice = input("Select an option (0-3): ").strip()
        if choice == "0":
            break
        elif choice == "1":
            action_playlist_video_mp4()
        elif choice == "2":
            action_playlist_audio_mp3()
        elif choice == "3":
            action_playlist_audio_m4a()
        else:
            print(f"\n{RED}[ERROR] Invalid option!{WHITE}")
            time.sleep(1)

def action_video_mkv():
    urls = prompt_urls_input("DOWNLOAD BEST QUALITY (MKV)")
    if not urls:
        return
    download_batch_with_bar(urls, "DOWNLOAD BEST QUALITY (MKV)",
                           ["-f", "bv*+ba/b", "--merge-output-format", "mkv", "--no-playlist"])

def action_video_mp4():
    urls = prompt_urls_input("DOWNLOAD BEST QUALITY (MP4)")
    if not urls:
        return
    download_batch_with_bar(urls, "DOWNLOAD BEST QUALITY (MP4)",
                           ["-f", "bv*+ba/b", "--merge-output-format", "mp4", "--no-playlist"])

# --- Audio Download Handlers ---

def action_audio_mp3():
    urls = prompt_urls_input("DOWNLOAD BEST QUALITY (MP3)")
    if not urls:
        return
    download_batch_with_bar(urls, "DOWNLOAD BEST QUALITY (MP3)",
                           ["-x", "--audio-format", "mp3", "--audio-quality", "0", "--no-playlist"])

def action_audio_m4a():
    urls = prompt_urls_input("DOWNLOAD BEST QUALITY (M4A)")
    if not urls:
        return
    download_batch_with_bar(urls, "DOWNLOAD BEST QUALITY (M4A)",
                           ["-x", "--audio-format", "m4a", "--audio-quality", "0", "--no-playlist"])

# --- Playlist Download Handlers ---

def action_playlist_video_mp4():
    urls = prompt_urls_input("DOWNLOAD PLAYLIST - VIDEOS (MP4)")
    if not urls:
        return
    download_batch_with_bar(urls, "DOWNLOAD PLAYLIST - VIDEOS (MP4)",
                           ["-f", "bv*+ba/b", "--merge-output-format", "mp4", "--yes-playlist"])

def action_playlist_audio_mp3():
    urls = prompt_urls_input("DOWNLOAD PLAYLIST - AUDIOS (MP3)")
    if not urls:
        return
    download_batch_with_bar(urls, "DOWNLOAD PLAYLIST - AUDIOS (MP3)",
                           ["-x", "--audio-format", "mp3", "--audio-quality", "0", "--yes-playlist"])

def action_playlist_audio_m4a():
    urls = prompt_urls_input("DOWNLOAD PLAYLIST - AUDIOS (M4A)")
    if not urls:
        return
    download_batch_with_bar(urls, "DOWNLOAD PLAYLIST - AUDIOS (M4A)",
                           ["-x", "--audio-format", "m4a", "--audio-quality", "0", "--yes-playlist"])


# --- Custom Format Handler ---

def display_custom_formats(url: str, audio_only: bool = False) -> bool:
    cmd = [
        str(YTDLP),
        "--dump-json",
        "--no-playlist",
        "--no-warnings",
        url
    ]
    
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", **get_sp_kwargs())
    if proc.returncode != 0 or not proc.stdout.strip():
        return False

    try:
        data = json.loads(proc.stdout)
        raw_formats = data.get("formats", [])
    except Exception:
        return False

    if not raw_formats:
        return False

    mp4_videos, webm_videos, other_videos = [], [], []
    m4a_audios, webm_audios, other_audios = [], [], []

    for f in raw_formats:
        vcodec = str(f.get("vcodec", "")).lower()
        acodec = str(f.get("acodec", "")).lower()
        ext = str(f.get("ext", "")).lower()

        is_audio_only = (vcodec == "none" or not vcodec) and acodec != "none"
        is_video = vcodec != "none" and vcodec != ""

        if is_audio_only:
            if ext == "m4a":
                m4a_audios.append(f)
            elif ext in ("webm", "opus"):
                webm_audios.append(f)
            else:
                other_audios.append(f)
        elif is_video and not audio_only:
            if ext == "mp4":
                mp4_videos.append(f)
            elif ext == "webm":
                webm_videos.append(f)
            else:
                other_videos.append(f)

    def sort_video_key(item):
        return (item.get("height") or 0, item.get("width") or 0, item.get("tbr") or item.get("vbr") or 0)

    def sort_audio_key(item):
        return (item.get("abr") or item.get("tbr") or 0)

    if not audio_only:
        mp4_videos.sort(key=sort_video_key, reverse=True)
        webm_videos.sort(key=sort_video_key, reverse=True)
        other_videos.sort(key=sort_video_key, reverse=True)

    m4a_audios.sort(key=sort_audio_key, reverse=True)
    webm_audios.sort(key=sort_audio_key, reverse=True)
    other_audios.sort(key=sort_audio_key, reverse=True)

    def get_size_str(f):
        sz = f.get("filesize") or f.get("filesize_approx")
        if sz:
            mb = sz / (1024 * 1024)
            if mb >= 1024:
                return f"{mb/1024:.2f} GiB"
            return f"{mb:.2f} MiB"
        return "N/A"

    def print_video_table(title, items):
        if not items:
            return
        print(f"{WHITE}[{title}]{RESET}")
        header = f"  {'ID':<10} {'EXT':<6} {'RESOLUTION':<14} {'FPS':<6} {'FILESIZE':<12} {'CODEC':<18} {'NOTE'}"
        print(f"{CYAN}{header}{RESET}")
        print(f"{CYAN}  " + "-" * 78 + f"{RESET}")
        for f in items:
            fid = str(f.get("format_id", ""))
            ext = str(f.get("ext", ""))
            w, h = f.get("width"), f.get("height")
            res = f"{w}x{h}" if w and h else (f.get("resolution") or "N/A")
            fps_val = f.get("fps")
            fps = f"{int(fps_val)}fps" if fps_val else "N/A"
            size = get_size_str(f)
            vcodec = (f.get("vcodec") or "N/A").split(".")[0]
            note = f.get("format_note") or ""
            
            line = f"  {fid:<10} {ext:<6} {res:<14} {fps:<6} {size:<12} {vcodec:<18} {note}"
            print(f"{CYAN}{line}{RESET}")
        print()

    def print_audio_table(title, items):
        if not items:
            return
        print(f"{WHITE}[{title}]{RESET}")
        header = f"  {'ID':<10} {'EXT':<6} {'BITRATE':<12} {'FILESIZE':<12} {'CODEC':<18} {'NOTE'}"
        print(f"{CYAN}{header}{RESET}")
        print(f"{CYAN}  " + "-" * 72 + f"{RESET}")
        for f in items:
            fid = str(f.get("format_id", ""))
            ext = str(f.get("ext", ""))
            abr = f.get("abr") or f.get("tbr")
            bitrate = f"{int(abr)}k" if abr else "N/A"
            size = get_size_str(f)
            acodec = (f.get("acodec") or "N/A").split(".")[0]
            note = f.get("format_note") or ""
            
            line = f"  {fid:<10} {ext:<6} {bitrate:<12} {size:<12} {acodec:<18} {note}"
            print(f"{CYAN}{line}{RESET}")
        print()

    if not audio_only:
        print_video_table("mp4 video options", mp4_videos)
        print_video_table("webm video options", webm_videos)
        if other_videos:
            print_video_table("other video options", other_videos)
        
    print_audio_table("m4a audio options", m4a_audios)
    print_audio_table("webm audio options", webm_audios)
    if other_audios:
        print_audio_table("other audio options", other_audios)

    return True

def action_custom(audio_only: bool = False):
    if not ensure_ytdlp_exists():
        return

    title = "CUSTOM ADVANCE AUDIO DOWNLOAD" if audio_only else "CUSTOM ADVANCE VIDEO DOWNLOAD"
    urls = prompt_urls_input(title)
    if not urls:
        return

    print()
    print(f"{YELLOW}[INFO] Fetching available formats...{WHITE}")
    print()

    success = display_custom_formats(urls[0], audio_only=audio_only)

    if not success:
        result = subprocess.run([str(YTDLP), "-F", urls[0]], capture_output=True, text=True, encoding="utf-8", errors="ignore", **get_sp_kwargs())
        output = (result.stdout or "") + (result.stderr or "")
        if output.strip():
            lblock(output.strip())

    print()
    fmt = input("Enter desired format code (e.g., 137+140 or best) or select option [0]: ").strip()

    if not fmt or fmt == "0":
        return

    extra_args = ["-f", fmt]
    if audio_only:
        extra_args.insert(0, "-x")

    download_batch_with_bar(urls, title, extra_args)


# --- Updates & Downloads ---

def get_local_ytdlp_version() -> str:
    yt_exe = BIN_DIR / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    if not yt_exe.exists():
        return "[File not found: install]"
    try:
        res = subprocess.run(
            [str(yt_exe), "--version"], 
            capture_output=True, 
            text=True, 
            encoding="utf-8",
            errors="ignore",
            timeout=6,
            **get_sp_kwargs()
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
        return "installed"
    except Exception:
        return "installed"

def get_local_ffmpeg_version() -> str:
    ffmpeg_exe = BIN_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not ffmpeg_exe.exists():
        return "[File not found: install]"
    try:
        res = subprocess.run(
            [str(ffmpeg_exe), "-version"], 
            capture_output=True, 
            text=True, 
            encoding="utf-8",
            errors="ignore",
            timeout=6,
            **get_sp_kwargs()
        )
        if res.returncode == 0 and res.stdout:
            first_line = res.stdout.splitlines()[0]
            parts = first_line.split()
            if len(parts) >= 3 and parts[1].lower() == "version":
                return parts[2].split("-")[0]
            return "installed"
        return "installed"
    except Exception:
        return "installed"

def fetch_latest_release_tag(repo_path: str) -> str:
    url = f"https://github.com/{repo_path}/releases/latest"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            method="HEAD",
        )
        ctx = create_secure_ssl_context()
        with urlopen_with_fallback(req, ctx, timeout=8) as resp:
            final_url = resp.geturl()

        if "/releases/tag/" in final_url:
            tag = final_url.rsplit("/releases/tag/", 1)[-1]
            return urllib.parse.unquote(tag)
        return "No Release"

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "No Release"
        if e.code == 403:
            return "Rate Limited"
        return f"HTTP {e.code}"
    except urllib.error.URLError:
        return "No Internet"
    except Exception:
        return "Unavailable"

_RELEASE_CACHE = {}
CACHE_TTL_SECONDS = 300

def get_cached_release_tag(repo_path: str, force: bool = False) -> str:
    now = time.time()
    cached = _RELEASE_CACHE.get(repo_path)
    if not force and cached and (now - cached[1] < CACHE_TTL_SECONDS):
        return cached[0]
    tag = fetch_latest_release_tag(repo_path)
    _RELEASE_CACHE[repo_path] = (tag, now)
    return tag

def format_update_status(local_ver: str, latest_tag: str) -> str:
    non_version_statuses = ("Unavailable", "No Release", "Rate Limited", "No Internet")
    if latest_tag in non_version_statuses or latest_tag.startswith("HTTP "):
        return latest_tag

    if local_ver == "installed":
        return "Installed"

    clean_local = local_ver.lstrip("v").split("-")[0].strip()
    clean_latest = latest_tag.lstrip("v").split("-")[0].strip()

    if clean_local == clean_latest:
        return "Up to date"

    return latest_tag if latest_tag.startswith("v") else f"v{latest_tag}"

def action_install_update_menu():
    refresh = True
    while True:
        if refresh:
            clear()
            print_header_simple("Install / Update")
            print(f"{YELLOW}   [INFO] Fetching latest versions from GitHub...{WHITE}\n")

            yt_local = get_local_ytdlp_version()
            ff_local = get_local_ffmpeg_version()
            app_local = CURRENT_VERSION

            yt_latest = get_cached_release_tag("yt-dlp/yt-dlp", force=True)
            ff_latest = get_cached_release_tag("GyanD/codexffmpeg", force=True)
            app_latest = get_cached_release_tag(f"{REPO_OWNER}/{REPO_NAME}", force=True)

            yt_status = format_update_status(yt_local, yt_latest)
            ff_status = format_update_status(ff_local, ff_latest)
            app_status = format_update_status(app_local, app_latest)

            def fmt_ver(ver):
                if "not found" in ver.lower() or ver == "installed":
                    return ver
                return ver if ver.startswith("v") else f"v{ver}"

            yt_disp = fmt_ver(yt_local)
            ff_disp = fmt_ver(ff_local)
            app_disp = fmt_ver(app_local)
            refresh = False

        clear()
        print_header_simple("Install / Update")

        menu_content = (
            f" Current versions                  Latest versions\n"
            f"------------------                ------------------\n"
            f"[1] yt-dlp                          ({yt_status})\n"
            f"    {yt_disp:<24}\n"
            f"\n"
            f"[2] FFmpeg                          ({ff_status})\n"
            f"    {ff_disp:<24}\n"
            f"\n"
            f"[3] My Downloader                   ({app_status})\n"
            f"    {app_disp:<24}\n"
            f"===================================================\n"
            f"        Select [0] to go back, [R] to refresh"
        )
        
        cblock(menu_content)
        print()

        print(f"{YELLOW}")
        cline("Tip: If version status isn't shown, press [R] to refresh.")
        print(f"{WHITE}")

        choice = input("        Select an option (0-3, R): ").strip().lower()
        
        if choice == "0":
            break
        elif choice == "r":
            refresh = True
        elif choice == "1":
            action_update_ytdlp()
            refresh = True
        elif choice == "2":
            action_update_ffmpeg()
            refresh = True
        elif choice == "3":
            action_update()
            refresh = True
        else:
            print()
            print(f"        {RED}[ERROR] Invalid option!{WHITE}")
            time.sleep(1)


class RangeNotSupportedError(Exception):
    pass

class DownloadCanceledError(Exception):
    """Raised when a chunk notices cancel_event was set by a sibling
    failure elsewhere, so it can stop promptly instead of running toward
    its own full timeout while the batch is already being torn down."""
    pass

def download_chunk(url, start_byte, end_byte, part_num, temp_dir, ctx, progress_lock, progress_data, cancel_event=None):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Range": f"bytes={start_byte}-{end_byte}"
    }
    part_file = temp_dir / f"part_{part_num}.tmp"
    
    for attempt in range(3):
        bytes_written_this_attempt = 0
        try:
            req = urllib.request.Request(url, headers=headers)
            with urlopen_with_fallback(req, ctx, timeout=30) as resp, open(part_file, "wb") as f:
                if resp.status != 206:
                    raise RangeNotSupportedError(
                        f"Server returned {resp.status} instead of 206 for a ranged request."
                    )
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        # A sibling chunk failed elsewhere -- stop promptly
                        # instead of continuing to download toward our own
                        # 30s timeout while the whole batch is already dead.
                        with progress_lock:
                            progress_data["downloaded"] -= bytes_written_this_attempt
                        raise DownloadCanceledError("Canceled: a sibling chunk failed")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    bytes_written_this_attempt += len(chunk)
                    with progress_lock:
                        progress_data["downloaded"] += len(chunk)
            return part_file, start_byte
        except DownloadCanceledError:
            raise  # don't retry -- the whole batch is being torn down
        except RangeNotSupportedError:
            with progress_lock:
                progress_data["downloaded"] -= bytes_written_this_attempt
            raise
        except Exception:
            with progress_lock:
                progress_data["downloaded"] -= bytes_written_this_attempt
            if attempt == 2:
                raise
            time.sleep(0.5)
            
    return part_file, start_byte


class DownloadSizeExceededError(Exception):
    pass

def _download_single_stream(url, dest_file, ctx, timeout, progress_lock, progress_data, expected_total=None):
    hard_ceiling = int(expected_total * 1.10) if expected_total else None

    req_get = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen_with_fallback(req_get, ctx, timeout=timeout) as resp, open(dest_file, "wb") as f:
        downloaded_this_stream = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            downloaded_this_stream += len(chunk)
            with progress_lock:
                progress_data["downloaded"] += len(chunk)
            if hard_ceiling and downloaded_this_stream > hard_ceiling:
                raise DownloadSizeExceededError(
                    f"Received {downloaded_this_stream / (1024*1024):.1f} MB, which exceeds expected size."
                )

def download_with_progress(url, dest_path, ctx, label="Downloading", timeout=30):
    cfg = load_config()
    num_threads = cfg.get("update_threads", 4)
    FIFTEEN_MB = 15 * 1024 * 1024

    total = None
    accept_ranges = False

    try:
        req_head = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        with urlopen_with_fallback(req_head, ctx, timeout=timeout) as resp:
            content_length = resp.getheader("Content-Length")
            ranges_header = resp.getheader("Accept-Ranges", "").lower()
            if content_length and content_length.isdigit():
                total = int(content_length)
            if total and ranges_header != "none":
                accept_ranges = True
    except Exception:
        total = None
        accept_ranges = False

    if not total or not accept_ranges or (total <= FIFTEEN_MB and num_threads > 1) or total < (1024 * 1024):
        num_threads = 1

    if num_threads > 1:
        print(f"{CYAN}[INFO] Using {num_threads}-way parallel download.{WHITE}")
    else:
        reason = ("server didn't report a file size" if not total
                   else "server doesn't support partial/ranged downloads" if not accept_ranges
                   else "file is under 15MB or set to single-thread mode" if total <= FIFTEEN_MB
                   else "single-thread mode selected")
        print(f"{CYAN}[INFO] Using single-stream download ({reason}).{WHITE}")

    progress_data = {"downloaded": 0, "done": False, "printed_lines": 0}
    progress_lock = threading.Lock()
    temp_dir = Path(tempfile.mkdtemp())

    def update_ui():
        first_draw = True
        while not progress_data["done"]:
            mb = progress_data["downloaded"] / (1024 * 1024)
            prefix = "" if first_draw else "\033[1A"
            if total and total > 0:
                pct = min(100, int(progress_data["downloaded"] * 100 / total))
                total_mb = total / (1024 * 1024)
                sys.stdout.write(f"{prefix}\r\033[K{CYAN}{label}: {mb:6.1f} / {total_mb:.1f} MB ({pct}%){WHITE}   \n")
            else:
                sys.stdout.write(f"{prefix}\r\033[K{CYAN}{label}: {mb:6.1f} MB{WHITE}   \n")
            sys.stdout.flush()
            if first_draw:
                progress_data["printed_lines"] += 1
                first_draw = False
            time.sleep(0.1)

    ui_thread = threading.Thread(target=update_ui, daemon=True)
    ui_thread.start()

    download_success = False
    temp_assembled_file = temp_dir / "assembled_output.bin"

    try:
        if num_threads > 1:
            chunk_size = total // num_threads
            ranges = []
            for i in range(num_threads):
                start = i * chunk_size
                end = total - 1 if i == num_threads - 1 else (start + chunk_size - 1)
                ranges.append((start, end, i))

            try:
                cancel_event = threading.Event()
                with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                    futures = [
                        executor.submit(download_chunk, url, r[0], r[1], r[2], temp_dir, ctx, progress_lock, progress_data, cancel_event)
                        for r in ranges
                    ]
                    try:
                        results = [f.result() for f in concurrent.futures.as_completed(futures)]
                    except Exception:
                        # Signal every sibling immediately -- without this,
                        # already-running chunks have no way to know a
                        # sibling failed, and would otherwise keep
                        # downloading toward their own full 30s timeout
                        # before the executor's blocking shutdown could
                        # even complete.
                        cancel_event.set()
                        if sys.version_info >= (3, 9):
                            executor.shutdown(wait=False, cancel_futures=True)
                        else:
                            executor.shutdown(wait=False)
                        raise

                if len(results) == num_threads:
                    results.sort(key=lambda x: x[1])
                    with open(temp_assembled_file, "wb") as final_file:
                        for part_path, _ in results:
                            with open(part_path, "rb") as pf:
                                shutil.copyfileobj(pf, final_file)
                            part_path.unlink(missing_ok=True)
                    download_success = True

            except Exception:
                for leftover in temp_dir.glob("part_*.tmp"):
                    leftover.unlink(missing_ok=True)
                with progress_lock:
                    progress_data["downloaded"] = 0

        if not download_success:
            _download_single_stream(url, temp_assembled_file, ctx, timeout, progress_lock, progress_data, expected_total=total)

        dest_path_obj = Path(dest_path)
        dest_path_obj.parent.mkdir(parents=True, exist_ok=True)
        if dest_path_obj.exists():
            dest_path_obj.unlink(missing_ok=True)
        shutil.move(str(temp_assembled_file), str(dest_path_obj))

    finally:
        progress_data["done"] = True
        ui_thread.join(timeout=1.0)
        shutil.rmtree(temp_dir, ignore_errors=True)

    if total and total > 0:
        total_mb = total / (1024 * 1024)
        prefix = "\033[1A" if progress_data["printed_lines"] > 0 else ""
        sys.stdout.write(f"{prefix}\r\033[K{CYAN}{label}: {total_mb:.1f} / {total_mb:.1f} MB (100%){WHITE}   \n")
        sys.stdout.flush()

def action_update_ytdlp():
    clear()
    print_header_simple("UPDATING YT-DLP")
    if not YTDLP.exists():
        print(f"{YELLOW}[INFO] yt-dlp not found in bin folder. Installing automatically...{WHITE}")
    else:
        print(f"{YELLOW}[INFO] Downloading the latest yt-dlp.exe directly from GitHub...{WHITE}")
    print()
    
    url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" if os.name == "nt" else "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        ctx = create_secure_ssl_context()
        download_with_progress(url, YTDLP, ctx, label="Downloading yt-dlp")
        if os.name != "nt":
            YTDLP.chmod(0o755)
        print()
        print(f"{GREEN}[SUCCESS] yt-dlp is installed and up-to-date!{WHITE}")
    except Exception as e:
        print()
        print(f"{RED}[ERROR] Update failed. Check your connection. ({e}){WHITE}")
    print()
    flush_input()
    input("Press Enter to continue...")

def action_update_ffmpeg():
    clear()
    print_header_simple("UPDATING FFMPEG")
    ffmpeg_exe = BIN_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not ffmpeg_exe.exists():
        print(f"{YELLOW}[INFO] FFmpeg not found in bin folder. Installing automatically...{WHITE}")
    else:
        print(f"{YELLOW}[INFO] Downloading latest FFmpeg build...{WHITE}")
    print()

    import platform as _platform

    system = _platform.system()
    machine = _platform.machine().lower()

    if system == "Windows":
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        archive_type = "zip"
    elif system == "Linux":
        if machine in ("x86_64", "amd64"):
            url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
            archive_type = "tar.xz"
        else:
            url = None
    elif system == "Darwin":
        if machine == "arm64":
            url = None
        else:
            url = "https://evermeet.cx/ffmpeg/getrelease/zip"
            archive_type = "zip"
    else:
        url = None

    if url is None:
        print(f"{RED}[ERROR] No automatic FFmpeg install available for this platform ({system} {machine}).{WHITE}")
        if system == "Darwin" and machine == "arm64":
            print(f"{YELLOW}[INFO] Install it via Homebrew instead:  brew install ffmpeg{WHITE}")
        else:
            print(f"{YELLOW}[INFO] Please install FFmpeg manually and ensure it's on your PATH, or place it in:{WHITE}")
            print(f"{YELLOW}       {BIN_DIR}{WHITE}")
        print()
        flush_input()
        input("Press Enter to continue...")
        return

    tmp_dir = Path(tempfile.gettempdir())
    archive_path = tmp_dir / f"ffmpeg_download.{archive_type.replace('.', '_')}"
    extract_dir = tmp_dir / "ffmpeg_extracted"

    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        ctx = create_secure_ssl_context()
        download_with_progress(url, archive_path, ctx, label="Downloading FFmpeg")

        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True)

        if archive_type == "zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_dir)
        else:
            import tarfile
            with tarfile.open(archive_path, "r:xz") as tf:
                # Build the except-types tuple conditionally rather than
                # falling back to an empty tuple -- `except (TypeError, ())`
                # itself raises "catching classes that do not inherit from
                # BaseException is not allowed" on Python versions where
                # FilterError doesn't exist, which would be worse than the
                # bug it's meant to fix.
                except_types = (TypeError,)
                if hasattr(tarfile, "FilterError"):
                    except_types = except_types + (tarfile.FilterError,)
                try:
                    tf.extractall(extract_dir, filter="data")
                except except_types:
                    # TypeError: Python < 3.12, no filter param at all.
                    # FilterError: filter="data" rejected something in the
                    # archive (e.g. certain symlinks) -- fall back to an
                    # unfiltered extraction rather than failing the update
                    # outright, since we trust this specific, pinned source.
                    tf.extractall(extract_dir)

        bin_folder = None
        for path in extract_dir.rglob("ffmpeg.exe" if os.name == "nt" else "ffmpeg"):
            bin_folder = path.parent
            break

        if bin_folder is None:
            print(f"{YELLOW}[DEBUG] Could not locate 'ffmpeg' binary. Extracted contents:{WHITE}")
            found_any = False
            for p in sorted(extract_dir.rglob("*")):
                found_any = True
                marker = "*" if p.is_file() else "/"
                print(f"  {p.relative_to(extract_dir)}{marker}")
            if not found_any:
                print(f"  {RED}(extract_dir is completely empty -- archive extraction produced nothing){WHITE}")
            print()

        if bin_folder:
            for exe in ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe") if os.name == "nt" else ("ffmpeg", "ffprobe", "ffplay"):
                src = bin_folder / exe
                if src.exists():
                    dest = BIN_DIR / exe
                    shutil.copy2(src, dest)
                    if os.name != "nt":
                        dest.chmod(0o755)

        archive_path.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)
    except Exception as e:
        print(f"{RED}[ERROR] FFmpeg update failed. Check your connection. ({e}){WHITE}")
        print()
        flush_input()
        input("Press Enter to continue...")
        return

    if ffmpeg_exe.exists():
        print(f"{GREEN}[SUCCESS] FFmpeg installed/updated successfully!{WHITE}")
        if system == "Darwin" and machine != "arm64":
            print(f"{YELLOW}[INFO] Note: ffprobe/ffplay aren't bundled with this source on macOS -- only ffmpeg itself.{WHITE}")
    else:
        print(f"{RED}[ERROR] FFmpeg installation failed.{WHITE}")
    print()
    flush_input()
    input("Press Enter to continue...")

def action_update():
    clear()
    print_header_simple("UPDATING MY DOWNLOADER")
    print(f"{YELLOW}[INFO] Checking for latest release on GitHub...{WHITE}")
    print()

    download_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/latest/download/{urllib.parse.quote(GITHUB_EXE_FILENAME)}"

    try:
        print(f"{CYAN}[1/1] Downloading latest binary...")
        ctx = create_secure_ssl_context()
        base_folder = get_base_dir()
        temp_exe = base_folder / "My_Downloader_temp.exe"
        download_with_progress(download_url, temp_exe, ctx, label="Downloading update")

        print()
        print(f"{GREEN}[SUCCESS] Download complete!{WHITE}")
        print(f"{YELLOW}[INFO] Preserving shortcuts and restarting to apply update...{WHITE}")
        sys.stdout.flush()

        is_frozen = getattr(sys, 'frozen', False)
        current_exe = Path(sys.executable).resolve() if is_frozen else (base_folder / LOCAL_EXE_FILENAME)
        target_exe = base_folder / LOCAL_EXE_FILENAME

        rename_failed = False
        if current_exe.exists():
            old_exe = base_folder / f"My Downloader.old.{int(time.time())}.exe"
            for attempt in range(5):
                try:
                    os.replace(current_exe, old_exe)
                    break
                except PermissionError:
                    if attempt == 4:
                        rename_failed = True
                    else:
                        time.sleep(0.4)

        if rename_failed and os.name == "nt" and is_frozen:
            bat_script = base_folder / "update.bat"
            bat_content = (
                "@echo off\r\n"
                "timeout /t 2 /nobreak > NUL\r\n"
                f'move /y "{temp_exe}" "{target_exe}"\r\n'
                f'start "" "{target_exe}"\r\n'
                'del "%~f0"\r\n'
            )
            bat_script.write_text(bat_content)
            subprocess.Popen(["cmd.exe", "/c", str(bat_script)],
                              creationflags=subprocess.CREATE_NO_WINDOW)
            sync_shortcuts()
            os._exit(0)
        elif rename_failed:
            raise PermissionError(
                f"Could not replace the running executable ({current_exe}); "
                "it may still be locked by this process."
            )

        os.replace(temp_exe, target_exe)
        
        sync_shortcuts()

        if os.name == "nt":
            subprocess.Popen(["explorer.exe", str(target_exe.resolve())])
        else:
            subprocess.Popen([str(target_exe.resolve())])
        os._exit(0)

    except Exception as e:
        print()
        print(f"{RED}[ERROR] Self-update failed: {e}{WHITE}")
        print(f"{YELLOW}[INFO] Verify internet connection and check GitHub releases.{WHITE}")
        print()
        flush_input()
        input("Press Enter to continue...")


# --- Version Checks ---

def is_update_needed(local_ver: str, latest_tag: str) -> bool:
    if "not found" in local_ver.lower():
        return True

    if latest_tag in ("Unavailable", "No Release", "Rate Limited", "No Internet") or latest_tag.startswith("HTTP "):
        return False

    clean_local = local_ver.lstrip("v").strip()
    clean_latest = latest_tag.lstrip("v").strip()
    return clean_local != clean_latest

def check_for_updates():
    global UPDATE_AVAILABLE
    try:
        ffmpeg_exe = BIN_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        yt_missing = not YTDLP.exists()
        ff_missing = not ffmpeg_exe.exists()

        if yt_missing or ff_missing:
            UPDATE_AVAILABLE = True
            return

        yt_local = get_local_ytdlp_version()
        ff_local = get_local_ffmpeg_version()
        app_local = CURRENT_VERSION

        yt_latest = get_cached_release_tag("yt-dlp/yt-dlp")
        ff_latest = get_cached_release_tag("GyanD/codexffmpeg")
        app_latest = get_cached_release_tag(f"{REPO_OWNER}/{REPO_NAME}")

        yt_has_update = is_update_needed(yt_local, yt_latest)
        ff_has_update = is_update_needed(ff_local, ff_latest)
        app_has_update = is_update_needed(app_local, app_latest)

        UPDATE_AVAILABLE = yt_has_update or ff_has_update or app_has_update
    except Exception:
        ffmpeg_exe = BIN_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        UPDATE_AVAILABLE = (not YTDLP.exists()) or (not ffmpeg_exe.exists())


# --- Startup & Main ---

def action_exit():
    clear()
    logo = r"""
                   ##########                   
              ####################              
           ##########################           
         ##############################         
       ##################################       
      ##########++########################      
     #######+------######+--+######+++#####     
    ###++----------+###+-----+####+----+#####    
   ###+------+###--##+--+---+##+-----+#######   
   ##+----+#####+-++--+#+--+#+-----++########   
  #############+-+--+##+--++--++--+###########  
  ############+----###+--+--+#+--+############  
  ##########+----+##+---+-+##---########+#####  
  #########+----+###-----+#+---#+---------+###  
   #######+---+###+----+##+---##+--------+###   
   ######----+###-----###+---+####+------####   
    ####+---+###+---+####+---+++--++----####    
     ####+-+#####--######+------+####++####     
      #####################+++############      
       ##################################       
         ##############################         
           ##########################           
              ####################              
                   ##########                   
"""
    cblock(f"{DEFAULT_COLOR}{logo}")
    print(f"{WHITE}")

    cline("  ♥ THANK YOU FOR USING ♥")
    print(f"{DEFAULT_COLOR}")
    cline("Git handle: Y2m777a5 | Git Repo: github.com/Y2m777a5/My-Downloader")
    
    time.sleep(3)
    sys.exit(0)

def cleanup_old_update_files():
    for old_file in get_base_dir().glob("My Downloader.old.*.exe"):
        for attempt in range(5):
            try:
                old_file.unlink()
                break
            except OSError:
                time.sleep(0.3)

def main():
    if os.name == "nt":
        os.system("title My Downloader")
    setup_console()
    print(WHITE, end="")

    cleanup_old_update_files()
    cleanup_partials()
    sync_shortcuts()
    threading.Thread(target=check_for_updates, daemon=True).start()

    actions = {
        "1": menu_download_video,
        "2": menu_download_audio,
        "3": menu_download_playlist,
        "4": action_install_update_menu,
        "5": action_settings_menu,
        "6": action_exit
    }
    while True:
        print_menu()
        choice = input("Select an option (1-6): ").strip()
        action = actions.get(choice)
        if action:
            action()
        else:
            print(f"{RED}[ERROR] Invalid option! Please enter a number between 1 and 6.{WHITE}")
            time.sleep(1.5)

if __name__ == "__main__":
    main()
