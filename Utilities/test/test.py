import requests
BASE = "http://localhost:5055"
folds = requests.get(f"{BASE}/api/folders").json()["folders"]
print("folders:", len(folds))
if folds:
    top = folds[0]
    g, s, c = top["game"], top["set"], top["count"]
    print(f"top: {g!r} / {s!r} count={c}")
    d = requests.get(f"{BASE}/api/pending_batch", params={"game": g, "set": s}).json()
    print("filtered pending_batch:", d.get("pending"), "cards:", len(d.get("cards", [])), "done:", d.get("done"))
else:
    print("/api/folders returned nothing on :5055")
