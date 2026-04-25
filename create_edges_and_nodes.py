import os
import pandas as pd
import time
import csv
import re
import requests
import pyalex
pyalex.config.email = #INSERT YOUR OPENALEX ACCOUNT EMAIL HERE
from pyalex import Works
from requests.exceptions import RequestException

def normalize_id(val):
    """Normalize identifiers: lowercase, trim, strip DOI/URL prefixes, clean artifacts."""
    if pd.isna(val):
        return ""
    return (
        str(val)
        .strip()
        .lower()
        .replace("\ufeff", "")
        .rstrip("/")
        .replace("https://doi.org/", "")
        .replace("http://doi.org/", "")
        .strip()
    )

def rename_source_type_column(file_path):
    """Rename 'source_type' column to 'document_type' in a CSV file (in-place)."""
    if os.path.exists(file_path):
        df = pd.read_csv(file_path)
        if "source_type" in df.columns:
            df = df.rename(columns={"source_type": "document_type"})
            df.to_csv(file_path, index=False, encoding="utf-8-sig")

def update_type_map(filepath, id_col, type_col):
    """Update global id_to_type mapping from CSV columns [id_col, type_col]."""
    if os.path.exists(filepath):
        df = pd.read_csv(filepath, usecols=[id_col, type_col])
        df = df.dropna(subset=[id_col, type_col])
        df[id_col] = df[id_col].apply(normalize_id)
        df[type_col] = df[type_col].astype(str).str.strip().str.lower()
        id_to_type.update(df.set_index(id_col)[type_col].to_dict())


def trim(df):
    """Return DataFrame with only standard columns if they exist."""
    return df[[c for c in ['id', 'title', 'publication_date', 'infohazard_concepts', 'score'] if c in df.columns]]

def normalize_pub_date(val):
    """Normalize publication date into YYYY-MM-DD or NA if invalid/unusable."""
    try:
        val = str(val).strip()
        if not val or val.lower() in {"false", "nan", "none"}:
            return pd.NA
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            return val
        parsed = pd.to_datetime(val, dayfirst=True, errors="coerce")
        if pd.isna(parsed):
            return pd.NA
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        return pd.NA

print("CWD:", os.getcwd())
id_to_type = {}
base_dir = os.path.dirname(os.path.abspath(__file__))


#----------------------------------------------------------------------------------------------------------
# Edge file creation
#----------------------------------------------------------------------------------------------------------


def create_edges(output_directory = os.path.join(base_dir, "processed_data")):
    """Run edges creation."""

    # --- File paths ---
    compiled_overton_second_order_path = os.path.join(output_directory, "compiled_overton_second_order.csv")
    compiled_overton_first_order_path = os.path.join(output_directory, "compiled_overton_first_order.csv")
    compiled_altmetric_overton_second_order_path = os.path.join(output_directory, "compiled_altmetric_overton_second_order.csv")
    compiled_altmetric_first_order_path = os.path.join(output_directory, "compiled_altmetric_first_order.csv")
    compiled_altmetric_second_order_path = os.path.join(output_directory, "compiled_altmetric_second_order.csv")
    compiled_openalex_first_order_path = os.path.join(output_directory, "compiled_openalex_first_order.csv")
    compiled_openalex_second_order_path = os.path.join(output_directory, "compiled_openalex_second_order.csv")
    compiled_openalex_overton_second_order_path = os.path.join(output_directory, "compiled_openalex_overton_second_order.csv")
    edges_path = os.path.join(output_directory, "edges.csv")

    rename_source_type_column(compiled_altmetric_second_order_path)
    rename_source_type_column(compiled_altmetric_first_order_path)

    update_type_map(compiled_openalex_first_order_path, "first_order_doi", "type")
    update_type_map(compiled_openalex_second_order_path, "second_order_id", "type")
    update_type_map(compiled_altmetric_first_order_path, "unique_identifier", "document_type")
    update_type_map(compiled_altmetric_second_order_path, "unique_identifier", "document_type")
    update_type_map(compiled_overton_first_order_path, "unique_identifier", "document_type")
    update_type_map(compiled_overton_second_order_path, "unique_identifier", "document_type")
    update_type_map(compiled_altmetric_overton_second_order_path, "unique_identifier", "document_type")
    update_type_map(compiled_openalex_overton_second_order_path, "unique_identifier", "document_type")

    #Build ID-to-type map

    openalex_ids = ["W2158112812", "W2112170460", "W2782702360", "W2043170430", "W2155996896"]

    # Output CSV setup
    header = ["id", "doi", "title", "publication_date"]
    output_path = os.path.join(output_directory, "core_papers.csv")

    rows = []

    for oa_id in openalex_ids:
        url = f"https://api.openalex.org/works/https://openalex.org/{oa_id}"
        print(f"Fetching: {url}")
        for attempt in range(1, 4):   
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                rows.append([
                    normalize_id(data.get("id", "")),
                    normalize_id(data.get("doi", "")),
                    data.get("title", "").strip(),
                    data.get("publication_date", "")
                ])
                break    
            except RequestException as e:
                print(f" Attempt {attempt} for {oa_id} failed: {e}")
                if attempt < 5:
                    time.sleep(3)    
                else:
                    print(f"Skipping {oa_id} after 4 failed attempts.")
        time.sleep(1)     

    # Save to CSV
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    print(f"\nSaved core paper metadata to: {output_path}")


    core_papers_path = os.path.join(output_directory, "core_papers.csv")
    if os.path.exists(core_papers_path):
        core_df = pd.read_csv(core_papers_path, dtype=str)
        for doi in core_df.get("doi", pd.Series(dtype=str)).dropna().unique():
            norm_doi = normalize_id(doi)
            id_to_type[norm_doi] = "core_paper"
        print(f"[INFO] Added {len(core_df)} core DOIs to id_to_type map")
    else:
        print("[WARN] core_papers.csv not found — no core DOIs added")

    # Collect all edges
    all_edges = []

    # Altmetric first-order → core DOI
    if os.path.exists(compiled_altmetric_first_order_path):
        alt_first_df = pd.read_csv(compiled_altmetric_first_order_path, dtype=str)
        df = alt_first_df[["unique_identifier", "core_doi"]].dropna(subset=["core_doi"])
        df["source_id"] = df["unique_identifier"].apply(normalize_id)
        df["target_id"] = df["core_doi"].apply(normalize_id)
        df["source_type"] = df["source_id"].map(id_to_type)
        df["target_type"] = "core_paper"
        all_edges.append(df[["source_id", "target_id", "source_type", "target_type"]])
        print(f"[INFO] Added {len(df)} Altmetric first-order → core DOI edges")

    # Overton first-order → core DOI
    if os.path.exists(compiled_overton_first_order_path):
        first_order_df = pd.read_csv(compiled_overton_first_order_path)
        df = first_order_df[["unique_identifier", "core_doi", "document_type"]].dropna(subset=["core_doi"])
        df["source_id"] = df["unique_identifier"].apply(normalize_id)
        df["target_id"] = df["core_doi"].apply(normalize_id)
        df["source_type"] = df["source_id"].map(id_to_type)
        df["target_type"] = "core_paper"
        all_edges.append(df[["source_id", "target_id", "source_type", "target_type"]])
        print(f"[INFO] Added {len(df)} Overton first-order → core DOI edges")

    # OpenAlex first-order → core DOI
    if os.path.exists(compiled_openalex_first_order_path):
        openalex_first_df = pd.read_csv(compiled_openalex_first_order_path)
        if all(col in openalex_first_df.columns for col in ["first_order_doi", "core_doi", "type"]):
            df = openalex_first_df[["first_order_doi", "core_doi"]].dropna()
            df["source_id"] = df["first_order_doi"].apply(normalize_id)
            df["target_id"] = df["core_doi"].apply(normalize_id)
            df["source_type"] = df["source_id"].map(id_to_type)
            df["target_type"] = "core_paper"
            all_edges.append(df[["source_id", "target_id", "source_type", "target_type"]])
            print(f"[INFO] Added {len(df)} OpenAlex first-order → core DOI edges")

    # Overton second-order → first-order
    if os.path.exists(compiled_overton_second_order_path) and os.path.exists(compiled_overton_first_order_path):
        second_df = pd.read_csv(compiled_overton_second_order_path)
        first_df = pd.read_csv(compiled_overton_first_order_path)
        if "policy_document_dois" in second_df.columns:
            second_df["source_id"] = second_df["unique_identifier"].apply(normalize_id)
            second_df["target_id"] = second_df["policy_document_dois"].apply(normalize_id)
            valid_dois = set(first_df["unique_identifier"].dropna().map(normalize_id))
            second_df = second_df[second_df["target_id"].isin(valid_dois)]
            second_df["source_type"] = second_df["source_id"].map(id_to_type)
            second_df["target_type"] = second_df["target_id"].map(id_to_type)
            second_df = second_df.dropna(subset=["target_type"])
            all_edges.append(second_df[["source_id", "target_id", "source_type", "target_type"]])
            print(f"[INFO] Added {len(second_df)} Overton second-order → first-order edges")

    # OpenAlex second-order → first-order
        df = pd.read_csv(compiled_openalex_second_order_path, dtype=str)
        if all(col in df.columns for col in ["second_order_id", "first_order_id", "type"]):
            df = df[["second_order_id", "first_order_id"]].dropna()
            df["source_id"] = df["second_order_id"].apply(normalize_id)
            df["target_id"] = df["first_order_id"].apply(normalize_id)
            df["source_type"] = df["source_id"].map(id_to_type)
            df["target_type"] = df["target_id"].map(id_to_type)
            df = df.dropna(subset=["target_type"])
            all_edges.append(df[["source_id", "target_id", "source_type", "target_type"]])
            print(f"[INFO] Added {len(df)} OpenAlex second-order → first-order edges")

    # Altmetric second-order → first-order
    if os.path.exists(compiled_altmetric_second_order_path):
        df = pd.read_csv(compiled_altmetric_second_order_path)
        df["source_id"] = df["unique_identifier"].apply(normalize_id)
        df["target_id"] = df["first_order_doi"].apply(normalize_id)
        df["source_type"] = df["source_id"].map(id_to_type)
        df["target_type"] = df["target_id"].map(id_to_type)
        df = df.dropna(subset=["target_type"])
        all_edges.append(df[["source_id", "target_id", "source_type", "target_type"]])
        print(f"[INFO] Added {len(df)} Altmetric second-order → first-order edges")

    # Overton second-order → Altmetric first-order
    if os.path.exists(compiled_altmetric_overton_second_order_path) and os.path.exists(compiled_altmetric_first_order_path):
        alt_df = pd.read_csv(compiled_altmetric_overton_second_order_path)
        alt_df["source_id"] = alt_df["unique_identifier"].apply(normalize_id)
        alt_df["target_id"] = alt_df["first_order_doi"].apply(normalize_id)
        alt_df["source_type"] = alt_df["source_id"].map(id_to_type)
        alt_df["target_type"] = alt_df["target_id"].map(id_to_type)
        alt_df = alt_df.dropna(subset=["target_type"])
        all_edges.append(alt_df[["source_id", "target_id", "source_type", "target_type"]])
        print(f"[INFO] Added {len(alt_df)}  Overton second-order → Altmetric first-order edges")

    # Overton second-order → OpenAlex first-order
    if os.path.exists(compiled_openalex_overton_second_order_path) and os.path.exists(compiled_openalex_first_order_path):
        overton_df = pd.read_csv(compiled_openalex_overton_second_order_path, dtype=str)
        openalex_df = pd.read_csv(compiled_openalex_first_order_path, dtype=str)

        if "first_order_doi" in overton_df.columns and "first_order_doi" in openalex_df.columns:
            openalex_dois = set(openalex_df["first_order_doi"].dropna().map(normalize_id))

            overton_df["source_id"] = overton_df["unique_identifier"].map(normalize_id)
            overton_df["target_id"] = overton_df["first_order_doi"].map(normalize_id)
            overton_df = overton_df[overton_df["target_id"].isin(openalex_dois)]

            overton_df["source_type"] = overton_df["source_id"].map(id_to_type)
            overton_df["target_type"] = overton_df["target_id"].map(id_to_type)
            overton_df = overton_df.dropna(subset=["target_type"])

            all_edges.append(overton_df[["source_id", "target_id", "source_type", "target_type"]])
            print(f"[INFO] Added {len(overton_df)} Overton second-order → OpenAlex first-order edges")

    # Altmetric second-order → OpenAlex first-order
    if os.path.exists(compiled_altmetric_second_order_path) and os.path.exists(compiled_openalex_first_order_path):
        alt_df = pd.read_csv(compiled_altmetric_second_order_path, dtype=str)
        openalex_df = pd.read_csv(compiled_openalex_first_order_path, dtype=str)
        openalex_dois = set(openalex_df["first_order_doi"].dropna().map(normalize_id))
        if "first_order_doi" in alt_df.columns:
            alt_df["source_id"] = alt_df["unique_identifier"].apply(normalize_id)
            alt_df["target_id"] = alt_df["first_order_doi"].apply(normalize_id)
            alt_df = alt_df[alt_df["target_id"].isin(openalex_dois)]
            alt_df["source_type"] = alt_df["source_id"].map(id_to_type)
            alt_df["target_type"] = alt_df["target_id"].map(id_to_type)
            alt_df = alt_df.dropna(subset=["target_type"])
            all_edges.append(alt_df[["source_id", "target_id", "source_type", "target_type"]])
            print(f"[INFO] Added {len(alt_df)} Altmetric second-order → OpenAlex first-order edges")

    # Altmetric second-order → Overton first-order
    if os.path.exists(compiled_altmetric_second_order_path) and os.path.exists(compiled_overton_first_order_path):
        alt_df = pd.read_csv(compiled_altmetric_second_order_path, dtype=str)
        overton_df = pd.read_csv(compiled_overton_first_order_path, dtype=str)
        overton_dois = set(overton_df["unique_identifier"].dropna().map(normalize_id))
        if "first_order_doi" in alt_df.columns:
            alt_df["source_id"] = alt_df["unique_identifier"].apply(normalize_id)
            alt_df["target_id"] = alt_df["first_order_doi"].apply(normalize_id)
            alt_df = alt_df[alt_df["target_id"].isin(overton_dois)]
            alt_df["source_type"] = alt_df["source_id"].map(id_to_type)
            alt_df["target_type"] = alt_df["target_id"].map(id_to_type)
            alt_df = alt_df.dropna(subset=["target_type"])
            all_edges.append(alt_df[["source_id", "target_id", "source_type", "target_type"]])
            print(f"[INFO] Added {len(alt_df)} Altmetric second-order → Overton first-order edges")

    # OpenAlex second-order → Overton first-order
    if os.path.exists(compiled_openalex_second_order_path) and os.path.exists(compiled_overton_first_order_path):
        openalex_df = pd.read_csv(compiled_openalex_second_order_path, dtype=str)
        overton_df = pd.read_csv(compiled_overton_first_order_path, dtype=str)
        overton_dois = set(overton_df["unique_identifier"].dropna().map(normalize_id))
        if "first_order_id" in openalex_df.columns:
            openalex_df["source_id"] = openalex_df["second_order_id"].apply(normalize_id)
            openalex_df["target_id"] = openalex_df["first_order_id"].apply(normalize_id)
            openalex_df = openalex_df[openalex_df["target_id"].isin(overton_dois)]
            openalex_df["source_type"] = openalex_df["source_id"].map(id_to_type)
            openalex_df["target_type"] = openalex_df["target_id"].map(id_to_type)
            openalex_df = openalex_df.dropna(subset=["target_type"])
            all_edges.append(openalex_df[["source_id", "target_id", "source_type", "target_type"]])
            print(f"[INFO] Added {len(openalex_df)} OpenAlex second-order → Overton first-order edges")


    # Combine and normalize edge list
    if all_edges:
        combined_df = pd.concat(all_edges, ignore_index=True)

        # Normalize type labels
        type_normalization = {
            "publication": "policy_document", "policy": "policy_document",
            "blog post": "blog_post", "blogs": "blog_post", "working paper": "working_paper",
            "clinical guidance": "clinical_guidance", "scholarly article": "academic_article",
            "article": "academic_article", "book-chapter": "book_chapter",
            "news": "news_website"
        }
        combined_df["source_type"] = combined_df["source_type"].str.lower().replace(type_normalization)
        combined_df["target_type"] = combined_df["target_type"].str.lower().replace(type_normalization)

        # Final ID normalization for safety
        combined_df["source_id"] = combined_df["source_id"].apply(normalize_id)
        combined_df["target_id"] = combined_df["target_id"].apply(normalize_id)

        # Assign edge_type and weight
        combined_df["edge_type"] = combined_df["source_type"] + "_citation"
        source_type_weights = {
            "news_website": 8,
            "blog_post": 5,
            "wikipedia": 5,
            "video": 5,
            "policy_document": 3,
            "clinical_guidance": 3,
            "transcript": 1,
            "patent": 1,
            "academic_article": 1,
            "working_paper": 1,
            "preprint": 1,
            "book": 2,
            "book_chapter": 2,
            "report": 2,
            "editorial": 1,
            "review": 1,
            "letter": 1,
            "peer-review": 1,
            "dataset": 0.5,
            "guideline": 1,
            "dissertation": 0.5,
            "grant": 0.5,
            "paratext": 0.25,
            "periodical": 0.25,
            "reference-entry": 0.25,
            "retraction": 0.25,
            "erratum": 0.25,
            "other": 0.01
        }
        combined_df["weighting"] = combined_df["source_type"].map(source_type_weights).fillna(1).astype(float)

        combined_df = combined_df.drop_duplicates(subset=["source_id", "target_id"])
        combined_df.to_csv(edges_path, index=False, float_format="%.2f", encoding="utf-8-sig", )
        print(f"[OK] Saved {len(combined_df)} edges to {edges_path}")
    else:
        print("[SKIP] No edge data found. Nothing saved.")

    return id_to_type

#----------------------------------------------------------------------------------------------------------
# Node file creation
#----------------------------------------------------------------------------------------------------------

# Multi-word expressions (with variants)
mwes = [
    "dual use", "dual-use",
    "gain of function", "gain-of-function",
    "catastrophic risks", "catastrophic risk",
    "existential risks", "existential risk",
    "biological weapon", "chemical weapon",
    "biological weapons", "chemical weapons",
    "nuclear weapon", "nuclear weapons",
    "biological warfare", "chemical warfare",
    "artificial intelligence", "artificial general intelligence",
    "national security", "military application", "military applications",
    "weapon of mass destruction", "weapons of mass destruction",
    "import control", "import controls",
    "information hazard", "information hazards",
    "information governance", "information security",
    "knowledge hazard", "knowledge hazards",
    "malicious actor", "malicious actors", "malicious use",
    "export control", "export controls",
    "biosecurity threat", "biosecurity threats",
    "synthetic biology", "non proliferation", "non-proliferation",
    "risk assessment", "risk assessments",
    "security implication", "security implications",
    "ai safety", "arms control", "arms controls",
    "responsible use", "counter-terrorism", "geo-political", "man-made",
    "chemical threat", "biological threat", "nuclear threat", "radiological threat",
    "chemical threats", "biological threats", "nuclear threats", "radiological threats",
    "counter terrorism", "biotechnology risk", "biological attacks", "biological attack",
    "engineered pandemic", "high-risk", "biological risk", "biological risks"
    "risk analysis", "risk management", "bio-terror", "governance framework", 
    "governance frameworks", "international security", "bad actor", "bad actors",
    "biological hazard", "biological hazards"
]

# Canonical mapping for MWEs
canonical_phrase_map = {
    "dual-use": "dual use",
    "gain-of-function": "gain of function",
    "catastrophic risks": "catastrophic risk",
    "existential risks": "existential risk",
    "biological weapons": "biological weapon",
    "chemical weapons": "chemical weapon",
    "nuclear weapons": "nuclear weapon",
    "military applications": "military application",
    "weapon of mass destruction": "weapons of mass destruction",
    "import control": "import controls",
    "export control": "export controls",
    "arms controls": "arms control",
    "malicious actors": "malicious actor",
    "non proliferation": "non-proliferation",
    "chemical threats": "chemical threat",
    "biological threats": "biological threat",
    "nuclear threats": "nuclear threat",
    "radiological threats": "radiological threat",
    "information hazards": "information hazard",
    "knowledge hazards": "knowledge hazard",
    "biosecurity threats": "biosecurity threat",
    "risk assessments": "risk assessment",
    "security implication": "security implications",
    "counter terrorism": "counter-terrorism",
    "geo-political": "geopolitical",
    "biological attacks": "biological attacks",
    "biological risks": "biological risk",
    "bio-terror": "bioterrorism",
    "governance frameworks": "governance framework",
    "bad actors": "malicious actor",
    "bad actor": "malicious actor",
    "terror": "terrorism",
    "biological hazards": "biological hazard"
}

# Atomic keywords of interest
atomic_keywords_of_interest = {
    "catastrophic", "biosecurity", "compliance", "adversarial",
    "threat", "threats", "terrorism", "terror", "weapon", "weapons", 
    "proliferation", "biohazard", "military", "weaponization", "weaponisation",
    "attack", "attacks", "conflict", "conflicts", "misuse", "biosafety", 
    "wmd", "wmds", "bioterror", "biothreat", "hazard", "hazards", "malicious",
    "nuclear", "defense", "defence", "war", "safety", "export", 
    "CBRN", "biodefence", "biodefense", "non-proliferation", "ai", "battlefield",
    "battlefields", "bioethics", "biohazards", "biorisk", "biorisks", "biosafety",
    "bioterrorism", "bioterror", "biothreat", "biothreats", "btwc", "bwc", "cwc",
    "counterterrorism",  "dilemma", "infohazard", "exports",
    "import", "imports", "geopolitical",  "geopolitics",
    "infohazards", "warfare", "radiological", "debate", "controversy", "controversies" 
    "controversial", "disastrous", "outrage", "bioweapon", "bioweapons", "biohacker",
    "biohackers", "ethical", "ethics", "bioterrorist", "bioterrorists", "risky", "risk",
    "risks", "regulation", "disarmament", "regulatory", "governance", "disaster", "biotechnology"
}

# Canonical mapping for atomic keywords
atomic_keyword_map = {
    "threats": "threat",
    "risks": "risk",
    "hazards": "hazard",
    "exports": "export",
    "imports": "import",
    "attacks": "attack",
    "weapons": "weapon",
    "biohazards": "biohazard",
    "biohazard": "biological hazard",
    "biothreats": "biothreat",
    "biothreat": "biological threat",
    "biorisks": "biorisk",
    "biorisk": "biological risk",
    "bioterror": "bioterrorism",
    "defence": "defense",
    "infohazards": "infohazard",
    "infohazard": "information hazard",
    "biodefence": "biodefense",
    "wmds": "wmd",
    "wmd": "weapons of mass destruction",
    "ai": "artificial intelligence",
    "weaponisation": "weaponization",
    "battlefields": "battlefield",
    "counterterrorism": "counter-terrorism",
    "conflicts": "conflict",
    "controversies": "controversy",
    "bioweapons": "bioweapon",
    "bioweapon": "biological weapon",
    "biohackers": "biohacker",
    "bioterrorists": "bioterrorist",
    "risky": "risk",
    "btwc": "bwc"
}


def clean_text(text):
    """Lowercase and strip markup/punctuation for keyword matching."""
    text = str(text).lower()
    text = re.sub(r"<[^>]+>", "", text)  
    text = re.sub(r"[–—−]", "-", text)
    text = re.sub(r"[\[\]{}()\"“”‘’,:;.!?]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _norm(s):
    """Normalize a string to alphanumeric tokens for fuzzy matching."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def extract_keywords_overton(row):
    """Extract keywords from Overton metadata row and compute infohazard score."""
    combined_text = f"{row['title']} {row['document_theme']} {row['top_topics'].replace('|', ' ')}"
    cleaned = clean_text(combined_text)

    raw_phrases = [p for p in mwes if p in cleaned]
    canonical_phrases = {canonical_phrase_map.get(p, p) for p in raw_phrases}
    phrase_tokens = set(w for p in raw_phrases for w in re.findall(r"\b\w+\b", p))

    raw_atomic = [w for w in atomic_keywords_of_interest if re.search(rf"\b{re.escape(w)}\b", cleaned)]
    raw_atomic = [w for w in raw_atomic if w not in phrase_tokens]
    canonical_atomic = {atomic_keyword_map.get(w, w) for w in raw_atomic}

    norm_phrases = {_norm(p) for p in canonical_phrases}
    canonical_atomic = {w for w in canonical_atomic if _norm(w) not in norm_phrases}

    all_concepts = sorted(canonical_phrases | canonical_atomic)
    return compute_infohazard_score(all_concepts)

def extract_keywords_openalex(row):
    """Extract keywords from OpenAlex metadata row and compute infohazard score."""
    combined_text = ' '.join(str(row.get(col, '')) for col in row.index if col != "id").replace('|', ' ')
    cleaned = clean_text(combined_text)

    raw_phrases = [p for p in mwes if p in cleaned]
    canonical_phrases = {canonical_phrase_map.get(p, p) for p in raw_phrases}
    phrase_tokens = set(w for p in raw_phrases for w in re.findall(r"\b\w+\b", p))

    raw_atomic = [w for w in atomic_keywords_of_interest if re.search(rf"\b{re.escape(w)}\b", cleaned)]
    raw_atomic = [w for w in raw_atomic if w not in phrase_tokens]
    canonical_atomic = {atomic_keyword_map.get(w, w) for w in raw_atomic}

    norm_phrases = {_norm(p) for p in canonical_phrases}
    canonical_atomic = {w for w in canonical_atomic if _norm(w) not in norm_phrases}

    all_concepts = sorted(canonical_phrases | canonical_atomic)
    return compute_infohazard_score(all_concepts)

def extract_altmetric_keywords(row):
    """Extract keywords from Altmetric metadata row and compute infohazard score."""
    combined_text = f"{row['title']} {row['summary']}"
    cleaned = clean_text(combined_text)

    raw_phrases = [p for p in mwes if p in cleaned]
    canonical_phrases = {canonical_phrase_map.get(p, p) for p in raw_phrases}
    phrase_tokens = set(w for p in raw_phrases for w in re.findall(r"\b\w+\b", p))

    raw_atomic = [w for w in atomic_keywords_of_interest if re.search(rf"\b{re.escape(w)}\b", cleaned)]
    raw_atomic = [w for w in raw_atomic if w not in phrase_tokens]
    canonical_atomic = {atomic_keyword_map.get(w, w) for w in raw_atomic}

    norm_phrases = {_norm(p) for p in canonical_phrases}
    canonical_atomic = {w for w in canonical_atomic if _norm(w) not in norm_phrases}

    all_concepts = sorted(canonical_phrases | canonical_atomic)
    return compute_infohazard_score(all_concepts)

def trim(df):
    """Keep only standard metadata columns if present."""
    return df[[c for c in ['id', 'title', 'publication_date', 'infohazard_concepts', 'score'] if c in df.columns]]

def compute_infohazard_score(all_concepts: set) -> pd.Series:
    """Assign weighted score to concept set based on criticality tiers and return Series."""

    critical_terms = {
        "dual use", "gain of function", "information hazard", "knowledge hazard",
        "malicious use", "malicious actor", "misuse", "weaponization", 
        "bioterrorism", "engineered pandemic", "catastrophic risk", "existential risk",
        "biological weapon", "biological warfare", "bioterrorist", "biohacker",
        "responsible use", "biotechnology risk", "biological attack", "terrorism", 
        "counter-terrorism", "weapons of mass destruction", "military application"
    }

    high_relevance_terms = {
        "biosecurity threat", "export controls", "import controls", "military",
        "biodefense", "biological hazard", "information security",
        "information governance", "synthetic biology", "biological risk",  
        "biological threat", "bioethics", "arms control"
    }
    
    medium_relevance_terms = {
        "risk assessment", "security implications", "chemical weapon", "nuclear weapon",
        "governance", "national security", "artificial intelligence", "chemical warfare",
        "proliferation", "dilemma", "disastrous", "outrage", "disarmament", "debate", 
        "risk management", "risk analysis", "high-risk", "controversy", "controversial",  
        "governance framework", "weapon", "artificial general intelligence", "ai safety",
        "geopolitical", "man-made", "chemical threat", "nuclear threat", "radiological threat",
        "international security", "weapon", "adversarial", "proliferation", "warfare", 
        "non-proliferation", "war", "malicious", "CBRN", "battlefield", "bwc", "cwc",
        "biotechnology", "biosecurity", "biosafety"
    }

    score = 0
    critical_hits = 0
    high_hits = 0
    medium_hits = 0
    low_hits = 0

    for term in all_concepts:
        if term in critical_terms:
            score += 8
            critical_hits += 1
        elif term in high_relevance_terms:
            score += 5
            high_hits += 1
        elif term in medium_relevance_terms:
            score += 2
            medium_hits += 1
        else:
            score += 1
            low_hits += 1

    # Special case boost: exactly one critical term and no other matches
    if critical_hits == 1 and (high_hits + medium_hits + low_hits) == 0:
        score += 8  # Bonus bump

    return pd.Series({
        'infohazard_concepts': '; '.join(sorted(all_concepts)),
        'score': score
    })


def create_nodes(output_directory = os.path.join(base_dir, "processed_data")):
    """Run node creation."""

    nodes_path = os.path.join(output_directory, "nodes.csv")
    edges_path = os.path.join(output_directory, "edges.csv")
    core_papers_path = os.path.join(output_directory, "core_papers.csv")

    # ---------- Overton ----------
    overton_files = [
        "compiled_overton_second_order.csv",
        "compiled_overton_first_order.csv",
        "compiled_altmetric_overton_second_order.csv",
        "compiled_openalex_overton_second_order.csv"
    ]
    overton_cols = {
        "unique_identifier": "id",
        "title": "title",
        "published_on": "publication_date",
        "top_topics": "top_topics",
        "document_theme": "document_theme"
    }
    overton_nodes = []
    for file in overton_files:
        df = pd.read_csv(f"{output_directory}/{file}", dtype=str)
        df = df[[col for col in overton_cols if col in df.columns]].rename(columns=overton_cols)
        overton_nodes.append(df)

    overton_df = pd.concat(overton_nodes, ignore_index=True).drop_duplicates(subset="id")
    for col in ['title', 'top_topics', 'document_theme']:
        overton_df[col] = overton_df[col].fillna('')
    overton_df["id"] = overton_df["id"].apply(normalize_id)
    keywords = overton_df.apply(extract_keywords_overton, axis=1)
    overton_df = pd.concat([overton_df, keywords], axis=1)

    # ---------- OpenAlex ----------
    openalex_cols = [
        "title", "publication_date",
        "primary_topic.display_name", "primary_topic.subfield.display_name", "primary_topic.domain.display_name",
        "topics.display_name", "topics.field.display_name", "topics.domain.display_name",
        "keywords.display_name", "concepts.display_name", "mesh.descriptor_name", "mesh.qualifier_name"
    ]
    openalex_nodes = []
    for path, id_col in [("compiled_openalex_first_order.csv", "first_order_doi"), ("compiled_openalex_second_order.csv", "second_order_id")]:
        df = pd.read_csv(f"{output_directory}/{path}", dtype=str)
        df["id"] = df[id_col]
        df = df[["id"] + [col for col in openalex_cols if col in df.columns]]
        openalex_nodes.append(df)

    openalex_df = pd.concat(openalex_nodes, ignore_index=True).drop_duplicates(subset="id")
    for col in openalex_cols:
        if col in openalex_df.columns:
            openalex_df[col] = openalex_df[col].fillna('')
    openalex_df["id"] = openalex_df["id"].apply(normalize_id)
    keywords = openalex_df.apply(extract_keywords_openalex, axis=1)
    openalex_df = pd.concat([openalex_df, keywords], axis=1)

    # ---------- Altmetric ----------
    altmetric_cols = {
        "unique_identifier": "id",
        "title": "title",
        "posted_on": "publication_date",
        "summary": "summary"
    }
    altmetric_nodes = []
    for file in ["compiled_altmetric_first_order.csv", "compiled_altmetric_second_order.csv"]:
        df = pd.read_csv(f"{output_directory}/{file}", dtype=str)
        df = df[[col for col in altmetric_cols if col in df.columns]].rename(columns=altmetric_cols)
        altmetric_nodes.append(df)

    altmetric_df = pd.concat(altmetric_nodes, ignore_index=True).drop_duplicates(subset="id")
    altmetric_df["id"] = altmetric_df["id"].apply(normalize_id)
    altmetric_df["title"] = altmetric_df["title"].fillna('')
    altmetric_df["summary"] = altmetric_df["summary"].fillna('')
    keywords = altmetric_df.apply(extract_altmetric_keywords, axis=1)
    altmetric_df = pd.concat([altmetric_df, keywords], axis=1)

    # ---------- Merge and Filter ----------
    merged_nodes = pd.concat([
        trim(overton_df),
        trim(altmetric_df),
        trim(openalex_df)
    ], ignore_index=True).drop_duplicates(subset="id")

    # Normalize node IDs
    merged_nodes["id"] = merged_nodes["id"].apply(normalize_id)

    # Load edges
    edges_df = pd.read_csv(f"{output_directory}/edges.csv", dtype=str)
    edges_df["source_id"] = edges_df["source_id"].apply(normalize_id)
    edges_df["target_id"] = edges_df["target_id"].apply(normalize_id)
    used_ids = set(edges_df["source_id"]) | set(edges_df["target_id"])

    # Filter to connected nodes only
    merged_nodes = merged_nodes[merged_nodes["id"].isin(used_ids)]

    # Save
    merged_nodes.to_csv(f"{output_directory}/nodes.csv", index=False, encoding="utf-8-sig")

    # Load core papers and clean DOIs
    core_df = pd.read_csv(core_papers_path, dtype=str)
    core_df['doi_clean'] = core_df['doi'].apply(normalize_id)

    # Load and normalize nodes
    nodes_df = pd.read_csv(nodes_path, dtype=str)
    nodes_df['id'] = nodes_df['id'].apply(normalize_id)

    # Mark all core paper IDs
    core_ids = set(core_df['doi_clean'].dropna())

    # Update existing rows in nodes
    nodes_df['is_core'] = nodes_df['id'].isin(core_ids)
    nodes_df.loc[nodes_df['is_core'], 'infohazard_concepts'] = ""
    nodes_df.loc[nodes_df['is_core'], 'score'] = "0"
    nodes_df.drop(columns=['is_core'], inplace=True)

    # Find missing core papers (not in existing IDs)
    existing_ids = set(nodes_df['id'].dropna())
    missing_core = core_df[~core_df['doi_clean'].isin(existing_ids)]

    # Create rows for missing core papers
    new_rows = missing_core[['doi_clean', 'title']].rename(columns={'doi_clean': 'id'})
    new_rows['publication_date'] = missing_core['publication_date']
    new_rows['infohazard_concepts'] = ""
    new_rows['score'] = "0"

    # Ensure all required columns exist
    for col in nodes_df.columns:
        if col not in new_rows.columns:
            new_rows[col] = ""

    new_rows = new_rows[nodes_df.columns]

    # Merge and save
    updated_nodes = pd.concat([nodes_df, new_rows], ignore_index=True)
    updated_nodes.to_csv(nodes_path, index=False, encoding='utf-8-sig')

    print(f"Inserted {len(new_rows)} missing core papers and updated all core weights/concepts.")
    print(f"Total rows in nodes: {len(updated_nodes)}")

    # Load csv files and save to dataframes
    nodes_df = pd.read_csv(nodes_path, dtype=str)
    edges_df = pd.read_csv(edges_path, dtype=str)
    core_df = pd.read_csv(core_papers_path, dtype=str)

    # Clean and parse node dates 
    # Standardize invalid entries
    nodes_df["publication_date"] = nodes_df["publication_date"].apply(normalize_pub_date)
    print("[DEBUG] Null publication_date count before parsing:", nodes_df["publication_date"].isna().sum())

    # Date parsing 
    nodes_df["parsed_date"] = pd.to_datetime(nodes_df["publication_date"], errors="coerce")
    bad_dates = nodes_df[nodes_df["parsed_date"].isna()]
    print("[DEBUG] Example unparseable publication_date values:")
    print(bad_dates["publication_date"].value_counts().head(10))

    # Drop rows with unparseable dates
    before_drop = len(nodes_df)
    nodes_df = nodes_df.dropna(subset=["parsed_date"])
    after_drop = len(nodes_df)
    print(f"[INFO] Dropped {before_drop - after_drop} nodes with missing/unparseable dates")

    # Load and parse core dates 
    core_df["publication_date"] = pd.to_datetime(core_df["publication_date"], errors="coerce")
    oldest_core_date = core_df["publication_date"].dropna().min()

    if pd.isna(oldest_core_date):
        raise ValueError("[ERROR] No valid core paper dates found.")
    print(f"[INFO] Oldest core paper date: {oldest_core_date.date()}")

    # Filter outdated nodes 
    # Identify outdated nodes (published before oldest core paper)
    outdated_nodes_df = nodes_df[nodes_df["parsed_date"] < oldest_core_date].copy()
    outdated_node_ids = set(outdated_nodes_df["id"])

    # Then filter them out
    before_filter = len(nodes_df)
    nodes_df = nodes_df[nodes_df["parsed_date"] >= oldest_core_date].copy()
    after_filter = len(nodes_df)
    print(f"[INFO] Removed {before_filter - after_filter} outdated nodes (older than {oldest_core_date.date()})")

    #  Clean edges 
    # Find edges involving outdated nodes
    edges_with_old_nodes = edges_df[
        (edges_df["source_id"].isin(outdated_node_ids)) |
        (edges_df["target_id"].isin(outdated_node_ids))
    ]

    # Find dependent nodes that might be kept
    possibly_dependent_nodes = (
        set(edges_with_old_nodes["source_id"]) |
        set(edges_with_old_nodes["target_id"])
    ) - outdated_node_ids

    # Determine which are used elsewhere
    remaining_edges = edges_df[
        ~edges_df["source_id"].isin(outdated_node_ids) &
        ~edges_df["target_id"].isin(outdated_node_ids)
    ]
    still_connected_nodes = set(remaining_edges["source_id"]) | set(remaining_edges["target_id"])
    protected_nodes = possibly_dependent_nodes & still_connected_nodes

    # Preserve edges involving protected nodes
    edges_to_preserve = edges_with_old_nodes[
        edges_with_old_nodes["source_id"].isin(protected_nodes) |
        edges_with_old_nodes["target_id"].isin(protected_nodes)
    ]
    edges_df_clean = pd.concat([remaining_edges, edges_to_preserve], ignore_index=True)

    print(f"[INFO] Removed {len(edges_df) - len(edges_df_clean)} edges")

    # Remove disconnected nodes
    connected_ids = set(edges_df_clean["source_id"]) | set(edges_df_clean["target_id"])
    disconnected_nodes = set(nodes_df["id"]) - connected_ids
    nodes_df_clean = nodes_df[nodes_df["id"].isin(connected_ids)].drop(columns="parsed_date")

    print(f"[INFO] Removed {len(disconnected_nodes)} disconnected nodes")

    # Ensure all edges only reference nodes that still exist
    valid_node_ids = set(nodes_df_clean["id"])
    edges_before = len(edges_df_clean)

    edges_df_clean = edges_df_clean[
        edges_df_clean["source_id"].isin(valid_node_ids) &
        edges_df_clean["target_id"].isin(valid_node_ids)
    ].copy()

    edges_after = len(edges_df_clean)
    print(f"[INFO] Removed {edges_before - edges_after} edges pointing to missing nodes (final cleanup)")

    # Save cleaned files 
    nodes_df_clean.to_csv(nodes_path, index=False, encoding="utf-8-sig")
    edges_df_clean.to_csv(edges_path, index=False, encoding="utf-8-sig")

    print(f"[DONE] Cleaned nodes and edges saved to:\n- {nodes_path}\n- {edges_path}")

    edges_df = pd.read_csv(edges_path)
    nodes_df = pd.read_csv(nodes_path)

    # Normalize and fill empty string types
    edges_df["source_type"] = edges_df["source_type"].fillna("").str.strip().str.lower()
    edges_df["target_type"] = edges_df["target_type"].fillna("").str.strip().str.lower()

    # Create mapping from ID to type
    source_map = edges_df[["source_id", "source_type"]].dropna().drop_duplicates()
    target_map = edges_df[["target_id", "target_type"]].dropna().drop_duplicates()

    # Combine both maps
    source_map.columns = ["id", "node_type"]
    target_map.columns = ["id", "node_type"]
    type_map_df = pd.concat([source_map, target_map], ignore_index=True)

    # Drop conflicting entries by keeping the first
    type_map_df = type_map_df.drop_duplicates(subset="id", keep="first")

    # Build final mapping dictionary
    id_to_type = type_map_df.set_index("id")["node_type"].to_dict()

    # Apply to nodes
    nodes_df["node_type"] = nodes_df["id"].map(id_to_type).fillna("unknown")

    # Save output
    nodes_df.to_csv(nodes_path, index=False, encoding="utf-8-sig")
    print(f"[OK] Added 'node_type' column to {nodes_path}")

    edges_df = pd.read_csv(edges_path)
    nodes_df = pd.read_csv(nodes_path)

    # Unique source and target IDs
    unique_source_ids = set(edges_df['source_id'])
    unique_target_ids = set(edges_df['target_id'])

    # Unique IDs in edges (source and target combined)
    edge_node_ids = unique_source_ids | unique_target_ids
    print(f"Total unique node IDs in edges file: {len(edge_node_ids)}")

    # Unique IDs in node metadata file
    node_ids = set(nodes_df['id'])  
    print(f"Total unique node IDs in nodes file: {len(node_ids)}")

    # How many are missing from nodes file
    missing_from_nodes = edge_node_ids - node_ids
    print(f"IDs in edges but missing from nodes: {len(missing_from_nodes)}")


if __name__ == "__main__":
    create_edges()
    create_nodes()