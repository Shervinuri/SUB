import os
import requests
import base64
import json
import socket
import time
from urllib.parse import urlparse, unquote, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- تنظیمات اصلی ---
SOURCE_URL = "https://raw.githubusercontent.com/Shervinuri/SUB/main/Source.txt"
OUTPUT_FILE = "pure.md"
FINAL_REMARK = "☬SHΞN™"
MAX_LATENCY = 350
MAX_FINAL_NODES = 150
MAX_WORKERS = 100

# --- الگوی اولویت‌بندی ---
PRIORITY_PROTOCOLS = {'ws', 'grpc'}

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
        content += '=' * (-len(content) % 4)
        return base64.b64decode(content).decode('utf-8')
    except Exception:
        return None

def parse_node_details(link):
    """جزئیات کامل یک لینک را برای فیلتر و مرتب‌سازی استخراج می‌کند."""
    details = {}
    try:
        if link.startswith('vless://'):
            parsed_url = urlparse(link)
            if not parsed_url.hostname or not parsed_url.port: return None
            details['server'] = parsed_url.hostname
            details['port'] = parsed_url.port
            params = parse_qs(parsed_url.query)
            details['protocol'] = params.get('type', ['tcp'])[0]
            details['link'] = link
            return details
        elif link.startswith('vmess://'):
            decoded_json = json.loads(decode_base64_content(link.replace("vmess://", "")))
            if not decoded_json.get('add') or not decoded_json.get('port'): return None
            details['server'] = decoded_json.get('add')
            details['port'] = int(decoded_json.get('port'))
            details['protocol'] = decoded_json.get('net', 'tcp')
            details['link'] = link
            return details
    except Exception:
        return None
    return details

def get_all_nodes(links):
    """تمام کانفیگ‌های vless و vmess را از لینک‌ها استخراج می‌کند."""
    all_nodes = []
    seen_identifiers = set()
    for link in links:
        try:
            response = requests.get(link, timeout=15)
            content = response.text.strip()
            decoded_content = decode_base64_content(content) or content
            for line in decoded_content.splitlines():
                line = line.strip()
                if line.startswith(('vless://', 'vmess://')):
                    details = parse_node_details(line)
                    if details:
                        identifier = f"{details['server']}:{details['port']}"
                        if identifier not in seen_identifiers:
                            all_nodes.append(details)
                            seen_identifiers.add(identifier)
        except Exception:
            continue
    print(f"\nFound {len(all_nodes)} unique VLESS/VMESS nodes to test.")
    return all_nodes

def check_connectivity(node_details):
    """با یک تست اتصال ساده TCP، سلامت و پینگ سرور را چک می‌کند."""
    server, port = node_details['server'], node_details['port']
    try:
        start_time = time.time()
        sock = socket.create_connection((server, port), timeout=3)
        latency = (time.time() - start_time) * 1000
        sock.close()
        if latency < MAX_LATENCY:
            return node_details, int(latency)
    except (socket.timeout, socket.error, OSError):
        pass
    return None, None

def run_health_check(nodes):
    """تست سلامت را به صورت موازی روی تمام کانفیگ‌ها اجرا می‌کند."""
    if not nodes: return []
    print(f"\nRunning health check on all {len(nodes)} nodes (this may take a moment)...")
    healthy_nodes = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_node = {executor.submit(check_connectivity, node): node for node in nodes}
        for i, future in enumerate(as_completed(future_to_node)):
            node, latency = future.result()
            if node and latency:
                node['latency'] = latency
                healthy_nodes.append(node)
            print(f"\rProgress: {i + 1}/{len(nodes)} nodes tested...", end="")

    print(f"\n\nFound {len(healthy_nodes)} healthy nodes with latency < {MAX_LATENCY}ms.")
    return healthy_nodes

def sort_and_finalize(nodes):
    """کانفیگ‌ها را بر اساس اولویت پروتکل و سپس پینگ مرتب می‌کند."""
    print("Sorting nodes based on priority (ws, grpc) and latency...")
    
    def get_sort_key(node):
        priority = 1 if node.get('protocol') in PRIORITY_PROTOCOLS else 2
        latency = node.get('latency', 9999)
        return (priority, latency)

    nodes.sort(key=get_sort_key)
    final_nodes = nodes[:MAX_FINAL_NODES]
    
    final_links = []
    for node_details in final_nodes:
        link = node_details['link']
        try:
            if link.startswith('vless://'):
                link = link.split('#')[0] + '#' + FINAL_REMARK
            elif link.startswith('vmess://'):
                decoded_json_str = decode_base64_content(link.replace("vmess://", ""))
                if decoded_json_str:
                    vmess_json = json.loads(decoded_json_str)
                    vmess_json['ps'] = FINAL_REMARK
                    encoded_part = base64.b64encode(json.dumps(vmess_json).encode()).decode().replace('=', '')
                    link = "vmess://" + encoded_part
            final_links.append(link)
        except Exception:
            continue

    final_content = "\n".join(final_links)
    final_base64 = base64.b64encode(final_content.encode()).decode()
    
    node_count = len(final_links)
    print(f"Final subscription created with {node_count} nodes.")
    print(f"::set-output name=node_count::{node_count}")
    return final_base64

if __name__ == "__main__":
    sub_links = get_sub_links()
    if sub_links:
        all_nodes = get_all_nodes(sub_links)
        if all_nodes:
            healthy_nodes = run_health_check(all_nodes)
            if healthy_nodes:
                final_sub = sort_and_finalize(healthy_nodes)
                with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                    f.write(final_sub)
                print(f"\n✅ Process completed! Output saved to {OUTPUT_FILE}")
