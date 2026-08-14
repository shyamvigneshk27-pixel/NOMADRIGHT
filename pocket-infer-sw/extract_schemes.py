import json
import os

with open("all_20_schemes.json", "r") as f:
    data = json.load(f)

existing = {"onorc_pds", "pmjay", "eshram", "bocw", "mgnregs"}

os.makedirs("nomadright", exist_ok=True)

for scheme in data["schemes"]:
    sid = scheme["scheme_id"]
    if sid not in existing:
        with open(f"nomadright/{sid}.json", "w") as out:
            json.dump(scheme, out, indent=2)
        print(f"Extracted {sid}.json")

