"""
One-shot fix: fetch years for IA books that have year=0 in substitutions.jsonl,
then patch the jsonl in-place.

Also writes data/book_meta.json so future runs don't need to re-fetch.
"""
import json
import time
from pathlib import Path

import requests

DATA_DIR   = Path("data")
BOOKS_DIR  = Path("books")
SUB_PATH   = DATA_DIR / "substitutions.jsonl"
META_PATH  = DATA_DIR / "book_meta.json"

HEADERS    = {"User-Agent": "CookbookOracle/0.1 (educational, local use)"}
IA_SEARCH  = "https://archive.org/advancedsearch.php"

# Known years from the IA download output we saw earlier
KNOWN_IA_YEARS = {
    "five_roses_cook_book_being_a_manual_of_good_recipe":    1915,
    "watkins_cook_book":                                      1925,
    "the_modern_cook_1846_1462_recipes_by_queen_victori":    1877,
    "cake_secrets":                                           1924,
    "the_jubilee_recipe_book_a_collection_of_practical_":    1927,
    "the_family_herald_cook_book":                            1924,
    "mrs_ab_marshalls_cookery_book_with_seventy_illustr":     1894,
    "the_household_cyclopedia_of_general_information":        1881,
    "ogilvies_book_for_a_cook_a_selection_of_recipes_an":     1914,
    "the_secrets_of_good_cooking":                            1928,
    "modern_cookery_for_private_families":                    1887,
    "one_thousand_valuable_secrets_in_the_elegant_and_u":     1795,
    "good_things_to_eat_as_suggested_by_rufus":               1911,
    "the_complete_english_cook_or_prudent_housewife_bei":     1772,
    "a_textbook_of_cooking":                                  1915,
    "the_girl_at_catellis":                                   1900,
    "the_skilful_housewifes_guide_a_book_of_domestic_co":     1848,
    "the_sure_to_rise_cookery_book_third_edition":            1914,
    "colettes_best_recipes_a_book_of_french_cookery":         1925,
    "consult_me_to_know_how_to_cook_on_household_manage":     1868,
    "the_home_cook_book":                                     1887,
    "salad_secrets":                                          1928,
    "400_sweet_dishes_suitable_for_confectioners_cooks_": 1895,
    "a_thousand_and_one_receipts_useful_to_families":         1883,
    "commonsense_cookery_for_english_households_with_tw":     1913,
    "the_fine_art_of_carving":                                1922,
    "modern_domestic_cookery_and_useful_receipt_book_ad":     1845,
    "good_things_to_eat_made_with_cow_brand_bicarbonate":     1924,
    "gem_chopper_cook_book_valuable_recipes_for_substan":     1902,
    "recipe_book":                                            1785,
    "the_common_sense_recipe_book_containing_all_the_la":     1895,
    "some_valuable_recipes_for_canning_fruits_and_veget":     1920,
    "manual_of_military_cooking_and_dietary_mobilizatio":     1915,
    "lowneys_cook_book_illustrated_in_colors_a_new_guid":     1908,
}


def load_meta() -> dict:
    if META_PATH.exists():
        return json.loads(META_PATH.read_text())
    return {}


def save_meta(meta: dict):
    META_PATH.write_text(json.dumps(meta, indent=2))


def patch_jsonl(year_map: dict):
    """Patch year=0 records in substitutions.jsonl using year_map."""
    lines = SUB_PATH.read_text(encoding="utf-8").splitlines()
    patched = 0
    out = []
    for line in lines:
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("year", 0) == 0:
            sf = r.get("source_file", "")
            if sf in year_map:
                r["year"] = year_map[sf]
                patched += 1
        out.append(json.dumps(r, ensure_ascii=False))

    SUB_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    return patched


def main():
    meta = load_meta()
    meta.update(KNOWN_IA_YEARS)

    # Patch all jsonl files in data/
    total_patched = 0
    for jsonl_file in DATA_DIR.glob("*.jsonl"):
        lines = jsonl_file.read_text(encoding="utf-8").splitlines()
        out = []
        patched = 0
        for line in lines:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("year", 0) == 0:
                sf = r.get("source_file", "")
                if sf in meta:
                    r["year"] = meta[sf]
                    patched += 1
            out.append(json.dumps(r, ensure_ascii=False))
        if patched:
            jsonl_file.write_text("\n".join(out) + "\n", encoding="utf-8")
            print(f"  {jsonl_file.name}: patched {patched} records")
            total_patched += patched

    save_meta(meta)
    print(f"\nTotal patched: {total_patched} records")
    print(f"Meta saved → {META_PATH} ({len(meta)} books)")
    print("\nRun crossref.py and build_index.py to rebuild with correct years.")


if __name__ == "__main__":
    main()
