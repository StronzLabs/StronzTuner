import os
import sys
import requests
import re
import json
import base64

from concurrent.futures import ThreadPoolExecutor, as_completed

domaint_fmt = "https://{domain}.{tld}"


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
        domains = set(re.findall(rf"\b{domain}\.[a-zA-Z]+", response.text))
        return [domain.split(".")[-1].upper() for domain in domains]
    except requests.exceptions.RequestException:
        pass

    return set()


def extract_from_lookup(domain) -> set[str]:
    global lookup_service

    try:
        response = requests.get(
            f"{lookup_service}/{domain}", timeout=5, allow_redirects=False
        )
        domains = response.text.strip().split("\n")
        return [domain.split(".")[-1].upper() for domain in domains]
    except requests.exceptions.RequestException:
        pass

    return set()


def verify_tlds(domain, tlds, validator, scope, site_id):
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = []

        for tld in tlds:
            test_domain = domaint_fmt.format(domain=domain, tld=tld)
            futures += [executor.submit(validate_domain, test_domain, validator)]

            for future in as_completed(futures):
                if future.result() == True:
                    print(f"Site #{site_id+1} found in {scope}", file=sys.stderr)
                    executor.shutdown(wait=False, cancel_futures=True)
                    return tld

        print(f"Site #{site_id+1} not found in {scope}", file=sys.stderr)
        return None


def find_domain(i, site, cache_tld):
    domain = site["domain"]
    validator = site["validator"]

    # Check the cache first
    if cache_tld and (tld := verify_tlds(domain, [cache_tld], validator, "cache", i)):
        return tld

    if (fast_path := site.get("fast_path")) and (
        tld := verify_tlds(
            domain, extract_from_fastpath(fast_path, domain), validator, "fastpath", i
        )
    ):
        return tld

    if lookup_service and (
        tld := verify_tlds(domain, extract_from_lookup(domain), validator, "lookup", i)
    ):
        return tld

    if tld := verify_tlds(domain, tlds, validator, "all tlds", i):
        return tld


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


def parse_cache():
    cache = os.getenv("CACHE")
    assert cache is not None, "CACHE environment variable is not set"
    return base64.b64decode(cache).decode().strip().split("|")


def parse_config():
    config_str = os.getenv("CONFIG")
    assert config_str is not None, "JSON environment variable is not set"

    config_str = base64.b64decode(config_str).decode().strip()
    return json.loads(config_str)


def cache_all_tlds():
    # Fetch the list of TLDs
    tlds_response = requests.get("https://data.iana.org/TLD/tlds-alpha-by-domain.txt")
    assert tlds_response.status_code == 200, "Failed to fetch TLDs"

    return tlds_response.text.splitlines()[1:]  # Skip the first line


cache = parse_cache()
config = parse_config()
tlds = cache_all_tlds()

lookup_service = config.get("lookup_service")
sites = config["sites"]

if len(cache) != len(sites):
    print(
        f"Cache length does not match sites length. Cache len:{len(cache)} != Sites len:{len(sites)}. Skipping it",
        file=sys.stderr,
    )
    cache = [None] * len(sites)

out = find_domains(sites, cache)

encoded_out = base64.b64encode(out.encode()).decode()

print(encoded_out)
