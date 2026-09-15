import shutil
from pathlib import Path
import config
import db

def _matrix_row(game, indexed, on_g, on_t, src_gone, missing_g, missing_t, orphans):
    flag = "OK " if (missing_g == 0 and missing_t == 0 and orphans == 0) else "!! "
    return (f"{flag}{game:<28} {indexed:>6} {on_g:>6} {on_t:>6} "
            f"{src_gone:>5} {missing_g:>7} {missing_t:>7} {orphans:>6}")

def matrix_check(report_only=True):
    coll = db.coll()
    print("=" * 92)
    print("DB CHECK - RECONCILIATION MATRIX")
    print("=" * 92)
    print(f"{'':<3}{'GAME':<28} {'IDX':>6} {'G_DRV':>6} {'T':>6} "
          f"{'SRC':>5} {'MISS_G':>7} {'MISS_T':>7} {'ORPH':>6}")
    print("-" * 92)

    total_indexed = total_on_g = total_on_t = total_src_gone = 0
    total_missing_g = total_missing_t = total_orphans = 0
    problems = []

    indexed_names = set()
    for doc in coll.find({}, {"filename": 1, "game": 1}):
        indexed_names.add((doc["game"], doc["filename"]))

    for game_folder in sorted(config.CARD_DATABASE.iterdir(), key=lambda p: p.name.lower()):
        if not game_folder.is_dir():
            continue
        game = game_folder.name
        drive_folder = config.G_DRIVE / game
        upload_folder = config.CARD_UPLOAD / game

        docs = list(coll.find({"game": game}))
        indexed = len(docs)
        on_g = on_t = src_gone = missing_g = missing_t = 0
        g_names = {f.name for f in drive_folder.iterdir()} if drive_folder.is_dir() else set()
        t_names = {f.name for f in game_folder.iterdir() if f.is_file()}
        u_names = {f.name for f in upload_folder.iterdir()} if upload_folder.is_dir() else set()

        for doc in docs:
            fn = doc["filename"]
            if fn in g_names:
                on_g += 1
            else:
                missing_g += 1
                problems.append(f"MISSING G_DRIVE: {game} / {fn}")
            if fn in t_names:
                on_t += 1
            else:
                missing_t += 1
                problems.append(f"MISSING T: {game} / {fn}")
            if fn not in u_names:
                src_gone += 1

        orphans = 0
        for fn in g_names | t_names:
            if (game, fn) not in indexed_names:
                orphans += 1
                problems.append(f"ORPHAN: {game} / {fn}")

        print(_matrix_row(game, indexed, on_g, on_t, src_gone, missing_g, missing_t, orphans))
        total_indexed += indexed; total_on_g += on_g; total_on_t += on_t
        total_src_gone += src_gone; total_missing_g += missing_g
        total_missing_t += missing_t; total_orphans += orphans

    print("-" * 92)
    print(_matrix_row("TOTAL", total_indexed, total_on_g, total_on_t,
                      total_src_gone, total_missing_g, total_missing_t, total_orphans))
    print("=" * 92)

    if problems:
        print(f"\n{len(problems)} problem(s) found:")
        for p in problems[:50]:
            print(f"  {p}")
        if len(problems) > 50:
            print(f"  ... and {len(problems) - 50} more")
    else:
        print("\nAll clear - no problems found.")

    if problems and not report_only:
        fix(problems)
    return problems

def fix(problems):
    print("\n" + "=" * 92)
    print("FIX MODE - re-copy missing files from wherever they exist")
    print("=" * 92)
    coll = db.coll()
    fixed = failed = 0
    for p in problems:
        if not p.startswith("MISSING"):
            continue
        _, game, fn = p.split(" / ")
        doc = coll.find_one({"game": game, "filename": fn})
        if not doc:
            continue
        candidates = [
            config.CARD_UPLOAD / game / fn,
            config.CARD_DATABASE / game / fn,
        ]
        src = next((c for c in candidates if c.exists()), None)
        if not src:
            failed += 1
            print(f"  CANNOT FIX (no copy found): {game} / {fn}")
            continue
        dest = config.G_DRIVE / game / fn
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dest))
            fixed += 1
            print(f"  FIXED: {game} / {fn}")
        except Exception as e:
            failed += 1
            print(f"  FAILED: {game} / {fn}: {e}")
    print(f"\nFixed: {fixed}   Failed: {failed}")

def main():
    db.init_db()
    matrix_check(report_only=False)
    db.close()

if __name__ == "__main__":
    main()
