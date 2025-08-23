import requests
import base64
import re

# --- تنظیمات ---
SOURCE_URL = "https://raw.githubusercontent.com/Shervinuri/SUB/main/Source.txt"
OUTPUT_FILE = "pure.md"
REMARK_NAME = "☬SHΞN™"

# --- الگوی استخراج کانفیگ ---
VLESS_PATTERN = re.compile(r'^vless://([^#]+)#?(.*)$')
VMESS_PATTERN = re.compile(r'^vmess://([^#]+)#?(.*)$')

def decode_base64(s):
    try:
        return base64.b64decode(s).decode('utf-8')
    except Exception:
        return s

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
        query_params = {}
        if params:
            for param in params.split('&'):
                if '=' in param:
                    k, v = param.split('=', 1)
                    query_params[k] = v
        security = query_params.get('security', '')
        path = query_params.get('path', '')
        sni = query_params.get('sni', host)
        return {
            'type': 'vless',
            'host': host,
            'port': int(port),
            'path': path,
            'ws': 'ws' in security,
            'grpc': 'grpc' in security,
            'sni': sni,
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
        sni = data.get('sni', host)
        if not host or not port:
            return None
        try:
            port = int(port)
        except ValueError:
            return None
        return {
            'type': 'vmess',
            'host': host,
            'port': port,
            'path': path,
            'ws': network == 'ws',
            'grpc': network == 'grpc',
            'sni': sni,
            'url': url
        }
    return None

def is_cloudflare(host):
    # تشخیص دامنه کلودفلر
    cf_domains = ['cloudflare.com', 'cf', 'cloudflare.net']
    host_lower = host.lower()
    return any(domain in host_lower for domain in cf_domains)

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

    valid_configs = []

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
                        # فقط ws یا grpc
                        if not config['ws'] and not config['grpc']:
                            continue
                        # فقط کلودفلر
                        if not is_cloudflare(config['host']):
                            continue
                        # اضافه کن
                        config['remark'] = REMARK_NAME
                        valid_configs.append(config['url'])
            print(f"✅ پردازش لینک: {link}")

        except Exception as e:
            print(f"⚠️ خطای در پردازش لینک: {link} | {e}")
            continue

    print(f"✅ تعداد کانفیگ‌های معتبر: {len(valid_configs)}")

    # تولید خروجی
    final_text = '\n'.join(valid_configs)
    encoded_content = base64.b64encode(final_text.encode('utf-8')).decode('utf-8')

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(encoded_content)

    print(f"✅ خروجی نهایی در {OUTPUT_FILE} ذخیره شد.")

if __name__ == "__main__":
    main()
