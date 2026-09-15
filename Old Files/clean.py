import re

p = r"C:\Users\seeya\OneDrive\Desktop\temp.py"

with open(p, encoding="utf-8") as f:
    s = f.read()

# Remove zero-width spaces and other invisible non-printable characters
s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("Cleaned. Run temp.py again.")
