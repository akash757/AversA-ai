import json
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from day_one import parse_templates_file, process_brief


def main():
    templates_path = BASE_DIR / "samples" / "templates.txt"
    templates = parse_templates_file(templates_path)
    print(f"Loaded {len(templates)} template questions from {templates_path.name}\n")

    sample_files = [
        ("Health App (CGM & Meal Tracker)", BASE_DIR / "samples" / "brief_health_app.txt"),
        ("E-Commerce Storefront (Artisan Tableware)", BASE_DIR / "samples" / "brief_ecommerce.txt"),
        ("Vague One-Liner ('App for our business')", BASE_DIR / "samples" / "brief_vague.txt"),
    ]

    for title, filepath in sample_files:
        print("=" * 70)
        print(f"TESTING: {title}")
        print("=" * 70)
        brief_text = filepath.read_text(encoding="utf-8").strip()
        print(f"Brief text:\n\"{brief_text}\"\n")

        print("Calling Day 1 Discovery Agent...")
        try:
            response = process_brief(
                brief=brief_text, templates=templates, project_id=f"test_{filepath.stem}"
            )
            print("\nAGENT OUTPUT:")
            print(json.dumps(response.model_dump(), indent=2))
        except Exception as exc:
            print(f"\nAGENT ERROR: {type(exc).__name__}: {exc}")

        print("\n" + "-" * 70 + "\n")


if __name__ == "__main__":
    main()

