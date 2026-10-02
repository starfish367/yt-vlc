# yt-vlc: Trình phát YouTube siêu nhẹ với VLC Media Player (GTK3)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20(x86__64%20%7C%20arm64)-blue.svg)](#)

Một ứng dụng Desktop giao diện đồ họa hiện đại (GTK3) dành cho Linux, cho phép tìm kiếm, theo dõi kênh và phát video YouTube trực tiếp thông qua **VLC Media Player**. Rất thích hợp cho máy tính cấu hình yếu, máy nhúng ARM/ARM64 (Raspberry Pi, TV Box, Linux Mint, Debian, Ubuntu) cần xem YouTube mượt mà, không bị giật lag và không bị ngốn RAM bởi trình duyệt web.

---

## ✨ Tính năng nổi bật

* 🚀 **Xem trực tiếp trên VLC:** Tận dụng tối đa bộ giải mã phần cứng (Hardware Acceleration) của VLC, không ngốn RAM/CPU như trình duyệt Chrome/Firefox.
* 🖼️ **Thumbnail lớn, sắc nét:** Ảnh thu nhỏ tỷ lệ 16:9 rõ ràng, trực quan, dễ bấm.
* 🔍 **Tìm kiếm nhanh:** Tìm kiếm video hoặc dán link YouTube bất kỳ để phát ngay lập tức.
* 📺 **Kênh đăng ký (Subscriptions Feed):** Theo dõi video mới từ các kênh YouTube yêu thích hoàn toàn cục bộ (local RSS), không cần đăng nhập tài khoản Google.
* 🕒 **Lịch sử xem (Watch History):** Tự động lưu lại các video đã xem để dễ dàng phát lại bất kỳ lúc nào.
* ⚙️ **Cài đặt linh hoạt:**
  * Tùy chọn chất lượng video: 1080p, 720p (khuyên dùng), 480p, 360p, Best.
  * Tùy chỉnh bộ nhớ đệm VLC (`caching` từ 1000ms đến 5000ms) chống giật lag khi mạng yếu.
  * Tùy chọn bật/tắt tăng tốc phần cứng.
  * Giao diện tối (Dark theme) dịu mắt.

---

## 📦 Yêu cầu hệ thống

* **Hệ điều hành:** Linux (Debian, Ubuntu, Linux Mint, Arch, Fedora...). Hỗ trợ cả x86_64 và ARM64.
* **Các gói phụ thuộc:**
  * `vlc` (Trình phát đa phương tiện)
  * `yt-dlp` (Công cụ phân giải video)
  * `python3` và `python3-gi` (PyGObject GTK3)

---

## 🛠️ Cài đặt nhanh

Chỉ cần clone repository và chạy script cài đặt:

```bash
git clone https://github.com/starfish367/yt-vlc.git
cd yt-vlc
chmod +x install.sh
./install.sh
```

Sau khi cài đặt, bạn có thể:
1. Mở menu ứng dụng trên Linux và tìm **"Xem YouTube bằng VLC"**.
2. Hoặc gõ lệnh trong terminal:
   ```bash
   yt-vlc
   ```
3. Hoặc mở trực tiếp một link YouTube bất kỳ:
   ```bash
   yt-vlc "https://www.youtube.com/watch?v=..."
   ```

---

## 📄 Bản quyền (License)

Dự án được phát hành theo giấy phép [MIT License](LICENSE).
Tác giả: [**starfish367**](https://github.com/starfish367).
