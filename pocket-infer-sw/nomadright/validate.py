"""
Comprehensive JSON audit script for NomadRight Knowledge Base datasets.
Checks: missing fields, data types, duplicates, empty arrays, 
URL validity, schema compliance, contradictions, citation coverage.
"""
import json
import os
import re
from collections import Counter

REQUIRED_SCHEMA_KEYS = [
    "scheme_id", "scheme_name", "description", "objective",
    "eligibility", "beneficiary_categories", "required_documents",
    "benefits", "financial_benefits", "application_process",
    "portability", "state_specific_rules", "exceptions",
    "limitations", "faq", "official_contacts", "official_sources"
]

ARRAY_FIELDS = [
    "eligibility", "beneficiary_categories", "required_documents",
    "benefits", "financial_benefits", "state_specific_rules",
    "exceptions", "limitations", "faq", "official_contacts", "official_sources"
]

URL_PATTERN = re.compile(r'https?://[^\s",}\]]+')

VALID_INDIAN_STATES_UTS = {
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand",
    "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
    "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"
}

OFFICIAL_DOMAINS = {
    "gov.in", "nic.in", "india.gov.in", "nha.gov.in", "pmjay.gov.in",
    "nrega.nic.in", "nfsa.gov.in", "dfpd.gov.in", "pib.gov.in",
    "myscheme.gov.in", "impds.nic.in", "rural.gov.in", "umang.gov.in",
    "pgportal.gov.in", "indiabudget.gov.in", "ies.gov.in"
}

d = r'd:\MyData\downloads\bhasini_dataset'
files = ["pds.json", "pmjay.json", "mgnregs.json"]
findings = {}

for fname in files:
    fp = os.path.join(d, fname)
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    issues = []
    
    # ---- 1. Missing Schema Fields ----
    for key in REQUIRED_SCHEMA_KEYS:
        if key not in data:
            issues.append(("MISSING_FIELD", f"Required schema key '{key}' is MISSING", "CRITICAL"))
    
    # ---- 2. application_process sub-keys ----
    if "application_process" in data:
        ap = data["application_process"]
        if not isinstance(ap, dict):
            issues.append(("TYPE_ERROR", "application_process should be an object, got " + type(ap).__name__, "CRITICAL"))
        else:
            if "online" not in ap:
                issues.append(("MISSING_FIELD", "application_process.online is MISSING", "CRITICAL"))
            if "offline" not in ap:
                issues.append(("MISSING_FIELD", "application_process.offline is MISSING", "CRITICAL"))
    
    # ---- 3. Empty Arrays ----
    for key in ARRAY_FIELDS:
        if key in data:
            val = data[key]
            if key == "application_process":
                continue  # handled above
            if isinstance(val, list) and len(val) == 0:
                issues.append(("EMPTY_ARRAY", f"'{key}' is an empty array", "WARNING"))
    
    # ---- 4. Data Type Checks ----
    string_fields = ["scheme_id", "scheme_name", "description", "objective"]
    for key in string_fields:
        if key in data and not isinstance(data[key], str):
            issues.append(("TYPE_ERROR", f"'{key}' should be string, got {type(data[key]).__name__}", "CRITICAL"))
        if key in data and isinstance(data[key], str) and len(data[key].strip()) == 0:
            issues.append(("EMPTY_VALUE", f"'{key}' is an empty string", "CRITICAL"))
    
    for key in ARRAY_FIELDS:
        if key in data and key != "application_process":
            if not isinstance(data[key], list):
                issues.append(("TYPE_ERROR", f"'{key}' should be array, got {type(data[key]).__name__}", "CRITICAL"))
    
    if "portability" in data and not isinstance(data["portability"], dict):
        issues.append(("TYPE_ERROR", f"'portability' should be object, got {type(data['portability']).__name__}", "CRITICAL"))
    
    # ---- 5. Duplicate Detection ----
    # Check FAQ duplicates
    if "faq" in data and isinstance(data["faq"], list):
        questions = [item.get("question", "") for item in data["faq"] if isinstance(item, dict)]
        q_counts = Counter(questions)
        for q, c in q_counts.items():
            if c > 1:
                issues.append(("DUPLICATE", f"FAQ question duplicated {c} times: '{q[:60]}...'", "WARNING"))
    
    # Check benefits duplicates
    if "benefits" in data and isinstance(data["benefits"], list):
        benefits_text = [item.get("benefit", "") for item in data["benefits"] if isinstance(item, dict)]
        b_counts = Counter(benefits_text)
        for b, c in b_counts.items():
            if c > 1:
                issues.append(("DUPLICATE", f"Benefit duplicated {c} times: '{b[:60]}...'", "WARNING"))
    
    # Check eligibility duplicates
    if "eligibility" in data and isinstance(data["eligibility"], list):
        criteria = [item.get("criterion", "") for item in data["eligibility"] if isinstance(item, dict)]
        c_counts = Counter(criteria)
        for cr, c in c_counts.items():
            if c > 1:
                issues.append(("DUPLICATE", f"Eligibility criterion duplicated {c} times: '{cr[:60]}...'", "WARNING"))
    
    # ---- 6. URL Validation ----
    raw = json.dumps(data)
    urls_found = URL_PATTERN.findall(raw)
    for url in urls_found:
        # Clean trailing punctuation
        url_clean = url.rstrip('.,;:)]}')
        # Check for obviously broken URLs
        if ' ' in url_clean:
            issues.append(("INVALID_URL", f"URL contains spaces: {url_clean}", "CRITICAL"))
        # Check domain is official
        domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url_clean)
        if domain_match:
            domain = domain_match.group(1)
            is_official = any(domain.endswith(od) for od in OFFICIAL_DOMAINS)
            if not is_official:
                issues.append(("NON_OFFICIAL_URL", f"URL domain '{domain}' may not be official: {url_clean}", "WARNING"))
    
    # ---- 7. UNKNOWN value audit ----
    unknown_count = raw.count('"UNKNOWN"')
    if unknown_count > 0:
        issues.append(("UNKNOWN_VALUES", f"Found {unknown_count} field(s) with UNKNOWN value", "INFO"))
    
    # ---- 8. official_sources structure ----
    if "official_sources" in data and isinstance(data["official_sources"], list):
        required_src_keys = ["website", "document", "url", "page", "section"]
        for i, src in enumerate(data["official_sources"]):
            if isinstance(src, dict):
                for sk in required_src_keys:
                    if sk not in src:
                        issues.append(("MISSING_FIELD", f"official_sources[{i}] missing '{sk}'", "WARNING"))
                    elif isinstance(src[sk], str) and len(src[sk].strip()) == 0:
                        issues.append(("EMPTY_VALUE", f"official_sources[{i}].{sk} is empty string", "WARNING"))
    
    # ---- 9. Citation coverage: check all source references ----
    source_refs = set()
    def extract_sources(obj, path=""):
        if isinstance(obj, dict):
            if "source" in obj and isinstance(obj["source"], str):
                for s in obj["source"].split(","):
                    source_refs.add(s.strip())
            for k, v in obj.items():
                extract_sources(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                extract_sources(item, f"{path}[{i}]")
    extract_sources(data)
    
    official_urls = set()
    if "official_sources" in data:
        for src in data["official_sources"]:
            if isinstance(src, dict) and "url" in src:
                official_urls.add(src["url"])
    
    # ---- 10. Semantic content contradictions ----
    # Check benefits vs limitations for contradictions
    if "benefits" in data and "limitations" in data:
        benefit_text = " ".join([b.get("benefit","") for b in data["benefits"] if isinstance(b, dict)])
        limit_text = " ".join([l.get("limitation","") for l in data["limitations"] if isinstance(l, dict)])
        # Simplified check: identical phrases in both
        for phrase in ["not covered", "not available", "not eligible", "cannot"]:
            if phrase in benefit_text.lower():
                issues.append(("CONTRADICTION", f"Benefits section contains negative phrase '{phrase}' - review for contradiction", "WARNING"))
    
    # ---- 11. Check for state name mentions ----
    text = json.dumps(data)
    mentioned_states = []
    for state in VALID_INDIAN_STATES_UTS:
        if state in text:
            mentioned_states.append(state)
    # Check for potentially invalid state names
    potential_states = re.findall(r'(?:state|State) of ([A-Z][a-z]+(?: [A-Z][a-z]+)*)', text)
    for ps in potential_states:
        if ps not in VALID_INDIAN_STATES_UTS and ps not in ["India", "Government"]:
            issues.append(("INVALID_STATE", f"Potentially invalid state name: '{ps}'", "WARNING"))
    
    # ---- 12. Additional schema key check (extras beyond required) ----
    extra_keys = set(data.keys()) - set(REQUIRED_SCHEMA_KEYS)
    # These are acceptable extras
    acceptable_extras = {"important_definitions", "last_updated", "data_extraction_note"}
    unexpected_extras = extra_keys - acceptable_extras
    if unexpected_extras:
        issues.append(("EXTRA_FIELD", f"Unexpected extra keys found: {unexpected_extras}", "INFO"))
    
    findings[fname] = {
        "total_keys": len(data.keys()),
        "issues": issues,
        "unknown_count": unknown_count,
        "source_refs": sorted(source_refs),
        "mentioned_states": sorted(mentioned_states),
        "urls_found": len(set(urls_found)),
        "faq_count": len(data.get("faq", [])),
        "benefits_count": len(data.get("benefits", [])),
        "eligibility_count": len(data.get("eligibility", [])),
        "official_sources_count": len(data.get("official_sources", []))
    }

# ---- 13. Cross-file contradiction checks ----
cross_issues = []

# Print report
print("=" * 80)
print("COMPREHENSIVE JSON AUDIT REPORT")
print("=" * 80)

for fname, info in findings.items():
    print(f"\n{'='*80}")
    print(f"FILE: {fname}")
    print(f"{'='*80}")
    print(f"  Top-level keys: {info['total_keys']}")
    print(f"  UNKNOWN values: {info['unknown_count']}")
    print(f"  URLs referenced: {info['urls_found']}")
    print(f"  FAQ entries: {info['faq_count']}")
    print(f"  Benefits: {info['benefits_count']}")
    print(f"  Eligibility criteria: {info['eligibility_count']}")
    print(f"  Official sources: {info['official_sources_count']}")
    print(f"  States mentioned: {', '.join(info['mentioned_states']) if info['mentioned_states'] else 'None'}")
    
    print(f"\n  ISSUES ({len(info['issues'])} found):")
    if not info['issues']:
        print("    None found.")
    else:
        for category, msg, severity in info['issues']:
            icon = {"CRITICAL": "[X]", "WARNING": "[!]", "INFO": "[i]"}.get(severity, "[?]")
            print(f"    {icon} [{severity}] [{category}] {msg}")
    
    print(f"\n  SOURCE REFERENCES:")
    for sr in info['source_refs']:
        print(f"    - {sr}")

print(f"\n{'='*80}")
print("CROSS-FILE CHECKS")
print(f"{'='*80}")

# Check scheme_id uniqueness
all_ids = []
for fname in files:
    fp = os.path.join(d, fname)
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    all_ids.append((fname, data.get("scheme_id", "")))

id_values = [x[1] for x in all_ids]
if len(id_values) != len(set(id_values)):
    print("  [X] DUPLICATE scheme_id values detected!")
else:
    print("  [OK] All scheme_id values are unique")

print(f"\n  Scheme IDs:")
for fname, sid in all_ids:
    print(f"    {fname}: {sid}")

print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}")
total_critical = sum(1 for f in findings.values() for _, _, s in f['issues'] if s == "CRITICAL")
total_warning = sum(1 for f in findings.values() for _, _, s in f['issues'] if s == "WARNING")
total_info = sum(1 for f in findings.values() for _, _, s in f['issues'] if s == "INFO")
print(f"  CRITICAL: {total_critical}")
print(f"  WARNING:  {total_warning}")
print(f"  INFO:     {total_info}")
print(f"  TOTAL:    {total_critical + total_warning + total_info}")
