"""
Download public-domain cookbooks from Project Gutenberg as plain text.
Run once to populate the books/ directory.
"""
import requests
import time
from pathlib import Path
from tqdm import tqdm

BOOKS_DIR = Path("books")
BOOKS_DIR.mkdir(exist_ok=True)

# (gutenberg_id, short_name, approx_year)
COOKBOOKS = [
    (65061, "boston_cooking_school",     1896),  # Fannie Farmer — Boston Cooking-School Cook Book
    (13923, "white_house_cook_book",     1887),  # Gillette & Ziemann — The White House Cookbook
    (10136, "mrs_beetons_household",     1861),  # Isabella Beeton — Book of Household Management
    (12327, "the_jewish_manual",         1846),  # Lady Montefiore — The Jewish Manual
    (9624,  "directions_for_cookery",    1837),  # Eliza Leslie — Directions for Cookery
    (6745,  "miss_parloas_new_cook_book",1880),  # Maria Parloa — Miss Parloa's New Cook Book
    (22114, "plain_cookery_working",     1852),  # Francatelli — Plain Cookery for the Working Classes
    (28419, "twenty_five_cent_dinners",  1878),  # Juliet Corson — Twenty-Five Cent Dinners
    (28681, "the_cooks_oracle",          1817),  # William Kitchiner — The Cook's Oracle
    (46254, "mrs_hale_receipts",         1857),  # Sarah Josepha Hale — Mrs. Hale's Receipts
    (64459, "marion_harland_complete",   1903),  # Marion Harland — Complete Cook Book
    (29728, "cookery_imperial_rome",     1936),  # Apicius/Vehling — Cookery and Dining in Imperial Rome
    (10520, "compleat_cook",             1658),  # W. M. — The Compleat Cook
    (42450, "housekeeping_old_virginia", 1879),  # Marion Cabell Tyree — Housekeeping in Old Virginia
    (12519, "virginia_housewife",        1824),  # Mary Randolph — The Virginia Housewife
]

GUTENBERG_URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
HEADERS = {"User-Agent": "CookbookOracle/0.1 (educational, local use)"}


def download(book_id: int, name: str) -> bool:
    dest = BOOKS_DIR / f"{name}.txt"
    if dest.exists():
        print(f"  skip  {dest.name} (already downloaded)")
        return True

    url = GUTENBERG_URL.format(id=book_id)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        print(f"  ok    {dest.name} ({len(r.content)//1024} KB)")
        return True
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        return False


if __name__ == "__main__":
    print(f"Downloading {len(COOKBOOKS)} cookbooks to {BOOKS_DIR.resolve()}\n")
    ok = 0
    for book_id, name, year in tqdm(COOKBOOKS, desc="Books"):
        if download(book_id, name):
            ok += 1
        time.sleep(1)  # be polite to Gutenberg

    print(f"\nDone: {ok}/{len(COOKBOOKS)} downloaded.")
