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
HEALTH_THRESHOLD_MS = 600
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

def safe_sanitize(hostname):
    try:
        return idna.encode(hostname).decode('ascii')
    except Exception:
        return hostname

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
        host = safe_sanitize(host)
        try:
            port = int(port)
        except ValueError:
            return None
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
            data = eval(f'dict({decoded})')
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
        host = safe_sanitize(host)

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

def ping_server(host, port, timeout=2.0):
    try:
        try:
            socket.gethostbyname(host)
        except:
            return None

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        start_time = socket.gethrtime()
        try:
            sock.connect((host, port))
            end_time = socket.gethrtime()
            latency_ms = (end_time - start_time) * 1000
            sock.close()
            return latency_ms
        except Exception as e:
            sock.close()
            return None
    except Exception as e:
        return None

def http_test(host, port, path, timeout=3.0):
    try:
        # ساخت URL
        scheme = "https" if port == 443 else "http"
        url = f"{scheme}://{host}:{port}{path}"

        # ارسال GET
        resp = requests.get(url, timeout=timeout, verify=False, allow_redirects=True)
        if resp.status_code in [200, 301, 302]:
            return (resp.elapsed.total_seconds() * 1000)
        return None
    except Exception as e:
        return None

def is_healthy(config):
    host = config['host']
    port = config['port']
    path = config['path']

    # اگر ws یا grpc باشه → تست HTTP
    if config['ws'] or config['grpc']:
        # تست با path
        test_path = path or "/"
        latency = http_test(host, port, test_path, timeout=3.0)
        if latency and latency < HEALTH_THRESHOLD_MS:
            return latency
        return None

    # اگر tcp باشه → تست ping
    latency = ping_server(host, port, timeout=2.0)
    if latency and latency < HEALTH_THRESHOLD_MS:
        return latency
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

    unique_configs = {}

    for link in links:
        try:
            resp = requests.get(link, timeout=10)
            content = resp.text.strip()

            if 'base64,' in content or 'base64;' in content:
                try:
                    parts = content.split(',', 1)
                    if len(parts) > 1:
                        content = decode_base64(parts[1])
                except Exception:
                    pass

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
                            if config['ws'] or config['grpc']:
                                if not unique_configs[key]['ws'] and not unique_configs[key]['grpc']:
                                    unique_configs[key] = config
            print(f"✅ پردازش لینک: {link}")

        except Exception as e:
            print(f"⚠️ خطای در پردازش لینک: {link} | {e}")
            continue

    print(f"🗂️ تعداد کانفیگ‌های منحصر به فرد: {len(unique_configs)}")

    healthy_configs = []
    print("📡 در حال تست سلامت کانفیگ‌ها...")

    for config in unique_configs.values():
        latency = is_healthy(config)
        if latency:
            config['latency'] = latency
            healthy_configs.append(config)
            print(f"✅ سالم: {config['host']}:{config['port']} ({latency:.1f} ms)")
        else:
            print(f"❌ ناموفق: {config['host']}:{config['port']} (latency=NA)")

    print(f"✅ تعداد کانفیگ‌های سالم: {len(healthy_configs)}")

    prioritized = []
    other = []

    for c in healthy_configs:
        if c['ws'] or c['grpc']:
            prioritized.append(c)
        else:
            other.append(c)

    prioritized.sort(key=lambda x: x['latency'])
    other.sort(key=lambda x: x['latency'])

    sorted_configs = prioritized + other
    selected_configs = sorted_configs[:MAX_CONFIGS]

    print(f"📊 انتخاب {len(selected_configs)} کانفیگ برتر")

    # تولید خروجی
    print("📤 در حال تولید خروجی نهایی...")

    if not selected_configs:
        print("❌ هیچ کانفیگ سالمی یافت نشد!")
        final_text = """# ❌ خطای سیستم: هیچ کانفیگ سالمی یافت نشد!
        
این مشکل معمولاً به دلایل زیر اتفاق می‌افتد:
- منبع (Source.txt) خالی یا غیرقابل دسترس است.
- تمام سرورها دسترسی ندارند (Firewall / IP Ban).
- لینک‌ها کدگذاری شده‌اند و به درستی تجزیه نمی‌شوند.

📌 لطفاً بررسی کن:
1. https://raw.githubusercontent.com/Shervinuri/SUB/main/Source.txt
2. آیا فایل `Source.txt` موجود است؟
3. آیا لینک‌های `vmess://` یا `vless://` دارد؟

✅ اگر مشکل حل نشد، از طریق GitHub Issues اطلاع بده."""
    else:
        for c in selected_configs:
            c['remark'] = REMARK_NAME
        output_lines = [c['url'] for c in selected_configs]
        final_text = '\n'.join(output_lines)

    encoded_content = base64.b64encode(final_text.encode('utf-8')).decode('utf-8')

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(encoded_content)

    print(f"✅ خروجی نهایی در {OUTPUT_FILE} ذخیره شد.")

    # لاگ‌گیری
    with open("logs.txt", "w", encoding="utf-8") as f:
        f.write(f"📊 کانفیگ‌های منحصر به فرد: {len(unique_configs)}\n")
        f.write(f"✅ کانفیگ‌های سالم: {len(healthy_configs)}\n")
        f.write(f"📌 انتخاب شده: {len(selected_configs)}\n")
        f.write("\n--- لیست سرورها ---\n")
        for c in unique_configs.values():
            status = "سالم" if c.get('latency') else "نازده"
            f.write(f"{c['host']}:{c['port']} | {status} | {c['latency'] if c.get('latency') else 'N/A'} ms\n")

if __name__ == "__main__":
    main()
