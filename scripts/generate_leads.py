"""Generate the fictional AIDO leads dataset: data/leads.csv.

    python scripts/generate_leads.py            # writes data/leads.csv
    python scripts/generate_leads.py --check    # exits 1 if data/leads.csv differs from a fresh run

Every business, name and number here is invented. The script uses a fixed seed,
so the same run always writes the same file (docs/02-architecture.md,
decisions). Stages are computed with app/stage.py, never typed in.
Do not edit data/leads.csv by hand: change this script and rerun it (CONTRIBUTING.md).
"""
from __future__ import annotations

import argparse
import csv
import io
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.stage import DOMAIN_IDS, score_business  # noqa: E402

# random.gauss, lognormvariate and choices can change between Python versions; .python-version and CI pin
# 3.12, and tests/test_leads_dataset.py fails if the output ever changes, so a bump is noticed.
SEED = 20261108
ROWS = 300
FIRST_DAY = date(2025, 11, 1)
LAST_DAY = date(2026, 10, 31)
OUT = ROOT / "data" / "leads.csv"

COLUMNS = [
    "business_name", "industry", "employees", "lead_date", "total_score", "stage",
    *[f"{d}_avg" for d in DOMAIN_IDS], *[f"{d}_stage" for d in DOMAIN_IDS],
    "pains", "pipeline_status", "deal_value", "fictional",
]

INDUSTRIES = ["קמעונאות", "מסעדנות", "בנייה ושיפוצים", "הובלה ולוגיסטיקה", "קליניקות ובריאות", "משרד עורכי דין",
              "משרד רואי חשבון", "ייצור ותעשייה קלה", "סוכנות ביטוח", "נדל\"ן", "חינוך והדרכה", "שיווק ופרסום"]

# Name parts are generic words combined at random, so no name points at a real business. Words that are
# also well-known company names (for example a large insurer) are left out on purpose.
NAME_FIRST = ["אופק", "גבעה", "נחל", "תמר", "ארז", "שקד", "רימון", "צפון", "דרום", "מעיין", "צאלון", "ברוש",
              "חצב", "כרמל", "יובל", "נוף", "סלע", "גפן", "דקל", "ערבה", "שחר", "אורן", "לוטם", "זית"]
NAME_KIND = {
    "קמעונאות": ["חנויות", "מרכולים", "בוטיק"], "מסעדנות": ["מטבח", "ביסטרו", "קייטרינג"],
    "בנייה ושיפוצים": ["בנייה", "שיפוצים", "קבלנות"], "הובלה ולוגיסטיקה": ["הובלות", "שילוח", "לוגיסטיקה"],
    "קליניקות ובריאות": ["קליניקה", "מרפאה", "בריאות"], "משרד עורכי דין": ["משפטים", "עו\"ד", "ייעוץ משפטי"],
    "משרד רואי חשבון": ["ראיית חשבון", "חשבונאות", "הנהלת חשבונות"], "ייצור ותעשייה קלה": ["תעשיות", "מפעלים", "ייצור"],
    "סוכנות ביטוח": ["ביטוח", "סוכנות", "פיננסים"], "נדל\"ן": ["נכסים", "נדל\"ן", "יזמות"],
    "חינוך והדרכה": ["הדרכה", "מכללה", "סדנאות"], "שיווק ופרסום": ["מדיה", "פרסום", "סטודיו"],
}
NAME_SUFFIX = ["", "", "", " בע\"מ"]

PAINS = {
    "strategy": ["אין יעדים כתובים", "כל שבוע עדיפות אחרת", "אין תוכנית עבודה שנתית"],
    "management": ["הבעלים עונה לכל טלפון", "החלטות נתקעות אצל המנכ\"ל", "אין ישיבות בקרה קבועות"],
    "systems": ["מלאי וניהול באקסל", "כל מחלקה עם מערכת משלה", "ידע נשאר בראש של עובד אחד"],
    "people": ["תחלופת עובדים גבוהה", "עובדים לא יודעים למי לפנות", "אין מסלול צמיחה לעובדים"],
    "finance": ["תזרים מזומנים לוחץ", "לא יודעים מה הרווחיות לפי מוצר", "תקציב לא מוגדר למחלקות"],
}

# Not yet diagnosed -> early statuses; diagnosed -> later ones.
EARLY = (["new", "contacted", "meeting"], [5, 4, 3])
LATE = (["contacted", "diagnosed", "proposal", "won", "lost"], [1, 4, 4, 3, 2])


def _answers(rng: random.Random, level: float) -> dict:
    """Four answers per domain around a business-wide level (1-3), with one domain often weaker."""
    weak = rng.choice(DOMAIN_IDS)
    out = {}
    for d in DOMAIN_IDS:
        center = level - (0.6 if d == weak else 0.0) + rng.uniform(-0.4, 0.4)
        out[d] = [min(3, max(1, round(center + rng.uniform(-0.7, 0.7)))) for _ in range(4)]
    return out


def generate(seed: int = SEED, rows: int = ROWS) -> list[dict]:
    rng = random.Random(seed)
    used: set[str] = set()
    span = (LAST_DAY - FIRST_DAY).days
    out = []
    while len(out) < rows:
        industry = rng.choice(INDUSTRIES)
        base = f"{rng.choice(NAME_FIRST)} {rng.choice(NAME_KIND[industry])}"
        if base in used:
            continue
        used.add(base)
        name = base + rng.choice(NAME_SUFFIX)
        employees = int(min(400, max(3, rng.lognormvariate(3.0, 0.9))))
        lead_date = FIRST_DAY + timedelta(days=rng.randint(0, span))
        diagnosed = rng.random() < 0.8
        row = {c: "" for c in COLUMNS}
        row.update(business_name=name, industry=industry, employees=employees, lead_date=lead_date.isoformat(),
                   fictional="true")
        if diagnosed:
            # Bigger businesses tend to be further along, as in the deck's examples.
            level = min(3.0, max(1.0, rng.gauss(1.85 + min(employees, 200) / 250, 0.45)))
            result = score_business(_answers(rng, level))
            row.update(total_score=result["total"], stage=result["stage"])
            for d in result["domains"]:
                row[f"{d['id']}_avg"] = f"{d['average']:.1f}"
                row[f"{d['id']}_stage"] = d["stage"]
            weakest = sorted(result["domains"], key=lambda d: d["average"])[:2]
            pains = [rng.choice(PAINS[d["id"]]) for d in weakest]
            statuses, weights = LATE
        else:
            pains = [rng.choice(PAINS[rng.choice(DOMAIN_IDS)])]
            statuses, weights = EARLY
        row["pains"] = "; ".join(dict.fromkeys(pains))
        row["pipeline_status"] = rng.choices(statuses, weights)[0]
        if diagnosed or rng.random() < 0.6:
            value = rng.uniform(6000, 18000) * (1 + min(employees, 150) / 50)
            row["deal_value"] = int(round(value / 500) * 500)
        out.append(row)
    out.sort(key=lambda r: (r["lead_date"], r["business_name"]))
    return out


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if data/leads.csv is not what this script writes")
    args = ap.parse_args()
    text = to_csv(generate())
    if args.check:
        same = OUT.exists() and OUT.read_bytes() == text.encode("utf-8")
        print("data/leads.csv is up to date" if same else "data/leads.csv differs from the generator output")
        return 0 if same else 1
    OUT.write_bytes(text.encode("utf-8"))
    print(f"wrote {OUT.relative_to(ROOT)}: {text.count(chr(10)) - 1} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
