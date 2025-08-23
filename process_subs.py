import requests
import base64
import re
import socket
import idna
from urllib.parse import urlparse
from collections import OrderedDict

# --- تنظیمات ---
SOURCE_URL = "https://raw.githubusercontent.com/Shervinuri/SUB/main/Source.txt"
OUTPUT_FILE = "pure.md"
MAX_CONFIGS = 300
HEALTH_THRESHOLD_MS = 350
REMARK_NAME = "☬SHΞN™"

# --- الگوی استخراج کانفیگ ---
VLESS_PATTERN = re.compile(r'^vless://([^#]+)#?(.*)$')
VMESS_PATTERN = re.compile(r'^vmess://([^#]+)#?(.*)$')

# --- لیست کانفیگ‌های منحصر به فرد ---
unique_configs = {}

def decode_base64(s):
    try:
        return base64.b64decode(s).decode('utf-8')
    except Exception:
        return s

def sanitize_hostname(hostname):
    try:
        return idna.encode(hostname).decode('ascii')
    except Exception:
        return hostname  # در صورت خطا، حالت اصلی را نگه دار

def parse_vless_or_vmess(url):
    match = VLESS_PATTERN.match(url.strip())
    if match:
        raw = match.group(1)
        params = match.group(2)
        decoded = decode_base64(raw)
        parts = decoded.split('@', 1)
        if len(parts) != 2:
            return None
        auth, server_info = parts
        server_parts = server_info.split(':', 1)
        if len(server_parts) != 2:
            return None
        host, port = server_parts
        host = sanitize_hostname(host)
        try:
            port = int(port)
        except ValueError:
            return None
        # استخراج پارامترهای اختیاری
        query_params = {}
        if params:
            for param in params.split('&'):
                if '=' in param:
                    k, v = param.split('=', 1)
                    query_params[k] = v
        return {
            'type': 'vless',
            'host': host,
            'port': port,
            'path': query_params.get('path', ''),
            'ws': 'ws' in query_params.get('security', ''),
            'grpc': 'grpc' in query_params.get('security', ''),
            'latency': None,
            'remark': query_params.get('remark', REMARK_NAME),
            'url': url
        }

    match = VMESS_PATTERN.match(url.strip())
    if match:
        raw = match.group(1)
        params = match.group(2)
        decoded = decode_base64(raw)
        try:
            data = eval(f'dict({decoded})')  # تبدیل string JSON-like به dict
        except Exception:
            return None

        host = data.get('add')
        port = data.get('port')
        network = data.get('net', '')
        path = data.get('path', '')
        if not host or not port:
            return None
        try:
            port = int(port)
        except ValueError:
            return None
        host = sanitize_hostname(host)

        return {
            'type': 'vmess',
            'host': host,
            'port': port,
            'path': path,
            'ws': network == 'ws',
            'grpc': network == 'grpc',
            'latency': None,
            'remark': data.get('ps', REMARK_NAME),
            'url': url
        }
    return None

def ping_server(host, port, timeout=1.5):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        start_time = socket.gethrtime()  # Python 3.7+
        sock.connect((host, port))
        end_time = socket.gethrtime()
        latency_ms = (end_time - start_time) * 1000
        sock.close()
        return latency_ms
    except Exception as e:
        return None

def main():
    print("🔄 در حال خواندن لیست منابع...")
    try:
        response = requests.get(SOURCE_URL, timeout=10)
        response.raise_for_status()
        links = [line.strip() for line in response.text.splitlines() if line.strip()]
    except Exception as e:
        print(f"❌ خطای دریافت لیست منابع: {e}")
        return

    print(f"📥 دریافت {len(links)} لینک ورودی")

    # --- مرحله ۱: استخراج و حذف تکراری ---
    for link in links:
        try:
            resp = requests.get(link, timeout=10)
            content = resp.text.strip()

            # اگر Base64 باشد، تجزیه کن
            if content.startswith('base64'):
                content = decode_base64(content.split(',', 1)[1])
            elif content.startswith('vmess://') or content.startswith('vless://'):
                pass  # محتوای خام
            else:
                # شاید متن خام باشد
                content = content

            # استخراج کانفیگ‌ها
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith('vmess://') or line.startswith('vless://'):
                    config = parse_vless_or_vmess(line)
                    if config:
                        key = f"{config['host']}:{config['port']}"
                        if key not in unique_configs:
                            unique_configs[key] = config
                        else:
                            # فقط اگر سرور/پورت یکسان باشد، جایگزین کن
                            if config['ws'] or config['grpc']:
                                # اگر جدید ws/grpc باشد، جایگزین کن
                                if not unique_configs[key]['ws'] and not unique_configs[key]['grpc']:
                                    unique_configs[key] = config
            print(f"✅ پردازش لینک: {link}")

        except Exception as e:
            print(f"⚠️ خطای در پردازش لینک: {link} | {e}")
            continue

    print(f"🗂️ تعداد کانفیگ‌های منحصر به فرد: {len(unique_configs)}")

    # --- مرحله ۲: تست سلامت ---
    healthy_configs = []
    print("📡 در حال تست سلامت کانفیگ‌ها...")

    for config in unique_configs.values():
        latency = ping_server(config['host'], config['port'], timeout=1.5)
        if latency and latency < HEALTH_THRESHOLD_MS:
            config['latency'] = latency
            healthy_configs.append(config)
            print(f"✅ سالم: {config['host']}:{config['port']} ({latency:.1f} ms)")
        else:
            print(f"❌ ناموفق: {config['host']}:{config['port']} (latency={latency if latency else 'N/A'})")

    print(f"✅ تعداد کانفیگ‌های سالم: {len(healthy_configs)}")

    # --- مرحله ۳: مرتب‌سازی ---
    print("🎯 در حال مرتب‌سازی کانفیگ‌ها...")

    # دو دسته: اولویت ws/grpc → سایر
    prioritized = []
    other = []

    for c in healthy_configs:
        if c['ws'] or c['grpc']:
            prioritized.append(c)
        else:
            other.append(c)

    # مرتب‌سازی داخل هر دسته بر اساس پینگ
    prioritized.sort(key=lambda x: x['latency'])
    other.sort(key=lambda x: x['latency'])

    # ترکیب: اول ws/grpc، سپس سایر
    sorted_configs = prioritized + other

    # انتخاب حداکثر 300 کانفیگ
    selected_configs = sorted_configs[:MAX_CONFIGS]
    print(f"📊 انتخاب {len(selected_configs)} کانفیگ برتر")

    # --- مرحله ۴: تولید خروجی ---
    print("📤 در حال تولید خروجی نهایی...")

    # تغییر Remark
    for c in selected_configs:
        c['remark'] = REMARK_NAME

    # تولید لیست از URLهای اصلی (نه کدگذاری شده)
    output_lines = []
    for c in selected_configs:
        output_lines.append(c['url'])

    final_text = '\n'.join(output_lines)

    # کدگذاری Base64
    encoded_content = base64.b64encode(final_text.encode('utf-8')).decode('utf-8')

    # ذخیره در فایل
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(encoded_content)

    print(f"✅ خروجی نهایی در {OUTPUT_FILE} ذخیره شد.")

if __name__ == "__main__":
    main()
