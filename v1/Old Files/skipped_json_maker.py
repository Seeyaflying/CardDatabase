import os
import json

# ==============================================================
# CONFIGURATION
# ==============================================================
# Hardcoded path for your Google Drive folder
SCAN_FOLDER = r"G:/My Drive/Skipped Cards"

# The name of the file that will be created
OUTPUT_FILE = "skipped_output.json"


# ==============================================================

def run_pre_scan():
    print("\n" + "=" * 45)
    print("      TCG FILENAME TO JSON CONVERTER")
    print("=" * 45)

    # Use hardcoded path; fall back to input if empty
    target_dir = SCAN_FOLDER if SCAN_FOLDER else input("Paste the folder path to scan: ").strip()
    target_dir = target_dir.replace('"', '')

    if not target_dir or not os.path.exists(target_dir):
        print(f"Error: Invalid or missing path '{target_dir}'")
        return

    print(f"Scanning folder: {target_dir}...")

    skipped_data = []
    extensions = ('.png', '.jpg', '.jpeg', '.webp')

    try:
        files = [f for f in os.listdir(target_dir) if f.lower().endswith(extensions)]

        for filename in files:
            name_only = os.path.splitext(filename)[0]

            # Logic: _200w = English, everything else = Japanese
            if "_200w" in name_only:
                image_id = name_only.replace("_200w", "")
                lang = "english"
            else:
                image_id = name_only
                lang = "japanese"

            skipped_data.append({
                "image_name": image_id,
                "language": lang
            })

        # Sort alphabetically by image_name so the list is organized
        skipped_data.sort(key=lambda x: x['image_name'])

        # --- ONE LINE PER ENTRY FORMATTING ---
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write("[\n")
            for i, entry in enumerate(skipped_data):
                # dumps creates the single-line string for the dictionary
                line = json.dumps(entry)

                # Add comma for all but the last item
                comma = "," if i < len(skipped_data) - 1 else ""
                f.write(f"  {line}{comma}\n")
            f.write("]")

        print("-" * 45)
        print(f"SUCCESS! Created {OUTPUT_FILE}")
        print(f"Total entries: {len(skipped_data)}")
        print("-" * 45)

    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    run_pre_scan()