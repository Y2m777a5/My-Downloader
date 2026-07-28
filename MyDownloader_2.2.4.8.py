"""
My Downloader (Python port of the original .bat script)

Requires:
  - bin\\yt-dlp.exe  (or bin/yt-dlp on non-Windows)
  - bin\\ffmpeg.exe, ffprobe.exe, ffplay.exe (optional, used for merging/audio extraction)

Run with:  python downloader.py
"""

import os
import sys
import time
import shutil
import zipfile
import tempfile
import subprocess
import urllib.request
from pathlib import Path

try:
    import msvcrt
except ImportError:
    msvcrt = None

try:
    import ctypes
    from ctypes import wintypes
except ImportError:
    ctypes = None

CONSOLE_COLS = 120
CONSOLE_LINES = 40
MAX_CONSOLE_COLS = 220  # hard ceiling so we never try to grow off-screen


def get_base_dir():
    """Get the absolute path of the script or compiled .exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

#Colors
WHITE = "\033[97m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
GREEN = "\033[38;2;0;254;0m"
RESET = "\033[0m"


BASE_DIR = get_base_dir()
BIN_DIR = BASE_DIR / "bin"
OUT_DIR = BASE_DIR / "Downloads"
YTDLP = BIN_DIR / "yt-dlp.exe"

OUT_DIR.mkdir(exist_ok=True)
BIN_DIR.mkdir(exist_ok=True)

FULL = "█" * 25
EMPTY = "░" * 25

# Bright White ANSI Code
WHITE = "\033[97m"

def main():
    if os.name == "nt":
        os.system("title My Downloader")
    setup_console()
    
    # Force text to bright white right from the start
    print(WHITE, end="")

def setup_console():
    """Fix the console to a known size and move the window to screen center."""
    if os.name != "nt":
        return
    resize_console(CONSOLE_COLS, CONSOLE_LINES)


def resize_console(cols, lines=CONSOLE_LINES):
    """Resize the console buffer/window to the given size and re-center it."""
    if os.name != "nt":
        return
    cols = max(80, min(cols, MAX_CONSOLE_COLS))
    os.system(f"mode con: cols={cols} lines={lines}")
    center_console_window()


def maximize_console():
    """Maximize the console window to fill the screen (Windows only)."""
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
    """Un-maximize and put the console back to its normal centered size."""
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
    """Move the console window to the middle of the primary monitor (Windows only)."""
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

        screen_w = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        screen_h = user32.GetSystemMetrics(1)   # SM_CYSCREEN

        x = max((screen_w - win_w) // 2, 0)
        y = max((screen_h - win_h) // 2, 0)

        # SWP_NOSIZE=0x0001, SWP_NOZORDER=0x0004
        user32.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001 | 0x0004)
    except Exception:
        pass


def term_width():
    return shutil.get_terminal_size((CONSOLE_COLS, CONSOLE_LINES)).columns


def cline(text=""):
    """Print a single line centered in the console (Used for titles)."""
    print(text.center(term_width()))


def cblock(text):
    """Print a multi-line block centered as a whole (Used for headers)."""
    width = term_width()
    lines = text.splitlines()
    maxlen = max((len(l) for l in lines), default=0)
    pad = max((width - maxlen) // 2, 0)
    for line in lines:
        print(" " * pad + line)


def lblock(text):
    """Print a multi-line block left-aligned."""
    for line in text.splitlines():
        print(line)


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def cleanup_partials():
    for pattern in ("*.part", "*.ytdl"):
        for f in OUT_DIR.glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass


def print_header(title, url=None):
    print()
    lines = [
        "----------------------------------------------------",
        title.center(52),
        "----------------------------------------------------",
    ]
    cblock("\n".join(lines))
    print()
    if url:
            print(f"Video URL: {url}")

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
    cleanup_partials()
    print()
    print_logo() # <--- Displays your chosen logo here
    print()
    menu_lines = [
        "====================================================",
        "My Downloader".center(52),
        "====================================================",
        " [1] Download Video (Best Quality - MKV)",
        " [2] Download Video (Best Quality - MP4)",
        " [3] Download Audio Only (MP3)",
        " [4] Download Custom Format / List Formats",
        " [5] Install / Update yt-dlp",
        " [6] Install / Update FFmpeg",
        " [7] Exit",
        "====================================================",
    ]
    cblock("\n".join(menu_lines))
    print()
    imp_lines = [
        "# First-time users: Choose option 5 & 6.",
        "# N.B: Keep the app in a folder.",
        "# WARNING: Do not delete the 'bin' folder.",
    ]
    print(f"{YELLOW}")
    cblock("\n".join(imp_lines))
    print(f"\n\n{WHITE}")


def download_with_bar(url, title, extra_args):
    log_path = Path(tempfile.gettempdir()) / "ytdlp_progress.txt"
    if log_path.exists():
        log_path.unlink()

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

    clear()
    print_header(title, url)
    print(f"{CYAN}Progress:  [" + EMPTY + "] 0%")
    print(f"{YELLOW}[INFO] Press 'Q' to cancel download.{WHITE}")
    print()

    canceled = False
    last_pct = -1

    try:
        while True:
            if msvcrt and msvcrt.kbhit():
                key = msvcrt.getch()
                if key.lower() == b"q":
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
                draw_progress(title, url, pct)
                last_pct = pct

            time.sleep(0.25)
    finally:
        log_file.close()

    if canceled:
        clear()
        print_header(title, url)
        print("\n")
        cline(f"{RED}[CANCELED] Download aborted by user.")
        print()
        cleanup_log(log_path)
        time.sleep(2)
        return

    content = ""
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8", errors="ignore")

    clear()
    print_header(title, url)

    if "error" in content.lower() or "unable" in content.lower():
        print(f"{RED}[ERROR] Download failed:")
        lblock("---------------------------------------------------\n"
               + content.strip()
               + "\n---------------------------------------------------")
        cleanup_log(log_path)
        input(f"{WHITE}Press Enter to continue...")
        return

    print(f"{CYAN}Progress:  [" + FULL + "] 100%")
    print()
    print(f"{GREEN}[DONE] Download complete! Check your 'Downloads' folder.{WHITE}")
    cleanup_log(log_path)
    input("Press Enter to continue...")


def read_progress(log_path):
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


def draw_progress(title, url, pct):
    filled = pct // 4
    bar = FULL[:filled] + EMPTY[:25 - filled]
    sys.stdout.write(f"\033[3A\r{CYAN}Progress:  [{bar}] {pct}%\033[0m\033[K\n\033[2B")
    sys.stdout.flush()


def cleanup_log(log_path):
    try:
        if log_path.exists():
            log_path.unlink()
    except OSError:
        pass


def action_video_mkv():
    clear()
    print_header("DOWNLOAD BEST QUALITY (MKV)")
    url = input("Enter Video URL: ").strip()
    print()
    print(f"{YELLOW}[INFO] Downloading best streams into MKV container...{WHITE}")
    download_with_bar(url, "DOWNLOAD BEST QUALITY (MKV)",
                       ["-f", "bv*+ba/b", "--merge-output-format", "mkv"])


def action_video_mp4():
    clear()
    print_header("DOWNLOAD BEST QUALITY (MP4)")
    url = input("Enter Video URL: ").strip()
    print()
    print(f"{YELLOW}[INFO] Downloading best video + audio track...{WHITE}")
    download_with_bar(url, "DOWNLOAD BEST QUALITY (MP4)",
                       ["-f", "bv*+ba/b", "--merge-output-format", "mp4"])


def action_audio():
    clear()
    print_header("DOWNLOAD AUDIO ONLY (MP3)")
    url = input("Enter Video URL: ").strip()
    print()
    print(f"{YELLOW}[INFO] Extracting audio to MP3...{WHITE}")
    download_with_bar(url, "DOWNLOAD AUDIO ONLY (MP3)",
                       ["-x", "--audio-format", "mp3", "--audio-quality", "0"])


def action_custom():
    clear()
    print_header("CUSTOM FORMAT / RESOLUTION")
    url = input("Enter Video URL: ").strip()
    print()
    print(f"{YELLOW}[INFO] Fetching available formats...{WHITE}")
    print()
    result = subprocess.run([str(YTDLP), "-F", url], capture_output=True, text=True)
    output = (result.stdout or "") + (result.stderr or "")
    if output.strip():
        widest_line = max((len(l) for l in output.splitlines()), default=CONSOLE_COLS)
        needed_cols = widest_line + 4
        if needed_cols > CONSOLE_COLS:
            maximize_console()
        lblock(output.strip())
    print()
    fmt = input("Enter desired format code (e.g., 137+140 or best): ").strip()
    
    restore_console()
    
    download_with_bar(url, "CUSTOM FORMAT / RESOLUTION",
                       ["-f", fmt, "--merge-output-format", "mp4"])


def action_update_ytdlp():
    clear()
    print_header("UPDATING YT-DLP")
    print(f"{YELLOW}[INFO] Downloading the latest yt-dlp.exe directly from GitHub...{WHITE}")
    print()
    print(f"{CYAN}[1/3] Connecting to GitHub servers...")
    time.sleep(1)
    print(f"{CYAN}[2/3] Downloading latest binary (Please wait)...")
    url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(YTDLP, "wb") as f:
            shutil.copyfileobj(resp, f)
        print(f"{CYAN}[3/3] Finalizing installation...{WHITE}")
        time.sleep(1)
        print()
        print(f"{GREEN}[SUCCESS] yt-dlp has been updated!{WHITE}")
    except Exception as e:
        print()
        print(f"{RED}[ERROR] Update failed. Check connection. ({e}){WHITE}")
    print()
    input("Press Enter to continue...")


def action_update_ffmpeg():
    clear()
    print_header("UPDATING FFMPEG")
    print(f"{YELLOW}[INFO] Downloading latest FFmpeg Essentials build...{WHITE}")
    print(f"{YELLOW}[INFO] Please wait, this may take a moment (~100MB)...{WHITE}")
    print()

    tmp_dir = Path(tempfile.gettempdir())
    zip_path = tmp_dir / "ffmpeg.zip"
    extract_dir = tmp_dir / "ffmpeg_extracted"

    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as f:
            shutil.copyfileobj(resp, f)

        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        bin_folder = None
        for path in extract_dir.rglob("ffmpeg.exe"):
            bin_folder = path.parent
            break

        if bin_folder:
            for exe in ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe"):
                src = bin_folder / exe
                if src.exists():
                    shutil.copy2(src, BIN_DIR / exe)

        zip_path.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)
    except Exception as e:
        print(f"{RED}[ERROR] FFmpeg update failed. Check your connection. ({e}){WHITE}")
        print()
        input("Press Enter to continue...")
        return

    if (BIN_DIR / "ffmpeg.exe").exists():
        print(f"{GREEN}[SUCCESS] FFmpeg, ffprobe, and ffplay updated successfully!{WHITE}")
    else:
        print(f"{RED}[ERROR] FFmpeg update failed. Check your connection.{WHITE}")
    print()
    input("Press Enter to continue...")


def action_exit():
    clear()
    logo = r"""
                                                  
                 ---------------.                 
             -----------------------.             
          -----------------------------.          
        .--------------------------------.        
       ------++++++------------------------       
     .++++++++     +-----+++++++-----++++++-.     
    +++ +-         .+--+++     +---+++    +---    
   ++          ++   +++.       +-+++       ----   
  -+        +++++  +++   #    ++++       ++-----  
  -+     ++++-++  ++   +++   +++       +++------  
 --+ ++++----++  #   ++++   #+   ##   ++--------- 
 --+++------++  +  -+++.  -#   +#   +++---------- 
 ---------+++     ++++   +.  +#+   ++++++++++++-- 
 --------++     -++++   -   ++    +++++.      +-- 
 -------++     +++++      +++    ++           .-- 
  ----+++     ++++      ++++    ++++          +-  
  ----+      ++++      ++-+    -+-++#        ++-  
   ---+    -++-+     +++--+    ++++   -     ++-   
    --+   ++---+    ++----+         ++++   -+-    
     --++++----++ +++-----++     ++++--+++++-     
       ----------++--------+++++++---------       
        .--------------------------------.        
          .----------------------------.          
             .-----------------------             
                 .---------------                 
                                                  
    """
    comment = r"""
 _____ _   _    _    _   _ _  __ __   _____  _   _   _____ ___  ____    _   _ ____ ___ _   _  ____ 
|_   _| | | |  / \  | \ | | |/ / \ \ / / _ \| | | | |  ___/ _ \|  _ \  | | | / ___|_ _| \ | |/ ___|
  | | | |_| | / _ \ |  \| | ' /   \ V / | | | | | | | |_ | | | | |_) | | | | \___ \| ||  \| | |  _ 
  | | |  _  |/ ___ \| |\  | . \    | || |_| | |_| | |  _|| |_| |  _ <  | |_| |___) | || |\  | |_| |
  |_| |_| |_/_/   \_\_| \_|_|\_\   |_| \___/ \___/  |_|   \___/|_| \_\  \___/|____/___|_| \_|\____|
    """
    cblock(f"\033[38;2;238;128;32m{logo}{WHITE}")
    print()
    cblock(f"{comment}")
    print()
    time.sleep(2.5)  # Pauses for 2.5 seconds so they can see the logo
    sys.exit()       # Closes the script cleanly


def main():
    if os.name == "nt":
        os.system("title My Downloader")
    setup_console()

    actions = {
        "1": action_video_mkv,
        "2": action_video_mp4,
        "3": action_audio,
        "4": action_custom,
        "5": action_update_ytdlp,
        "6": action_update_ffmpeg,
        "7": action_exit
    }
    while True:
        print_menu()
        choice = input("Select an option (1-7): ").strip()
        action = actions.get(choice)
        if action:
            action()
        else:
            print(f"{RED}[ERROR] Invalid option! Please enter a number between 1 and 7.{WHITE}")
            time.sleep(1.5)  # Pause so they can read the error message


if __name__ == "__main__":
    main()