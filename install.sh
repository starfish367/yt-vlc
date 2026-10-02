#!/usr/bin/env bash
# Script cài đặt yt-vlc vào hệ thống
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "===> Đang cài đặt yt-vlc vào ~/.local/bin/ ..."
mkdir -p "$HOME/.local/bin"
cp "$DIR/yt_vlc.py" "$HOME/.local/bin/yt-vlc"
chmod +x "$HOME/.local/bin/yt-vlc"

echo "===> Đang tạo lối tắt Desktop & Menu ứng dụng ..."
mkdir -p "$HOME/.local/share/applications"
cp "$DIR/yt-vlc.desktop" "$HOME/.local/share/applications/yt-vlc.desktop"

if [ -d "$HOME/Desktop" ]; then
    cp "$DIR/yt-vlc.desktop" "$HOME/Desktop/yt-vlc.desktop"
    chmod +x "$HOME/Desktop/yt-vlc.desktop"
    # Tin cậy file desktop trên GNOME / Cinnamon nếu có gio
    if command -v gio &>/dev/null; then
        gio set "$HOME/Desktop/yt-vlc.desktop" metadata::trusted true 2>/dev/null || true
    fi
fi

echo "===> Hoàn tất cài đặt! Bạn có thể khởi động bằng lệnh: yt-vlc"
