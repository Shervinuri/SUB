import os
import requests
import base64
import json
import socket
import time
from urllib.parse import urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- تنظیمات اصلی ---
SOURCE_URL = "https://raw.githubusercontent.com/Shervinuri/SUB/main/Source.txt"
OUTPUT_FILE = "pure.md"
FINAL_REMARK = "☬SHΞN™"
MAX_LATENCY = 400  # کمی بالاتر به دلیل تست ساده‌تر
MAX_FINAL_NODES = 150
MAX_WORKERS = 100 # می‌توانیم تعداد را بالاتر ببریم چون تست سبک‌تر است

def get_sub_links():
    """لیست لینک‌های اشتراک را از فایل شما می‌خواند."""
    print("Fetching subscription links...")
    try:
        response = requests.get(SOURCE_URL, timeout=10)
        response.raise_for_status()
        links = response.text.strip().splitlines()
        print(f"Found {len(links)} subscription links.")
        return [link for link in links if link.strip()]
    except requests.RequestException as e:
        print(f"Error fetching source file: {e}")
        return []

def decode_base64_content(content):
    """محتوای Base64 را با مدیریت خطا دیکد می‌کند."""
    try:
        missing_padding = len(content) % 4
        if missing_padding:
            content += '=' * (4 - missing_padding)
        return base64.b64decode(content).decode('utf-8')
    except Exception:
        return None

def extract_server_port(link):
    """از لینک vless یا vmess، آدرس سرور و پورت را استخراج می‌کند."""
    try:
        if link.startswith('vless://'):
            parsed_url = urlparse(link)
            return parsed_url.hostname, parsed_url.port
        elif link.startswith('vmess://'):
            decoded_json = json.loads(decode_base64_content(link.replace("vmess://", "")))
            return decoded_json.get('add'), int(decoded_json.get('port'))
    except Exception:
        return None, None
    return None, None

def get_all_nodes(links):
    """تمام کانفیگ‌های vless و vmess را از لینک‌ها استخراج می‌کند."""
    all_nodes = []
    seen_identifiers = set()

    for link in links:
        try:
            print(f"Processing link: {link[:40]}...")
            response = requests.get(link, timeout=15)
            content = response.text.strip()
            
            decoded_content = decode_base64_content(content)
            if not decoded_content:
                decoded_content = content

            for line in decoded_content.splitlines():
                line = line.strip()
                if line.startswith('vless://') or line.startswith('vmess://'):
                    server, port = extract_server_port(line)
                    if server and port:
                        identifier = f"{server}:{port}"
                        if identifier not in seen_identifiers:
                            all_nodes.append(line)
                            seen_identifiers.add(identifier)
        except Exception as e:
            print(f"  Could not process link. Error: {e}")
            
    print(f"\nFound {len(all_nodes)} unique VLESS/VMESS nodes in total.")
    return all_nodes

def check_connectivity(node_link):
    """با یک تست اتصال ساده TCP، سلامت و پینگ سرور را چک می‌کند."""
    server, port = extract_server_port(node_link)
    if not server or not port:
        return None, None
    
    try:
        start_time = time.time()
        # تلاش برای ایجاد یک اتصال TCP با تایم‌اوت 3 ثانیه
        sock = socket.create_connection((server, port), timeout=3)
        latency = (time.time() - start_time) * 1000
        sock.close()
        
        if latency < MAX_LATENCY:
            print(f"  [SUCCESS] {server}:{port} -> Latency: {int(latency)}ms")
            return node_link, int(latency)
        return None, None
    except (socket.timeout, socket.error):
        return None, None

def run_health_check(nodes):
    """تست سلامت را به صورت موازی روی تمام کانفیگ‌ها اجرا می‌کند."""
    print(f"\nRunning health check on {len(nodes)} nodes...")
    healthy_nodes = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_node = {executor.submit(check_connectivity, node): node for node in nodes}
        for future in as_completed(future_to_node):
            node, latency = future.result()
            if node and latency:
                healthy_nodes.append({'link': node, 'latency': latency})
    print(f"\nFound {len(healthy_nodes)} healthy nodes with latency < {MAX_LATENCY}ms.")
    return healthy_nodes

def generate_final_sub(nodes):
    """کانفیگ‌های سالم را مرتب کرده، نامشان را تغییر داده و به فرمت نهایی تبدیل می‌کند."""
    print("Generating final subscription file...")
    nodes.sort(key=lambda x: x.get('latency', 9999))
    final_nodes = nodes[:MAX_FINAL_NODES]
    
    final_links = []
    for node_data in final_nodes:
        link = node_data['link']
        # تغییر نام (remark) در لینک‌ها
        if link.startswith('vless://'):
            link = link.split('#')[0] + '#' + FINAL_REMARK
        elif link.startswith('vmess://'):
            try:
                decoded_json_str = decode_base64_content(link.replace("vmess://", ""))
                if decoded_json_str:
                    vmess_json = json.loads(decoded_json_str)
                    vmess_json['ps'] = FINAL_REMARK
                    encoded_part = base64.b64encode(json.dumps(vmess_json).encode()).decode()
                    link = "vmess://" + encoded_part
            except Exception:
                pass # اگر نشد، همان لینک اصلی را نگه می‌داریم
        final_links.append(link)

    final_content = "\n".join(final_links)
    final_base64 = base64.b64encode(final_content.encode()).decode()
    
    node_count = len(final_links)
    print(f"Final subscription created with {node_count} nodes.")
    print(f"::set-output name=node_count::{node_count}")
    return final_base64

if __name__ == "__main__":
    sub_links = get_sub_links()
    if sub_links:
        nodes = get_all_nodes(sub_links)
        if nodes:
            healthy = run_health_check(nodes)
            if healthy:
                final_sub = generate_final_sub(healthy)
                with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                    f.write(final_sub)
                print(f"\n✅ Process completed! Output saved to {OUTPUT_FILE}")
