import os
import requests
import base64
import json
import socket
import time
import ipaddress
from urllib.parse import urlparse, unquote, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- تنظیمات اصلی ---
SOURCE_URL = "https://raw.githubusercontent.com/Shervinuri/SUB/main/Source.txt"
OUTPUT_FILE = "pure.md"
FINAL_REMARK = "☬SHΞN™"
# --- معیار سخت‌گیرانه‌تر ---
MAX_LATENCY = 250
MAX_FINAL_NODES = 150
MAX_WORKERS = 100

# --- فیلترهای هوشمند ---
CLOUDFLARE_IPV4_RANGES = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "172.64.0.0/13", "131.0.72.0/22"
]
PREFERRED_PORTS = {443, 8443, 2096, 2083, 2053, 80, 8080, 8880}

def get_sub_links():
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
    try:
        content += '=' * (-len(content) % 4)
        return base64.b64decode(content).decode('utf-8')
    except Exception:
        return None

def parse_node_details(link):
    details = {}
    try:
        if link.startswith('vless://'):
            parsed_url = urlparse(link)
            if not parsed_url.hostname or not parsed_url.port: return None
            details['server'] = parsed_url.hostname
            details['port'] = parsed_url.port
            params = parse_qs(parsed_url.query)
            details['type'] = params.get('type', ['tcp'])[0]
            return details
        elif link.startswith('vmess://'):
            decoded_json = json.loads(decode_base64_content(link.replace("vmess://", "")))
            if not decoded_json.get('add') or not decoded_json.get('port'): return None
            details['server'] = decoded_json.get('add')
            details['port'] = int(decoded_json.get('port'))
            details['type'] = decoded_json.get('net', 'tcp')
            return details
    except Exception:
        return None
    return details

def is_cloudflare_ip(ip_str):
    if not isinstance(ip_str, str): return False
    try:
        ip = ipaddress.ip_address(ip_str)
        for cidr in CLOUDFLARE_IPV4_RANGES:
            if ip in ipaddress.ip_network(cidr):
                return True
    except ValueError:
        return False
    return False

def get_all_nodes(links):
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
                            all_nodes.append(line)
                            seen_identifiers.add(identifier)
        except Exception:
            continue
    print(f"\nFound {len(all_nodes)} unique VLESS/VMESS nodes in total.")
    return all_nodes

def pre_filter_nodes(nodes):
    print("Applying smart pre-filter...")
    high_potential_nodes = []
    for link in nodes:
        details = parse_node_details(link)
        if not details: continue
        if is_cloudflare_ip(details.get('server')):
            if details.get('type') == 'ws' and details.get('port') in PREFERRED_PORTS:
                high_potential_nodes.append(link)
    print(f"Found {len(high_potential_nodes)} high-potential nodes matching the pattern.")
    return high_potential_nodes

def check_connectivity(node_link):
    details = parse_node_details(node_link)
    if not details: return None, None
    server, port = details['server'], details['port']
    try:
        start_time = time.time()
        sock = socket.create_connection((server, port), timeout=3)
        latency = (time.time() - start_time) * 1000
        sock.close()
        if latency < MAX_LATENCY:
            # print(f"  [SUCCESS] {server}:{port} -> Latency: {int(latency)}ms") # لاگ اضافه
            return node_link, int(latency)
    except (socket.timeout, socket.error, OSError):
        pass
    return None, None

def run_health_check(nodes):
    if not nodes: return []
    print(f"\nRunning health check on {len(nodes)} high-potential nodes...")
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
    print("Generating final subscription file...")
    nodes.sort(key=lambda x: x.get('latency', 9999))
    # --- منطق جدید و هوشمند ---
    # دیگر همیشه 150 تا نیست. فقط بهترین‌ها تا سقف 150 تا انتخاب می‌شوند.
    final_nodes = nodes[:MAX_FINAL_NODES]
    
    final_links = []
    for node_data in final_nodes:
        link = node_data['link']
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
            potential_nodes = pre_filter_nodes(all_nodes)
            healthy_nodes = run_health_check(potential_nodes)
            if healthy_nodes:
                final_sub = generate_final_sub(healthy_nodes)
                with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                    f.write(final_sub)
                print(f"\n✅ Process completed! Output saved to {OUTPUT_FILE}")
