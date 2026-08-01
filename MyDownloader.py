"""
My Downloader (Python port of the original .bat script)

Requires:
  - bin\yt-dlp.exe  (or bin/yt-dlp on non-Windows)
  - bin\ffmpeg.exe, ffprobe.exe, ffplay.exe (optional, used for merging/audio extraction)

Run with:  python downloader.py
"""

# --- Configuration & Metadata ---
VERSION = "2.2.8.2"
CURRENT_VERSION = VERSION
REPO_OWNER = "Y2m777a5"
REPO_NAME = "My-Downloader"       
GITHUB_EXE_FILENAME = "My Downloader.exe"

import os
import ssl
import sys
import time
import shutil
import zipfile
import tempfile
import subprocess
import json
import threading
import urllib.request
import urllib.parse
from pathlib import Path

# Platform-specific imports for keyboard input and Win32 API calls
try:
    import msvcrt
except ImportError:
    msvcrt = None

try:
    import ctypes
    from ctypes import wintypes
except ImportError:
    ctypes = None

# Default console dimensions
CONSOLE_COLS = 120
CONSOLE_LINES = 40
MAX_CONSOLE_COLS = 220  # Hard ceiling for screen width


def get_base_dir() -> Path:
    """
    Returns the absolute directory of the script or compiled executable.
    Handles both standard Python execution and PyInstaller frozen bundles.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


# --- ANSI Color Palette Definitions ---
WHITE = "\033[97m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
GREEN = "\033[38;2;0;254;0m"
RESET = "\033[0m"
DEFAULT_COLOR = "\033[38;2;238;128;32m"

# Application Path Setup
BASE_DIR = get_base_dir()
BIN_DIR = BASE_DIR / "bin"
OUT_DIR = BASE_DIR / "Downloads"
YTDLP = BIN_DIR / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")

# Create missing runtime directories
OUT_DIR.mkdir(exist_ok=True)
BIN_DIR.mkdir(exist_ok=True)

# Global flag to track available updates across components
UPDATE_AVAILABLE = False

# Visual Progress Bar Elements
FULL = "█" * 25
EMPTY = "░" * 25


# --- Global SSL Context Helper ---
def create_secure_ssl_context() -> ssl.SSLContext:
    """
    Creates an SSL context that attempts standard certificate validation,
    falling back to unverified mode if local OS/Python CA bundles are missing.
    """
    try:
        return ssl.create_default_context()
    except Exception:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


# --- Terminal Input Management ---
def flush_input():
    """Flushes queued extra keypresses or trailing newlines from the terminal buffer."""
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


def check_q_pressed() -> bool:
    """
    Non-blocking keyboard check to determine if 'Q' or 'q' was pressed.
    Used for user-initiated download cancellations.
    """
    if msvcrt:
        if msvcrt.kbhit():
            try:
                ch = msvcrt.getch()
                if ch.lower() == b"q":
                    return True
            except Exception:
                pass
    else:
        try:
            import select
            if select.select([sys.stdin], [], [], 0.0)[0]:
                ch = sys.stdin.read(1)
                if ch.lower() == 'q':
                    return True
        except Exception:
            pass
    return False


# --- Terminal Layout & Windows Console Controls ---
def setup_console():
    """Initializes ANSI escape code support in Windows CMD and applies standard sizing."""
    if os.name == "nt":
        os.system("")  # Triggers VT100 native ANSI escape code processing on Windows
        resize_console(CONSOLE_COLS, CONSOLE_LINES)


def resize_console(cols: int, lines: int = CONSOLE_LINES):
    """Resizes the console buffer window (Windows only) within bounded dimensions."""
    if os.name != "nt":
        return
    cols = max(80, min(cols, MAX_CONSOLE_COLS))
    os.system(f"mode con: cols={cols} lines={lines}")
    center_console_window()


def maximize_console():
    """Maximizes the console window using Win32 API calls."""
    if os.name != "nt" or ctypes is None:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
    except Exception:
        pass


def restore_console():
    """Restores the console to default centered bounds."""
    if os.name != "nt" or ctypes is None:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    except Exception:
        pass
    resize_console(CONSOLE_COLS, CONSOLE_LINES)


def center_console_window():
    """Positions the console window directly in the center of the primary display monitor."""
    if ctypes is None:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top

        screen_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN

        x = max((screen_w - win_w) // 2, 0)
        y = max((screen_h - win_h) // 2, 0)

        # SWP_NOSIZE (0x0001) | SWP_NOZORDER (0x0004)
        user32.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001 | 0x0004)
    except Exception:
        pass


def term_width() -> int:
    """Retrieves current terminal column width."""
    return shutil.get_terminal_size((CONSOLE_COLS, CONSOLE_LINES)).columns


def cline(text: str = ""):
    """Prints a single line of text centered within the current terminal width."""
    print(text.center(term_width()))


def cblock(text: str):
    """Prints a multiline block of text centered relative to its longest line."""
    width = term_width()
    lines = text.splitlines()
    maxlen = max((len(l) for l in lines), default=0)
    pad = max((width - maxlen) // 2, 0)
    for line in lines:
        print(" " * pad + line)


def lblock(text: str):
    """Prints a multiline block left-aligned."""
    for line in text.splitlines():
        print(line)


def clear():
    """Clears the terminal screen for both Windows and Unix systems."""
    os.system("cls" if os.name == "nt" else "clear")


def cleanup_partials():
    """Removes leftover unfinished download artifacts (.part / .ytdl files)."""
    for pattern in ("*.part", "*.ytdl"):
        for f in OUT_DIR.glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass


def print_header_prompt(title: str):
    """Renders menu prompt header for input screens."""
    print()
    lines = [
        "----------------------------------------------------",
        title.center(52),
        "----------------------------------------------------",
        " [0] Go to menu",
        " [1] Download",
        "----------------------------------------------------",
        "For multiple downloads: use comma(,) or space".center(52),
    ]
    cblock("\n".join(lines))
    print()


def print_header_simple(title: str):
    """Renders menu section header."""
    print()
    lines = [
        "----------------------------------------------------",
        title.center(52),
        "----------------------------------------------------",
    ]
    cblock("\n".join(lines))
    print()


def print_logo():
    """Renders ASCII logo banner."""
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
    """Renders the main interactive interface."""
    clear()
    cleanup_partials()
    print()
    print_logo()
    print()

    install_option = " [5] Install / Update  (Available)" if UPDATE_AVAILABLE else " [5] Install / Update"

    menu_lines = [
        "====================================================",
        "My Downloader".center(52),
        "====================================================",
        " [1] Download Video (Best Quality - MKV)",
        " [2] Download Video (Best Quality - MP4)",
        " [3] Download Audio Only (MP3)",
        " [4] Download Custom (Advance download)",
        install_option,
        " [6] Exit",
        "====================================================",
    ]
    cblock("\n".join(menu_lines))
    print()
    imp_lines = [
        "# First-time users: Choose option 5",
        "# N.B: Keep the app in a folder.",
        "# WARNING: Do not delete the 'bin' folder.",
    ]
    print(f"{YELLOW}")
    cblock("\n".join(imp_lines))
    print(f"\n\n{WHITE}")


# --- Media Download Processing ---
def ensure_ytdlp_exists() -> bool:
    """Validates presence of binary dependency before execution."""
    if not YTDLP.exists():
        print(f"{RED}[ERROR] yt-dlp was not found in the 'bin' directory!{WHITE}")
        print(f"{YELLOW}[INFO] Please run Option [5] (Install / Update) first.{WHITE}\n")
        flush_input()
        input("Press Enter to return to main menu...")
        return False
    return True


def prompt_urls_input(title: str) -> list[str]:
    """Prompts the user for target URLs and handles action confirmation."""
    clear()
    print_header_prompt(title)
    
    raw_input = input("Enter your URL(s): ").strip()
    print("\n")
    
    if not raw_input:
        print(f"{YELLOW}[!] No URL entered. Returning to menu...{WHITE}")
        time.sleep(1)
        return []

    # Parse whitespace/comma delimited input strings into distinct URLs
    urls = [u.strip() for u in raw_input.replace(",", " ").split() if u.strip()]

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


def download_batch_with_bar(urls: list[str], title: str, extra_args: list[str]):
    """
    Executes yt-dlp subprocess tasks with real-time output parsing 
    and custom multi-line progress rendering.
    """
    if not ensure_ytdlp_exists() or not urls:
        return

    total = len(urls)
    clear()
    print_header_simple(title)

    successful_count = 0
    canceled_count = 0
    failed_count = 0

    for idx, url in enumerate(urls, 1):
        # Dedicated temp log file for progress monitoring
        log_path = Path(tempfile.gettempdir()) / f"ytdlp_progress_{idx}.txt"
        if log_path.exists():
            try:
                log_path.unlink()
            except OSError:
                pass

        cmd = [
            str(YTDLP),
            "--ffmpeg-location", str(BIN_DIR),
            "--no-colors",
            *extra_args,
            "--newline",
            "--progress-template", "PG|%(progress._percent_str)s",
            "-o", str(OUT_DIR / "%(title)s.%(ext)s"),
            url,
        ]

        log_file = open(log_path, "w", encoding="utf-8", errors="ignore")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        print(f"Video URL: {url}")
        print(f"{CYAN}Progress:  [" + EMPTY + f"] 0%{RESET}")
        print(f"{YELLOW}[INFO] Press 'Q' to cancel this download.{RESET}")

        canceled = False
        last_pct = -1

        try:
            while True:
                # Check for user cancellation request
                if check_q_pressed():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    canceled = True
                    break

                if proc.poll() is not None:
                    break

                pct = read_progress(log_path)
                if pct != last_pct:
                    draw_progress(pct)
                    last_pct = pct

                time.sleep(0.25)
        except Exception:
            pass
        finally:
            log_file.close()

        content = ""
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8", errors="ignore")

        # Visual progress updates via ANSI cursor manipulation (\033[2A = up 2 lines)
        if canceled:
            sys.stdout.write("\033[2A\r")
            sys.stdout.write(f"\033[K{CYAN}Progress:  [{FULL[:max(0, last_pct)//4] + EMPTY[:25-max(0, last_pct)//4]}] {max(0, last_pct)}%\033[0m\n")
            sys.stdout.write(f"\033[K{RED}[{idx}/{total}] Canceled by user.{WHITE}\n\n")
            sys.stdout.flush()
            cleanup_log(log_path)
            canceled_count += 1
            continue

        return_code = proc.returncode
        success = (return_code == 0) and ("error" not in content.lower() and "unable" not in content.lower())
        final_pct = 100 if success else (last_pct if last_pct >= 0 else 0)

        filled = final_pct // 4
        bar = FULL[:filled] + EMPTY[:25 - filled]
        sys.stdout.write(f"\033[2A\r{CYAN}Progress:  [{bar}] {final_pct}%\033[0m\033[K\n")

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


def read_progress(log_path: Path) -> int:
    """Parses percent value from the progress log file."""
    pct = 0
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("PG|"):
                        raw = line.strip().split("|", 1)[1].replace("%", "").strip()
                        try:
                            pct = int(float(raw))
                        except ValueError:
                            pass
        except OSError:
            pass
    return max(0, min(100, pct))


def draw_progress(pct: int):
    """Overwrites progress bar line using ANSI terminal escape sequences."""
    filled = pct // 4
    bar = FULL[:filled] + EMPTY[:25 - filled]
    sys.stdout.write(f"\033[2A\r{CYAN}Progress:  [{bar}] {pct}%\033[0m\033[K\n\033[1B")
    sys.stdout.flush()


def cleanup_log(log_path: Path):
    """Safely deletes temporary process log files."""
    try:
        if log_path.exists():
            log_path.unlink()
    except OSError:
        pass


def action_video_mkv():
    """Download best available video/audio streams into MKV container."""
    urls = prompt_urls_input("DOWNLOAD BEST QUALITY (MKV)")
    if not urls:
        return
    download_batch_with_bar(urls, "DOWNLOAD BEST QUALITY (MKV)",
                           ["-f", "bv*+ba/b", "--merge-output-format", "mkv"])


def action_video_mp4():
    """Download best available video/audio streams into MP4 container."""
    urls = prompt_urls_input("DOWNLOAD BEST QUALITY (MP4)")
    if not urls:
        return
    download_batch_with_bar(urls, "DOWNLOAD BEST QUALITY (MP4)",
                           ["-f", "bv*+ba/b", "--merge-output-format", "mp4"])


def action_audio():
    """Extract and convert audio streams into MP3 format at maximum quality (V0)."""
    urls = prompt_urls_input("DOWNLOAD AUDIO ONLY (MP3)")
    if not urls:
        return
    download_batch_with_bar(urls, "DOWNLOAD AUDIO ONLY (MP3)",
                           ["-x", "--audio-format", "mp3", "--audio-quality", "0"])


# --- Formatted Custom Format Viewer ---
def display_custom_formats(url: str) -> bool:
    """
    Fetches media metadata using yt-dlp JSON dumping and formats output tables 
    categorized by stream media types and extensions.
    """
    cmd = [
        str(YTDLP),
        "--dump-json",
        "--no-playlist",
        "--no-warnings",
        url
    ]
    
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return False

    try:
        data = json.loads(proc.stdout)
        raw_formats = data.get("formats", [])
    except Exception:
        return False

    if not raw_formats:
        return False

    # Group formats by type and container format
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
        elif is_video:
            if ext == "mp4":
                mp4_videos.append(f)
            elif ext == "webm":
                webm_videos.append(f)
            else:
                other_videos.append(f)

    # Sorting keys for organized tabular display
    def sort_video_key(item):
        return (item.get("height") or 0, item.get("width") or 0, item.get("tbr") or item.get("vbr") or 0)

    def sort_audio_key(item):
        return (item.get("abr") or item.get("tbr") or 0)

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

    print_video_table("mp4 video options", mp4_videos)
    print_video_table("webm video options", webm_videos)
    if other_videos:
        print_video_table("other video options", other_videos)
        
    print_audio_table("m4a audio options", m4a_audios)
    print_audio_table("webm audio options", webm_audios)
    if other_audios:
        print_audio_table("other audio options", other_audios)

    return True


def action_custom():
    """Allows manual choice of explicit format strings (e.g., 137+140)."""
    if not ensure_ytdlp_exists():
        return

    urls = prompt_urls_input("CUSTOM FORMAT / RESOLUTION")
    if not urls:
        return

    print()
    print(f"{YELLOW}[INFO] Fetching available formats...{WHITE}")
    print()

    # Attempt structured JSON view first
    success = display_custom_formats(urls[0])

    # Fall back to standard yt-dlp tabular view if JSON parsing fails
    if not success:
        result = subprocess.run([str(YTDLP), "-F", urls[0]], capture_output=True, text=True)
        output = (result.stdout or "") + (result.stderr or "")
        if output.strip():
            widest_line = max((len(l) for l in output.splitlines()), default=CONSOLE_COLS)
            needed_cols = widest_line + 4
            if needed_cols > CONSOLE_COLS:
                maximize_console()
            lblock(output.strip())

    print()
    fmt = input("Enter desired format code (e.g., 137+140 or best) or select option [0]: ").strip()
    
    restore_console()
    
    if not fmt or fmt == "0":
        return

    download_batch_with_bar(urls, "CUSTOM FORMAT / RESOLUTION", ["-f", fmt])


# --- Updates & Dependency Management ---
def get_local_ytdlp_version() -> str:
    """Reads installed yt-dlp version with 6s timeout to account for Antivirus delays."""
    yt_exe = BIN_DIR / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    if not yt_exe.exists():
        return "[File not found: install]"
    try:
        res = subprocess.run(
            [str(yt_exe), "--version"], 
            capture_output=True, 
            text=True, 
            timeout=6
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
        return "installed"
    except Exception:
        return "installed"


def get_local_ffmpeg_version() -> str:
    """Reads installed FFmpeg build version string."""
    ffmpeg_exe = BIN_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not ffmpeg_exe.exists():
        return "[File not found: install]"
    try:
        res = subprocess.run(
            [str(ffmpeg_exe), "-version"], 
            capture_output=True, 
            text=True, 
            timeout=6
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
    """
    Retrieves latest GitHub release tag via standard browser HTTP HEAD redirect tracking.
    Bypasses GitHub API rate-limiting rules (api.github.com's 60 req/hr ceiling).
    """
    url = f"https://github.com/{repo_path}/releases/latest"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            method="HEAD",
        )
        ctx = create_secure_ssl_context()
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
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


# Temporary runtime cache to prevent redundant HTTP requests within 5 minutes
_RELEASE_CACHE = {}
CACHE_TTL_SECONDS = 300


def get_cached_release_tag(repo_path: str, force: bool = False) -> str:
    """Retrieves cached release tags or forces an updated remote check."""
    now = time.time()
    cached = _RELEASE_CACHE.get(repo_path)
    if not force and cached and (now - cached[1] < CACHE_TTL_SECONDS):
        return cached[0]
    tag = fetch_latest_release_tag(repo_path)
    _RELEASE_CACHE[repo_path] = (tag, now)
    return tag


def format_update_status(local_ver: str, latest_tag: str) -> str:
    """Formally formats version strings for display in update menus."""
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
    """Renders update status dashboard for dependencies and application."""
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


def action_update_ytdlp():
    """Downloads latest yt-dlp executable directly from GitHub releases."""
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
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        ctx = create_secure_ssl_context()
        with urllib.request.urlopen(req, context=ctx) as resp, open(YTDLP, "wb") as f:
            shutil.copyfileobj(resp, f)
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
    """Downloads and extracts latest Gyan.dev FFmpeg Essentials zip build."""
    clear()
    print_header_simple("UPDATING FFMPEG")
    ffmpeg_exe = BIN_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not ffmpeg_exe.exists():
        print(f"{YELLOW}[INFO] FFmpeg not found in bin folder. Installing automatically...{WHITE}")
    else:
        print(f"{YELLOW}[INFO] Downloading latest FFmpeg Essentials build (~100MB)...{WHITE}")
    print()

    tmp_dir = Path(tempfile.gettempdir())
    zip_path = tmp_dir / "ffmpeg.zip"
    extract_dir = tmp_dir / "ffmpeg_extracted"

    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        ctx = create_secure_ssl_context()
        with urllib.request.urlopen(req, context=ctx) as resp, open(zip_path, "wb") as f:
            shutil.copyfileobj(resp, f)

        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # Locate binaries nested inside archive folder structure
        bin_folder = None
        for path in extract_dir.rglob("ffmpeg.exe" if os.name == "nt" else "ffmpeg"):
            bin_folder = path.parent
            break

        if bin_folder:
            for exe in ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe") if os.name == "nt" else ("ffmpeg", "ffprobe", "ffplay"):
                src = bin_folder / exe
                if src.exists():
                    dest = BIN_DIR / exe
                    shutil.copy2(src, dest)
                    if os.name != "nt":
                        dest.chmod(0o755)

        zip_path.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)
    except Exception as e:
        print(f"{RED}[ERROR] FFmpeg update failed. Check your connection. ({e}){WHITE}")
        print()
        flush_input()
        input("Press Enter to continue...")
        return

    if ffmpeg_exe.exists():
        print(f"{GREEN}[SUCCESS] FFmpeg, ffprobe, and ffplay installed/updated successfully!{WHITE}")
    else:
        print(f"{RED}[ERROR] FFmpeg installation failed.{WHITE}")
    print()
    flush_input()
    input("Press Enter to continue...")


def action_update():
    """Performs self-update of application binary via atomic file replacement."""
    clear()
    print_header_simple("UPDATING MY DOWNLOADER")
    print(f"{YELLOW}[INFO] Checking for latest release on GitHub...{WHITE}")
    print()

    try:
        print(f"{CYAN}[1/2] Finding latest release tag...")
        tag = get_cached_release_tag(f"{REPO_OWNER}/{REPO_NAME}", force=True)
        if tag in ("Unavailable", "No Release", "Rate Limited", "No Internet") or tag.startswith("HTTP "):
            raise Exception(f"Could not determine latest release ({tag})")

        encoded_tag = urllib.parse.quote(tag)
        encoded_name = urllib.parse.quote(GITHUB_EXE_FILENAME)
        download_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/download/{encoded_tag}/{encoded_name}"

        print(f"{CYAN}[2/2] Downloading latest binary...")
        req_dl = urllib.request.Request(download_url, headers={"User-Agent": "Mozilla/5.0"})
        ctx = create_secure_ssl_context()
        
        base_folder = get_base_dir()
        temp_exe = base_folder / "My_Downloader_temp.exe"
        
        with urllib.request.urlopen(req_dl, context=ctx) as resp, open(temp_exe, "wb") as f:
            shutil.copyfileobj(resp, f)

        print()
        print(f"{GREEN}[SUCCESS] Download complete!{WHITE}")
        print(f"{YELLOW}[INFO] The app will now restart to apply the update...{WHITE}")
        sys.stdout.flush()

        is_frozen = getattr(sys, 'frozen', False)
        current_exe = Path(sys.executable).resolve() if is_frozen else (base_folder / GITHUB_EXE_FILENAME)
        target_exe = base_folder / GITHUB_EXE_FILENAME

        # Windows locks active executables; rename running executable first
        if current_exe.exists():
            old_exe = base_folder / f"My Downloader.old.{int(time.time())}.exe"
            current_exe.rename(old_exe)

        temp_exe.rename(target_exe)
        
        # Spawn replacement process and terminate current instance
        if os.name == "nt":
            os.startfile(str(target_exe.resolve()))
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


# --- Startup & Dependency Verification ---
def is_update_needed(local_ver: str, latest_tag: str) -> bool:
    """Compares version tags to determine update eligibility."""
    if "not found" in local_ver.lower():
        return True

    if latest_tag in ("Unavailable", "No Release", "Rate Limited", "No Internet") or latest_tag.startswith("HTTP "):
        return False

    clean_local = local_ver.lstrip("v").strip()
    clean_latest = latest_tag.lstrip("v").strip()
    return clean_local != clean_latest


def check_for_updates():
    """Asynchronously checks for updates to all binaries in background thread."""
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


# --- Exit Screen ---
def action_exit():
    """Displays closing banner and cleans up application runtime."""
    clear()
    logo = r"""
                   ##########                   
              ####################              
           ##########################           
         ##############################         
       ##################################       
      ##########++########################      
     #######+------######+--+######+++#####     
    ###++----------+###+-----####+----+#####    
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
    cline(f"Git handle: Y2m777a5 | Git Repo: github.com/Y2m777a5/My-Downloader")
    
    time.sleep(3)
    sys.exit()


# --- Main Application Entry Point ---
def cleanup_old_update_files():
    """Deletes old binary backups created during previous self-update cycles."""
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
    
    # Run update check in background thread to avoid blocking GUI startup
    threading.Thread(target=check_for_updates, daemon=True).start()

    actions = {
        "1": action_video_mkv,
        "2": action_video_mp4,
        "3": action_audio,
        "4": action_custom,
        "5": action_install_update_menu,
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
