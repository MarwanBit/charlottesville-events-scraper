#!/bin/bash
# Run the app with a headed browser and VNC so you can watch Chrome from your host.
# In container: DISPLAY=:99, HEADLESS=0. x11vnc streams :99 to port 5900.
# On host: connect with a VNC client to localhost:5900 (or 5901 if 5900 is in use).

set -e
# Ignore SIGHUP in this shell so docker exec -it hangups don't kill our setup
trap '' HUP
export DISPLAY=:99
export HEADLESS=0

# Clean up any previous Xvfb/x11vnc instances and stale locks so re-runs are idempotent.
rm -f /tmp/.X99-lock || true
pkill Xvfb >/dev/null 2>&1 || true
pkill x11vnc >/dev/null 2>&1 || true

# Start virtual display: 1280x720, 16bpp = less data so first VNC frame finishes in ~30–60s.
Xvfb :99 -screen 0 1280x720x16 >/tmp/xvfb.log 2>&1 &
sleep 2

# Stream that display over VNC. -listen 0.0.0.0 so host (via Docker port map) can connect.
# Run x11vnc in the foreground so this script stays running until you Ctrl+C.
echo "Starting x11vnc on :99 (VNC on port 5900)..."
echo "Connect with a VNC client to localhost:5900 to watch the browser."
x11vnc -display :99 -forever -shared -rfbport 5900 -noxdamage -nopw -listen 0.0.0.0 >/tmp/x11vnc.log 2>&1

