from flask import Flask, render_template
import pandas as pd
import re
from pathlib import Path


app = Flask(__name__)
DATA_FILE = Path(__file__).resolve().parent / "digital_payment_data.xlsx"

def clean_col(c):
    c = str(c).strip().lower()
    c = re.sub(r"\([^)]*\)", "", c)
    c = re.sub(r"[^a-z0-9]+", "_", c)
    return re.sub(r"_+", "_", c).strip("_")

def prepare_columns(df):
    seen, names = {}, []
    for c in df.columns:
        n = clean_col(c)
        seen[n] = seen.get(n, 0) + 1
        names.append(n if seen[n] == 1 else f"{n}_{seen[n]-1}")
    df.columns = names
    return df

def find_col(df, *terms):
    for c in df.columns:
        if all(t in c for t in terms):
            return c
    return None

def clean_text(v):
    return "" if pd.isna(v) else re.sub(r"\s+", " ", str(v).strip())

def single_counts(df, col):
    if not col: return {}
    s = df[col].fillna("").map(clean_text)
    return {str(k): int(v) for k, v in s.value_counts().items() if str(k)}

def multi_counts(df, col):
    if not col: return {}
    out = {}
    for value in df[col].fillna(""):
        for item in str(value).split(","):
            item = clean_text(item)
            if item:
                out[item] = out.get(item, 0) + 1
    return dict(sorted(out.items(), key=lambda x: x[1], reverse=True))

def safety_vs_knowledge_pairs(df, safety_col, knowledge_col):
    """One {x, y} pair per respondent: their safety rating (x) vs their
    fraud-knowledge rating (y). Rows missing either value are skipped."""
    if not safety_col or not knowledge_col:
        return []
    pairs = []
    for _, row in df[[safety_col, knowledge_col]].dropna().iterrows():
        try:
            x = float(row[safety_col])
            y = float(row[knowledge_col])
        except (TypeError, ValueError):
            continue
        pairs.append({"x": x, "y": y})
    return pairs

def collapse_to_others(counts, known_labels):
    """Merge any category not in known_labels into a single 'Others' bucket."""
    known = {k.strip().lower() for k in known_labels}
    out, others = {}, 0
    for label, count in counts.items():
        if label.strip().lower() in known:
            out[label] = out.get(label, 0) + count
        else:
            others += count
    if others:
        out["Others"] = out.get("Others", 0) + others
    return dict(sorted(out.items(), key=lambda x: x[1], reverse=True))

def make_data(df):
    cols = {
        "age_group": find_col(df, "age_group"),
        "gender": find_col(df, "gender"),
        "study_year": find_col(df, "year_of_study"),
        "payment_apps": find_col(df, "which_digital_payment_applications"),
        "payment_frequency": find_col(df, "how_frequently_do_you_use_digital_payment"),
        "payment_purpose": find_col(df, "following_purposes_do_you_primarily_use_digital_payments"),
        "amount": find_col(df, "what_is_the_average_amount"),
        "small": find_col(df, "do_you_prefer_using_digital_payments_over_cash"),
        "otp": find_col(df, "do_you_know_what_an_otp"),
        "shared": find_col(df, "have_you_ever_shared_your_otp"),
        "security": find_col(df, "before_entering_your_payment_details"),
        "fraud": find_col(df, "have_you_personally_experienced_or_been_targeted"),
        "unique": find_col(df, "use_different_unique_passwords"),
        "response": find_col(df, "if_you_were_to_fall_victim"),
        "concerns": find_col(df, "biggest_concern"),
    }
    safety_col = find_col(df, "scale_of_1_to_5")
    knowledge_col = find_col(df, "rate_your_own_overall_knowledge")
    rating_cols = [c for c in (safety_col, knowledge_col) if c]
    study_counts = single_counts(df, cols["study_year"])

    for key in list(study_counts.keys()):
        if key.lower() in ["phd", "working", "undergraduate","job"]:
            study_counts["Others"] = study_counts.get("Others", 0) + study_counts[key]
            del study_counts[key]

    purpose_counts = collapse_to_others(multi_counts(df, cols["payment_purpose"]), [
        "Online or offline shopping",
        "Food delivery",
        "Recharge",
        "Sending money to friends or family",
        "OTT subscriptions",
        "Paying college/tuition fees",
    ])

    return {
        "age_group": single_counts(df, cols["age_group"]),
        "gender": single_counts(df, cols["gender"]),
        "study_year": study_counts,
        "payment_frequency": single_counts(df, cols["payment_frequency"]),
        "avg_transaction_amount": single_counts(df, cols["amount"]),
        "prefer_digital_small": single_counts(df, cols["small"]),
        "otp_2fa_awareness": single_counts(df, cols["otp"]),
        "shared_otp_pin": single_counts(df, cols["shared"]),
        "security_check": single_counts(df, cols["security"]),
        "unique_pin_password": single_counts(df, cols["unique"]),
        "fraud_experience": single_counts(df, cols["fraud"]),
        "fraud_response_knowledge": single_counts(df, cols["response"]),
        "safety_rating": single_counts(df, rating_cols[0] if rating_cols else None),
        "fraud_knowledge": single_counts(df, rating_cols[1] if len(rating_cols) > 1 else None),
        "payment_apps": multi_counts(df, cols["payment_apps"]),
        "payment_purpose": purpose_counts,
        "payment_concerns": multi_counts(df, cols["concerns"]),
        "safety_vs_knowledge": safety_vs_knowledge_pairs(df, safety_col, knowledge_col),
    }

def pct(d, key, total):
    return round(d.get(key, 0) / total * 100) if total else 0

@app.route("/")
def dashboard():
    df = prepare_columns(pd.read_excel(DATA_FILE)).drop_duplicates()
    data = make_data(df)
    n = len(df)

    metrics = {
        "n": n,
        "prefer_small_pct": pct(data["prefer_digital_small"], "Yes", sum(data["prefer_digital_small"].values())),
        "security_always_pct": pct(data["security_check"], "Always", sum(data["security_check"].values())),
        "never_shared_pct": pct(data["shared_otp_pin"], "Never", sum(data["shared_otp_pin"].values())),
        "fraud_pct": pct(data["fraud_experience"], "Yes", sum(data["fraud_experience"].values())),
    }

    top_app = next(iter(data["payment_apps"]), "-")
    daily = data["payment_frequency"].get("Daily", 0) + data["payment_frequency"].get("Multiple times a day", 0)

    summaries = {
        "who": f"A demographic snapshot of the students who participated in the digital payment survey.",
        "habits": f"Insights into students’ payment frequency, transaction values, preferences, app usage, and the purposes for which they use digital payments.",
        "security": f"Examining students’ awareness of OTP/2FA, secure payment practices, and password safety.",
        "fraud": f"Examining students’ exposure to digital payment fraud, their awareness of what to do after a scam, and their biggest concerns about payment security.",
    }

    return render_template("index.html", data=data, metrics=metrics, summaries=summaries, n=n,
                           source_file=DATA_FILE.name)

if __name__ == "__main__":
    app.run(debug=True)