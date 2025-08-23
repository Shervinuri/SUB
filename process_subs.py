import os
import requests
import yaml
import base64
import json
import subprocess
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- تنظیمات اصلی ---
# آدرس فایل حاوی لینک‌های اشتراک شما
SOURCE_URL = "https://raw.githubusercontent.com/Shervinuri/SUB/main/Source.txt"
# نام فایل خروجی نهایی
OUTPUT_FILE = "pure.md"
# ریمارک (نام) نهایی برای تمام کانفیگ‌ها
FINAL_REMARK = "☬SHΞN™"
# آدرس URL برای تست پینگ و سرعت (یک آدرس سبک و سریع از گوگل)
PING_TEST_URL = "http://play.googleapis.com/generate_204"
# حداکثر پینگ قابل قبول به میلی‌ثانیه (شرط سخت‌گیرانه)
MAX_LATENCY = 350
# حداکثر تعداد کانفیگ در خروجی نهایی (برای جلوگیری از هنگ کردن کلاینت)
MAX_FINAL_NODES = 150
# تعداد تردها برای تست همزمان کانفیگ‌ها
MAX_WORKERS = 50

def get_sub_links():
    """از فایل شما در گیت‌هاب، لیست لینک‌های اشتراک را می‌خواند."""
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

def get_nodes_from_subconverter(links):
    """تمام لینک‌ها را به subconverter می‌دهد و یک لیست کامل از کانفیگ‌ها در فرمت YAML می‌گیرد."""
    print("Getting all nodes from subconverter...")
    url_param = "|".join(links)
    subconverter_url = f"http://127.0.0.1:25500/sub?target=clash&url={url_param}&config=https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/config/ACL4SSR_Online.ini"
    
    try:
        response = requests.get(subconverter_url, timeout=60)
        response.raise_for_status()
        config = yaml.safe_load(response.text)
        if 'proxies' in config and config['proxies']:
            print(f"Successfully fetched {len(config['proxies'])} nodes.")
            return config['proxies']
    except (requests.RequestException, yaml.YAMLError, KeyError) as e:
        print(f"Error getting nodes from subconverter: {e}")
    return []

def filter_and_deduplicate(nodes):
    """کانفیگ‌ها را برای vmess/vless فیلتر و موارد تکراری را حذف می‌کند."""
    print("Filtering for VLESS/VMESS and removing duplicates...")
    valid_nodes = []
    seen_nodes = set()

    for node in nodes:
        if node.get('type') in ['vmess', 'vless']:
            # یک شناسه منحصر به فرد برای هر سرور ایجاد می‌کنیم
            identifier = f"{node.get('server')}:{node.get('port')}"
            if identifier not in seen_nodes:
                valid_nodes.append(node)
                seen_nodes.add(identifier)
    
    print(f"Found {len(valid_nodes)} unique VLESS/VMESS nodes.")
    return valid_nodes

def test_latency(node, index):
    """یک کانفیگ را با استفاده از Clash تست می‌کند و زمان تاخیر (latency) را برمی‌گرداند."""
    # ساخت یک فایل کانفیگ موقت فقط برای این یک نود
    config = {
        'proxies': [node],
        'proxy-groups': [{
            'name': 'test-group',
            'type': 'select',
            'proxies': [node['name']]
        }],
        'rules': []
    }
    config_filename = f"temp_config_{index}.yaml"
    with open(config_filename, 'w', encoding='utf-8') as f:
        yaml.dump(config, f)

    # اجرای تست سرعت با Clash
    try:
        # Clash URL test command: ./clash -d . -f config.yaml --url-test http://...
        # We check the exit code and output for latency info. A simpler way is to test connectivity.
        # Let's use the connectivity test feature which is faster.
        # The command `clash -t -f <config_file>` checks syntax. We need a real speed test.
        # The most reliable way is to run clash and curl through it.
        
        clash_process = subprocess.Popen(
            ['./clash', '-d', '.', '-f', config_filename, '-p', str(7890 + index)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        # Give Clash a moment to start
        time.sleep(2)

        # Use curl to test through the Clash proxy
        proxy_url = f"http://127.0.0.1:{7890 + index}"
        start_time = time.time()
        
        result = subprocess.run(
            ['curl', '-s', '--proxy', proxy_url, PING_TEST_URL, '--max-time', '5', '-o', '/dev/null'],
            capture_output=True
        )
        
        latency = (time.time() - start_time) * 1000  # Convert to ms
        
        clash_process.terminate() # Ensure process is killed
        os.remove(config_filename) # Clean up temp file

        if result.returncode == 0 and latency < MAX_LATENCY:
            print(f"  [SUCCESS] {node['name']} -> Latency: {int(latency)}ms")
            return node, int(latency)
        else:
            # print(f"  [FAILED] {node['name']} -> Latency: {int(latency)}ms or Timed out")
            return None, None

    except Exception as e:
        # print(f"  [ERROR] Testing {node['name']}: {e}")
        if 'clash_process' in locals() and clash_process.poll() is None:
            clash_process.terminate()
        if os.path.exists(config_filename):
            os.remove(config_filename)
        return None, None


def run_speed_test(nodes):
    """تست سرعت را به صورت موازی روی تمام کانفیگ‌ها اجرا می‌کند."""
    print(f"\nRunning speed test on {len(nodes)} nodes with {MAX_WORKERS} workers (this will take a while)...")
    healthy_nodes = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_node = {executor.submit(test_latency, node, i): node for i, node in enumerate(nodes)}
        
        for future in as_completed(future_to_node):
            node, latency = future.result()
            if node and latency:
                node['latency'] = latency
                healthy_nodes.append(node)

    print(f"\nFound {len(healthy_nodes)} healthy nodes with latency < {MAX_LATENCY}ms.")
    return healthy_nodes


def generate_final_sub(nodes):
    """کانفیگ‌های نهایی را به فرمت Base64 تبدیل کرده و نام آن‌ها را تغییر می‌دهد."""
    print("Generating final subscription link...")
    # ابتدا نودها را بر اساس سرعت مرتب می‌کنیم
    nodes.sort(key=lambda x: x.get('latency', 9999))
    
    # بهترین‌ها را تا سقف مشخص شده انتخاب می‌کنیم
    final_nodes_yaml = nodes[:MAX_FINAL_NODES]

    # برای تبدیل به لینک خام، دوباره از subconverter استفاده می‌کنیم
    temp_yaml_file = "final_nodes.yaml"
    with open(temp_yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump({'proxies': final_nodes_yaml}, f)

    # خواندن فایل و ارسال محتوا به subconverter
    with open(temp_yaml_file, 'r', encoding='utf-8') as f:
        yaml_content = f.read()

    try:
        # استفاده از قابلیت rename در subconverter برای تغییر نام همه کانفیگ‌ها
        rename_rule = f"&rename=^.*@{re.escape(FINAL_REMARK)}"
        subconverter_url = f"http://127.0.0.1:25500/sub?target=mixed&list=true{rename_rule}"
        
        response = requests.post(subconverter_url, data=yaml_content, timeout=30)
        response.raise_for_status()
        
        # محتوای Base64 را برمی‌گردانیم
        final_sub_content = response.text
        os.remove(temp_yaml_file) # Clean up
        
        print(f"Final subscription created with {len(final_nodes_yaml)} nodes.")
        # Set output for GitHub Actions
        print(f"::set-output name=node_count::{len(final_nodes_yaml)}")
        return final_sub_content

    except requests.RequestException as e:
        print(f"Error generating final subscription: {e}")
        os.remove(temp_yaml_file) # Clean up
        return ""

if __name__ == "__main__":
    # اجرای subconverter در پس‌زمینه
    subconverter_process = subprocess.Popen(
        ['./subconverter/subconverter'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print("Subconverter started...")
    time.sleep(3) # چند ثانیه فرصت برای اجرا شدن

    # --- شروع فرآیند اصلی ---
    links = get_sub_links()
    if links:
        all_nodes = get_nodes_from_subconverter(links)
        if all_nodes:
            unique_nodes = filter_and_deduplicate(all_nodes)
            if unique_nodes:
                healthy_nodes = run_speed_test(unique_nodes)
                if healthy_nodes:
                    final_subscription = generate_final_sub(healthy_nodes)
                    if final_subscription:
                        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                            f.write(final_subscription)
                        print(f"\n✅ Process completed successfully! Output saved to {OUTPUT_FILE}")
    
    # --- پایان فرآیند ---
    subconverter_process.terminate()
    print("Subconverter stopped.")

