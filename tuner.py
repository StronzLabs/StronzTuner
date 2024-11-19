import os
import sys
import requests
import re
import json
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

# Set variable "cache" as the environment variable or default value
cache = os.getenv('CACHE')
assert cache is not None, "CACHE environment variable is not set"
cache = base64.b64decode(cache).decode().strip().split("|")

# Set variable "json" as the environment variable or default value
json_data = os.getenv('JSON')
assert json_data is not None, "JSON environment variable is not set"
json_data = base64.b64decode(json_data).decode().strip()

# Fetch the list of TLDs
tlds_response = requests.get(
    "https://data.iana.org/TLD/tlds-alpha-by-domain.txt")
assert tlds_response.status_code == 200, "Failed to fetch TLDs"

tlds = tlds_response.text.splitlines()[1:]  # Skip the first line


def check_domain_cache(domain, tld, validator):
    try:
        response = requests.get(
            f"https://{domain}.{tld}", timeout=5, allow_redirects=True)
        if re.search(re.escape(validator), response.text):
            tld = urlparse(response.url).hostname.split(".")[-1].upper()
            return tld
    except requests.exceptions.RequestException:
        pass
    return None


def validate_domain(url, validator):
    try:
        response = requests.get(url, timeout=5, allow_redirects=False)
        if re.search(re.escape(validator), response.text):
            return True
    except requests.exceptions.RequestException:
        pass
    return False

def extract_from_fastpath(fast_path, domain) -> set[str]:
    try:
        response = requests.get(fast_path, timeout=5, allow_redirects=True)
        domains = set(re.findall(rf'\b{domain}\.[a-zA-Z]+', response.text))
        return [domain.split(".")[-1].upper() for domain in domains]
    except requests.exceptions.RequestException:
        pass

    return set()
    
def find_domain(i, site, cache_tld):
    domain = site["domain"]
    validator = site["validator"]

    # Helper function to check each TLD in parallel
    def check_tld(tld):
        full_url = f"https://{domain}.{tld}"
        if validate_domain(full_url, validator):
            return tld
        return None

    # Check the cache first
    if cache_tld:
        tld = check_domain_cache(domain, cache_tld, validator)
        
        if tld:
            print(f"Site #{i+1} found in cache", file=sys.stderr)
            return tld
        else:
            print(f"Site #{i+1} not found in cache", file=sys.stderr)

    if fast_path := site.get("fast_path"):
        tlds_fastpath = extract_from_fastpath(fast_path, domain)

        for tld in tlds_fastpath:
            if validate_domain(f"https://{domain}.{tld}", validator):
                print(f"Site #{i+1} found in fastpath", file=sys.stderr)
                return tld
            
    print(f"Site #{i+1} not found in fastpath", file=sys.stderr)        

    # Run the TLD checks in parallel
    with ThreadPoolExecutor(max_workers=100) as executor:

        futures = [executor.submit(check_tld, tld) for tld in tlds]

        # Wait for the first successful result
        for future in as_completed(futures):
            tld = future.result()
            if tld:
                executor.shutdown(wait=False, cancel_futures=True)
                return tld
        return None


def find_domains(sites, cache):
    domains = []
    domain_idx = range(len(sites))
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(find_domain, domain_idx, sites, cache))

    for i, result in enumerate(results):
        if result:
            domains.append(result)
        else:
            raise Exception(f"Failed to find domain #{i+1}")

    return "|".join(domains)


def main():
    global cache

    sites = json.loads(json_data)["sites"]

    if len(cache) != len(sites):
        print(
            f"Cache length does not match sites length. Cache len:{len(cache)} != Sites len:{len(sites)}. Skipping it", file=sys.stderr)
        cache = [None] * len(sites)

    out = find_domains(sites, cache)

    encoded_out = base64.b64encode(out.encode()).decode()
    print(encoded_out)


main()
