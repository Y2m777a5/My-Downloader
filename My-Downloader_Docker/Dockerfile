# Place this at the root of your repo as: Dockerfile
FROM python:3.12-slim

# ffmpeg via apt as a baseline so it's already present -- the app's own
# "Update FFmpeg" menu option can still be tested separately, since it now
# downloads its own Linux static build (johnvansickle.com) rather than
# relying on this one. curl/ca-certificates included for basic network
# debugging inside the container if something looks off.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the whole repo so relative paths (bin/, Downloads/) resolve the same
# way they would on your actual machine -- get_base_dir() returns the
# script's own folder when not frozen, so /app becomes BASE_DIR here.
COPY . .

# Interactive console menu (uses input()) -- must run with `docker run -it`
# or `docker compose run`, not detached.
CMD ["python", "MyDownloader_2_4_8_4.py"]
