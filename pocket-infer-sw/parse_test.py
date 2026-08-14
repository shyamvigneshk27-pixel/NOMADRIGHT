import json

with open("all_20_schemes.json", "r") as f:
    data = json.load(f)

for s in data["schemes"]:
    if s["scheme_id"] == "apy":
        print(json.dumps(s, indent=2))
        break
