#!/usr/bin/env bash
# Script cài đặt yt-vlc vào hệ thống
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "===> Đang cài đặt yt-vlc vào ~/.local/bin/ ..."
mkdir -p "$HOME/.local/bin"
cp "$DIR/yt_vlc.py" "$HOME/.local/bin/yt-vlc"
chmod +x "$HOME/.local/bin/yt-vlc"

echo "===> Đang cài đặt biểu tượng (Icons) ..."
mkdir -p "$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$HOME/.local/share/pixmaps"

if [ -f "$DIR/assets/yt-vlc.svg" ]; then
    cp "$DIR/assets/yt-vlc.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/yt-vlc.svg"
    cp "$DIR/assets/yt-vlc.svg" "$HOME/.local/share/pixmaps/yt-vlc.svg"
fi

if [ -f "$DIR/assets/yt-vlc.png" ]; then
    cp "$DIR/assets/yt-vlc.png" "$HOME/.local/share/icons/hicolor/256x256/apps/yt-vlc.png"
    cp "$DIR/assets/yt-vlc.png" "$HOME/.local/share/pixmaps/yt-vlc.png"
fi

# Cập nhật cache icon nếu có lệnh
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "===> Đang tạo lối tắt Desktop & Menu ứng dụng ..."
mkdir -p "$HOME/.local/share/applications"
cp "$DIR/yt-vlc.desktop" "$HOME/.local/share/applications/yt-vlc.desktop"

if [ -d "$HOME/Desktop" ]; then
    cp "$DIR/yt-vlc.desktop" "$HOME/Desktop/yt-vlc.desktop"
    chmod +x "$HOME/Desktop/yt-vlc.desktop"
    if command -v gio &>/dev/null; then
        gio set "$HOME/Desktop/yt-vlc.desktop" metadata::trusted true 2>/dev/null || true
    fi
fi

echo "===> Hoàn tất cài đặt! Bạn có thể khởi động bằng lệnh: yt-vlc"
