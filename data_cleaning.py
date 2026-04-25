import os
import pandas as pd
import glob
import re
import csv
import langdetect
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException
from datetime import datetime
from pandas.errors import ParserError
import requests
import pyalex
from pyalex import Works, Authors, Sources, Institutions, Topics, Publishers, Funders
pyalex.config.email = #INSERT YOUR OPENALEX ACCOUNT EMAIL HERE
import urllib.parse
import time
import utils
from utils import normalize_id

# ----------- Helper Functions -----------
def normalize_doi(doi):
    """Extract and normalize a DOI string to lowercase '10.xxxx/...' form."""
    if pd.isna(doi): return None
    m = re.search(r"(10\.\d{4,9}/\S+)", str(doi), re.IGNORECASE)
    return m.group(1).lower() if m else None

def normalize_oa_id(oaid):
    """Normalize an OpenAlex ID to canonical uppercase 'Wxxxxxxx' form."""
    if pd.isna(oaid): 
        return None
    s = str(oaid).strip()
    seg = s.rsplit('/', 1)[-1]
    m = re.search(r'([Ww]\d+)', seg) 
    return m.group(1).upper() if m else None

def fetch_core_doi(oa_id, max_retries=5, backoff_factor=2):
    """Fetch DOI for a given OpenAlex source ID."""
    url = f"https://api.openalex.org/works/https://openalex.org/{oa_id}"
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return normalize_doi(data.get("doi"))
        except Exception as e:
            print(f"Attempt {attempt} failed for {oa_id}: {e}")
            if attempt < max_retries:
                sleep_time = backoff_factor ** (attempt - 1)
                print(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                print(f"Error fetching core DOI for {oa_id}: {e}")
                return None

def deduplicate_first_order(df):
    """Deduplicate first-order rows by DOI, keeping earliest per type."""
    if 'doi' not in df.columns or 'type' not in df.columns:
        return df

    df['doi'] = df['doi'].map(normalize_id)
    deduped = []
    for doi, group in df.groupby('doi'):
        if group['type'].nunique() > 1:
            group['parsed_date'] = pd.to_datetime(group['publication_date'], format='%Y-%m-%d', errors='coerce')
            group = group.sort_values(by='parsed_date')
        deduped.append(group.iloc[:1])
    return pd.concat(deduped, ignore_index=True)

def deduplicate_second_order(df, cfo_column):
    """Deduplicate second-order rows by (DOI, citing policy DOI), keep earliest."""
    if 'doi' not in df.columns or 'type' not in df.columns or cfo_column not in df.columns:
        return df

    df = df.copy()
    df['doi'] = df['doi'].map(normalize_id)
    df['_cfo_norm'] = df[cfo_column].map(normalize_id)

    deduped = []
    for _, group in df.groupby(['doi', '_cfo_norm']):
        if group['type'].nunique() > 1:
            group = group.copy()
            group['parsed_date'] = pd.to_datetime(
                group.get('publication_date', pd.Series(index=group.index, dtype=object)),
                format='%Y-%m-%d', errors='coerce'
            )
            group = group.sort_values(by='parsed_date', na_position='last')
        deduped.append(group.iloc[:1])

    out = pd.concat(deduped, ignore_index=True)
    out.drop(columns=['parsed_date', '_cfo_norm'], errors='ignore', inplace=True)
    return out

def detect_language(text):
    """Detect language of text with langdetect, fallback to 'unknown'."""
    try:
        return detect(str(text))
    except LangDetectException:
        return "unknown"

def convert_date_format(date_str):
    """Convert ISO date string to 'DD/MM/YYYY', else return original."""
    try:
        return datetime.fromisoformat(date_str).strftime('%d/%m/%Y')
    except Exception:
        return date_str

def normalize_col(col):
    """Normalize column name: strip BOM, lowercase, replace spaces with underscores."""
    return col.replace('\ufeff', '').strip().lower().replace(" ", "_")

def insert_dois(df, id_col, doi_col, new_col_name, drop_doi=False):
    """Insert DOIs into ID column, rename to new_col_name, optionally drop DOI column."""
    if id_col not in df.columns:
        return df

    df[id_col] = df[id_col].map(normalize_id)

    if doi_col and doi_col in df.columns:
        df[doi_col] = df[doi_col].map(normalize_id)
        mask = df[doi_col].notna() & df[doi_col].str.strip().ne("")
        df.loc[mask, id_col] = df.loc[mask, doi_col]

    if new_col_name in df.columns and new_col_name != id_col:
        df.drop(columns=[new_col_name], inplace=True)

    df.rename(columns={id_col: new_col_name}, inplace=True)

    if drop_doi and doi_col and doi_col in df.columns:
        df.drop(columns=[doi_col], inplace=True)

    return df

def deduplicate_df(df):
    """Deduplicate DataFrame rows by 'unique_identifier' if present, else all columns."""
    if "unique_identifier" in df.columns:
        df["unique_identifier"] = df["unique_identifier"].map(normalize_id)
        return df.drop_duplicates(subset="unique_identifier", keep="first")
    return df.drop_duplicates()


#---------------Variables-----------------

input_directory = "raw_collection_data"
output_directory = "processed_data"
DetectorFactory.seed = 42


# ------------ Regex patterns ---------------
oa_first_order_pattern = re.compile(r"^openalex_([A-Z0-9]+)_first_order\.csv$", re.IGNORECASE)
oa_second_order_pattern = re.compile(r"^openalex_([A-Z0-9]+)_second_order\.csv$", re.IGNORECASE)
oa_combined_filename = "combined_openalex_second_order_ov_first_order.csv"

alt_first_order_pattern = re.compile(r"^altmetric_[A-Z0-9]+_first_order_mentions\.csv$")
alt_second_order_pattern = re.compile(r"^openalex_W\d+_altmetric_second_order\.csv$")
alt_combined_filename = "combined_altmetric_second_order_ov_first_order.csv"

ov_first_order_pat = re.compile(r"^10\.\d+_[\w\.]+_overton_first_order\.csv$")
ov_second_order_pat = re.compile(r"^10\.\d+_[\w\.]+_overton_second_order\.csv$")
openalex_overton_second_pat = re.compile(r"^openalex_W\d+_overton_second_order\.csv$")
altmetric_overton_second_pat = re.compile(r"^altmetric_\d+_overton_second_order\.csv$")

# ------------ File groups -------------------
file_groups = {
    "compiled_openalex_first_order.csv": lambda f: oa_first_order_pattern.match(f),
    "compiled_openalex_second_order.csv": lambda f: oa_second_order_pattern.match(f) or f == oa_combined_filename,
    "compiled_openalex_overton_second_order.csv": lambda f: openalex_overton_second_pat.match(f),
    "compiled_altmetric_first_order.csv": lambda f: alt_first_order_pattern.match(f),
    "compiled_altmetric_second_order.csv": lambda f: alt_second_order_pattern.match(f) or f == alt_combined_filename,
    "compiled_overton_first_order.csv": lambda f: ov_first_order_pat.match(f),
    "compiled_overton_second_order.csv": lambda f: ov_second_order_pat.match(f),
    "compiled_altmetric_overton_second_order.csv": lambda f: altmetric_overton_second_pat.match(f),
}

#-------------------------------------------------------------------------------------------------------------------------------------------

def clean_data(input_directory = "raw_collection_data", output_directory = "processed_data"):
    """Run data cleaning pipeline."""

    # --- OpenAlex files ---
    columns_to_drop = [
        'publication_year', 'cited_by_count', 'cited_by_api_url',
        'ids.openalex', 'ids.doi'
    ]
    for filename in os.listdir(input_directory):
        if not (
            oa_first_order_pattern.match(filename) or
            oa_second_order_pattern.match(filename) or
            filename == oa_combined_filename
        ):
            continue

        input_path = os.path.join(input_directory, filename)
        df = pd.read_csv(input_path)

        existing_cols_to_drop = [col for col in columns_to_drop if col in df.columns]
        df.drop(columns=existing_cols_to_drop, inplace=True)

        output_path = os.path.join(output_directory, filename)
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"Saved cleaned file to: {output_path} — removed columns: {existing_cols_to_drop}")

    print("\nAll matching files processed.\n")


    for filename in os.listdir(output_directory):
        if not (
            oa_first_order_pattern.match(filename) or
            oa_second_order_pattern.match(filename) or
            filename == oa_combined_filename
        ):
            continue

        file_path = os.path.join(output_directory, filename)
        df = pd.read_csv(file_path, dtype=str)
        original_len = len(df)

        if oa_first_order_pattern.match(filename):
            df = deduplicate_first_order(df)
        elif oa_second_order_pattern.match(filename):
            df = deduplicate_second_order(df, cfo_column='cites_first_order_id')
        elif filename == oa_combined_filename:
            df = deduplicate_second_order(df, cfo_column='original_doi')

        removed = original_len - len(df)
        df.drop(columns='parsed_date', errors='ignore', inplace=True)
        print(f"{filename}: {removed} rows removed")

        df.to_csv(file_path, index=False, encoding='utf-8-sig')

    print("\nOpenAlex deduplication complete.\n")

    # Build DOI map and core DOI lookup
    doi_map = {}
    core_doi_lookup = {}

    for fn in os.listdir(output_directory):
        m = oa_first_order_pattern.match(fn)
        if not m: continue

        oa_id = m.group(1)
        df = pd.read_csv(os.path.join(output_directory, fn), encoding="utf-8")
        df.columns = [c.replace('\ufeff', '') for c in df.columns]
        if 'id' not in df.columns or 'doi' not in df.columns:
            print(f"Missing columns in first-order file: {fn}")
            continue

        df['openalex'] = df['id'].map(normalize_oa_id).map(normalize_id)
        df['doi_raw'] = df['doi'].map(normalize_doi).map(normalize_id)
        doi_map.update({r.openalex: r.doi_raw for _, r in df.dropna(subset=['openalex', 'doi_raw']).iterrows()})
        core_doi_lookup[oa_id] = fetch_core_doi(oa_id)

    # Transform first-order files (overwrite)
    for fn in os.listdir(output_directory):
        match = oa_first_order_pattern.match(fn)
        if not match:
            continue

        oa_id = match.group(1)
        core_doi = core_doi_lookup.get(oa_id)
        path = os.path.join(output_directory, fn)

        df = pd.read_csv(path, encoding="utf-8")
        df.columns = [c.replace('\ufeff', '') for c in df.columns]
        if 'doi' not in df.columns:
            print(f"Skipping (missing 'doi') in: {fn}")
            continue

        df['first_order_doi'] = df['doi'].map(normalize_doi).map(normalize_id)
        df.insert(0, 'core_doi', normalize_id(core_doi) if core_doi else "")
        df = df.drop(columns=['id', 'doi'], errors='ignore')
        df.to_csv(path, index=False, encoding='utf-8-sig')

    # Transform second-order files (overwrite)
    for fn in os.listdir(output_directory):
        match = oa_second_order_pattern.match(fn)
        if not match:
            continue

        path = os.path.join(output_directory, fn)
        df = pd.read_csv(path, encoding="utf-8")
        df.columns = [col.replace('\ufeff', '') for col in df.columns]

        if 'cites_first_order_id' not in df.columns:
            print(f"Skipping (missing 'cites_first_order_id'): {fn}")
            continue

        norm_first_ids = df['cites_first_order_id'].map(normalize_oa_id).map(normalize_id)
        df['first_order_id'] = norm_first_ids.map(doi_map).fillna(norm_first_ids)

        norm_second_ids = df['id'].map(normalize_oa_id).map(normalize_id)
        norm_dois = df['doi'].map(normalize_doi).map(normalize_id)
        df['second_order_id'] = norm_dois.fillna(norm_second_ids)

        missing_first = df['first_order_id'].isna().sum()
        missing_second = df['second_order_id'].isna().sum()
        if missing_first > 0 or missing_second > 0:
            print(f"Missing entries in {fn} — first_order_id: {missing_first}, second_order_id: {missing_second}")

        keep_cols = [
            'first_order_id', 'second_order_id', 'title', 'publication_date', 'type',
            'primary_topic.display_name', 'primary_topic.subfield.display_name', 'primary_topic.domain.display_name',
            'topics.display_name', 'topics.field.display_name', 'topics.domain.display_name',
            'keywords.display_name', 'concepts.display_name', 'mesh.descriptor_name', 'mesh.qualifier_name'
        ]
        df_out = df[keep_cols]
        df_out.to_csv(path, index=False, encoding='utf-8-sig')

    # Step 4: Transform combined file
    combined_path = os.path.join(output_directory, oa_combined_filename)
    if os.path.exists(combined_path):
        df = pd.read_csv(combined_path, encoding='utf-8-sig')
        df.columns = [col.replace('\ufeff', '') for col in df.columns]

        df['second_order_id'] = df['doi'].map(normalize_doi).map(normalize_id)
        df = df.rename(columns={'original_doi': 'first_order_id'})
        df['first_order_id'] = df['first_order_id'].map(normalize_id)
        df = df.drop(columns=['id', 'doi', 'source', 'linked_to_doi'], errors='ignore')
        df.to_csv(combined_path, index=False, encoding='utf-8-sig')
        print("\nCombined file transformed and overwritten.\n")
    else:
        print("Combined file not found.")


    # --- Altmetric files ---

    columns_to_drop = [
        'citation_ids', 'author_name', 'author_description', 'youtube_id', 'ucid'
    ]

    for filename in os.listdir(input_directory):
        if not (
            alt_first_order_pattern.match(filename) or 
            alt_second_order_pattern.match(filename) or 
            filename == alt_combined_filename
        ):
            continue

        input_path = os.path.join(input_directory, filename)
        output_path = os.path.join(output_directory, filename)

        try:
            df = pd.read_csv(input_path, dtype=str, encoding='utf-8-sig')

            if filename == alt_combined_filename:
                for col in df.columns:
                    if col.strip().lower() == "original_doi":
                        df.rename(columns={col: "first_order_doi"}, inplace=True)
                        break
                if "url" in df.columns:
                    df.rename(columns={"url": "unique_identifier"}, inplace=True)
                drop_cols = ["linked_to_doi", "ucid"]
                df.drop(columns=[col for col in drop_cols if col in df.columns], inplace=True)
                df = df.iloc[:, :9]

            elif filename.startswith("altmetric_") and "_first_order_mentions" in filename:
                if "doi" in df.columns:
                    df.rename(columns={"doi": "core_doi"}, inplace=True)
                if "first_order_doi" in df.columns and "url" in df.columns:
                    df["url"] = df["first_order_doi"].combine_first(df["url"])
                    df.rename(columns={"url": "unique_identifier"}, inplace=True)
                    df.drop(columns=["first_order_doi"], inplace=True)
                drop_cols = [col for col in columns_to_drop if col in df.columns]
                df.drop(columns=drop_cols, inplace=True)

            elif re.match(r"openalex_W\d+_altmetric_second_order\.csv", filename, re.IGNORECASE):
                for col in df.columns:
                    if col.strip().lower() in {"original_doi", "source_doi"}:
                        df.rename(columns={col: "first_order_doi"}, inplace=True)
                        break
                if "url" in df.columns:
                    df.rename(columns={"url": "unique_identifier"}, inplace=True)
                drop_cols = ["linked_to_doi"] + columns_to_drop
                df.drop(columns=[col for col in drop_cols if col in df.columns], inplace=True)

            # Normalize IDs
            if 'unique_identifier' in df.columns:
                df['unique_identifier'] = df['unique_identifier'].map(normalize_id)
            if 'core_doi' in df.columns:
                df['core_doi'] = df['core_doi'].map(normalize_id)
            if 'first_order_doi' in df.columns:
                df['first_order_doi'] = df['first_order_doi'].map(normalize_id)

            # Language Filtering 
            if {'title', 'summary'}.issubset(df.columns):
                if 'lang_checked' not in df.columns:
                    original_len = len(df)
                    df['title_lang'] = df['title'].apply(lambda x: detect_language(x) if pd.notna(x) and str(x).strip() else "nan")
                    df['summary_lang'] = df['summary'].apply(lambda x: detect_language(x) if pd.notna(x) and str(x).strip() else "nan")
                    df = df[(df['title_lang'] == 'en') | (df['summary_lang'] == 'en')]
                    df.drop(columns=['title_lang', 'summary_lang'], inplace=True)
                    df['lang_checked'] = True
                    print(f"Filtered {filename}: removed {original_len - len(df)} non-English rows")

            # Date Formatting
            if 'posted_on' in df.columns:
                df['posted_on'] = df['posted_on'].apply(lambda x: convert_date_format(str(x)) if pd.notna(x) else x)
                print(f"Formatted 'posted_on' in {filename} to dd/mm/yyyy")

            # Remove Empty unique_identifier values
            if 'unique_identifier' in df.columns:
                before = len(df)
                df = df[df['unique_identifier'].notna() & (df['unique_identifier'].astype(str).str.strip() != '')]
                print(f"{filename}: Removed {before - len(df)} rows with empty/missing unique_identifier")

            # Deduplicate
            if 'unique_identifier' in df.columns:
                before = len(df)
                if 'altmetric_id' in df.columns:
                    df = df.drop_duplicates(subset=['unique_identifier', 'altmetric_id'], keep='first')
                else:
                    df = df.drop_duplicates(subset='unique_identifier', keep='first')
                print(f"{filename}: Removed {before - len(df)} duplicate unique_identifier entries")

            # Save to csv
            df.to_csv(output_path, index=False, encoding='utf-8-sig')
            print(f"Saved cleaned file: {filename}")

        except Exception as e:
            print(f"Could not process {filename}: {e}")

    print("\nAltmetric data cleaning complete.\n")


    # --- Overton files ---

    # Columns to Keep 
    first_order_keep = [
        "overton_id", "title", "translated_title", "document_type",
        "published_on", "document_url", "source_specific_tags",
        "top_topics", "languages", "document_theme", "policy_document_dois"
    ]
    second_order_keep = first_order_keep + ["first_order_overton_id"]
    second_alt_keep = first_order_keep + ["first_order_doi"]

    # Make data consistent
    for filename in os.listdir(input_directory):
        if not (
            ov_first_order_pat.match(filename)
            or ov_second_order_pat.match(filename)
            or openalex_overton_second_pat.match(filename)
            or altmetric_overton_second_pat.match(filename)
        ):
            continue

        input_path = os.path.join(input_directory, filename)
        output_path = os.path.join(output_directory, filename)

        try:
            df = pd.read_csv(input_path, dtype=str, encoding='utf-8-sig')
        except Exception as e:
            print(f"Could not read {filename}: {e}")
            continue

        df.columns = [normalize_col(c) for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        

        if ov_second_order_pat.match(filename):
            if "cited_overton_id" in df.columns:
                df.rename(columns={"cited_overton_id": "first_order_overton_id"}, inplace=True)
            keep_cols = [col for col in second_order_keep if col in df.columns]
        elif openalex_overton_second_pat.match(filename) or altmetric_overton_second_pat.match(filename):
            keep_cols = [col for col in second_alt_keep + ["first_order_doi"] if col in df.columns]
        else:
            keep_cols = [col for col in second_alt_keep if col in df.columns]

        df = df[keep_cols]

        # Replace non-English titles
        if "languages" in df.columns:
            non_eng = df["languages"].str.lower() != "eng"
            if "translated_title" in df.columns:
                mask = non_eng & df["translated_title"].notna() & df["translated_title"].str.strip().ne("")
                df.loc[mask, "title"] = df.loc[mask, "translated_title"]
            drop_mask = (
                non_eng &
                (df["translated_title"].isna() | df["translated_title"].str.strip().eq("")) &
                df["document_theme"].isna() & df["top_topics"].isna()
            )
            df = df[~drop_mask]
            if "translated_title" in df.columns:
                df.drop(columns="translated_title", inplace=True)

        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"Cleaned: {filename}")

    # Deduplication
    for filename in os.listdir(output_directory):
        if not (
            ov_first_order_pat.match(filename)
            or ov_second_order_pat.match(filename)
            or openalex_overton_second_pat.match(filename)
            or altmetric_overton_second_pat.match(filename)
        ):
            continue

        file_path = os.path.join(output_directory, filename)

        try:
            df = pd.read_csv(file_path, dtype=str, encoding='utf-8-sig')
        except Exception as e:
            print(f"Could not read {filename}: {e}")
            continue

        for col in ['overton_id', 'policy_document_dois', 'first_order_doi', 'first_order_overton_id']:
            if col in df.columns:
                df[col] = df[col].map(normalize_id)

        original_len = len(df)

        if ov_first_order_pat.match(filename) or ov_second_order_pat.match(filename):
            if 'overton_id' in df.columns:
                df = df.drop_duplicates(subset='overton_id', keep='first')
            if 'policy_document_dois' in df.columns:
                mask = df['policy_document_dois'].notna() & df['policy_document_dois'].str.strip().ne("")
                df = pd.concat([
                    df[mask].drop_duplicates(subset='policy_document_dois', keep='first'),
                    df[~mask]
                ], ignore_index=True)

        elif openalex_overton_second_pat.match(filename) or altmetric_overton_second_pat.match(filename):
            if {"overton_id", "first_order_doi"}.issubset(df.columns):
                df = df.drop_duplicates(subset=["overton_id", "first_order_doi"], keep="first")
        
            if {"policy_document_dois", "first_order_doi"}.issubset(df.columns):
                mask = df['policy_document_dois'].notna() & df['policy_document_dois'].str.strip().ne("")
                df = pd.concat([
                    df[mask].drop_duplicates(subset=["policy_document_dois", "first_order_doi"], keep='first'),
                    df[~mask]
                ], ignore_index=True)

        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        print(f"{filename}: {original_len - len(df)} duplicates removed")

    # Build DOI Mapping
    doi_map = {}
    for filename in os.listdir(output_directory):
        if not (
            ov_first_order_pat.match(filename)
            or ov_second_order_pat.match(filename)
            or openalex_overton_second_pat.match(filename)
            or altmetric_overton_second_pat.match(filename)
        ):
            continue

        try:
            df = pd.read_csv(os.path.join(output_directory, filename), dtype=str, encoding='utf-8-sig')
            df.columns = [normalize_col(c) for c in df.columns]

            if 'overton_id' in df.columns and 'policy_document_dois' in df.columns:
                df = df.dropna(subset=['overton_id', 'policy_document_dois'])
                for _, row in df.iterrows():
                    doi_map[normalize_id(row['overton_id'])] = normalize_id(row['policy_document_dois'])

            if 'first_order_overton_id' in df.columns and 'policy_document_dois' in df.columns:
                df = df.dropna(subset=['first_order_overton_id', 'policy_document_dois'])
                for _, row in df.iterrows():
                    doi_map[normalize_id(row['first_order_overton_id'])] = normalize_id(row['policy_document_dois'])

        except Exception as e:
            print(f"Error loading {filename} for DOI mapping: {e}")

    #  Replace Overton IDs with DOIs
    for filename in os.listdir(output_directory):
        if not (
            ov_first_order_pat.match(filename)
            or ov_second_order_pat.match(filename)
            or openalex_overton_second_pat.match(filename)
            or altmetric_overton_second_pat.match(filename)
        ):
            continue

        file_path = os.path.join(output_directory, filename)
        try:
            df = pd.read_csv(file_path, dtype=str, encoding='utf-8-sig')
            df.columns = [normalize_col(c) for c in df.columns]
            df = df.loc[:, ~df.columns.duplicated()]

            # Replace overton_id with DOI if mapped
            if 'overton_id' in df.columns:
                df['overton_id'] = df['overton_id'].map(normalize_id).map(doi_map).fillna(df['overton_id'])
                df.rename(columns={'overton_id': 'unique_identifier'}, inplace=True)

            # Only apply to Overton second-order files
            if ov_second_order_pat.match(filename) and 'first_order_overton_id' in df.columns:
                df['first_order_overton_id'] = df['first_order_overton_id'].map(normalize_id).map(doi_map).fillna(df['first_order_overton_id'])
                df.rename(columns={'first_order_overton_id': 'first_order_unique_identifier'}, inplace=True)

            # Drop policy_document_dois if present
            if 'policy_document_dois' in df.columns:
                df.drop(columns=['policy_document_dois'], inplace=True)

            # Add core_doi from filename if it's a first-order file
            if ov_first_order_pat.match(filename):
                core_doi = filename.split("_overton_first_order.csv")[0].replace("_", "/")
                df["core_doi"] = normalize_id(core_doi)
            
            # Drop any accidental .1 columns (e.g. from overwrite conflicts)
            first_order_cols = [col for col in df.columns if re.match(r'^first_order_doi(\.\d+)?$', col)]
            if len(first_order_cols) > 1:

                # Prefer the true 'first_order_doi' if it exists, else keep the first and rename it safely
                if 'first_order_doi' in first_order_cols:
                    cols_to_drop = [col for col in first_order_cols if col != 'first_order_doi']
                else:
                    # Rename the first to 'first_order_doi', drop the rest
                    df.rename(columns={first_order_cols[0]: 'first_order_doi'}, inplace=True)
                    cols_to_drop = first_order_cols[1:]
                df.drop(columns=cols_to_drop, inplace=True)
            
            df.to_csv(file_path, index=False, encoding='utf-8-sig')
            print(f"Replaced Overton IDs with DOIs: {filename}")

        except Exception as e:
            print(f"Could not process {filename}: {e}")

    print("\nOverton data cleanup complete.\n")


    # --- Create Compiled files ---
    for output_filename, match_fn in file_groups.items():
        matching_files = [
            f for f in os.listdir(output_directory)
            if f.endswith(".csv") and match_fn(f)
        ]

        if not matching_files:
            print(f"[SKIP] No matching files for: {output_filename}")
            continue

        compiled = []
        for fname in matching_files:
            fpath = os.path.join(output_directory, fname)
            try:
                df = pd.read_csv(fpath, dtype=str, encoding="utf-8-sig")
                compiled.append(df)
            except Exception as e:
                print(f"[ERROR] Could not read {fname}: {e}")

        if not compiled:
            print(f"[WARN] No valid data found for {output_filename}")
            continue

        compiled_df = pd.concat(compiled, ignore_index=True)

        # Normalize unique_identifier, but no deduplication
        if "unique_identifier" in compiled_df.columns:
            compiled_df["unique_identifier"] = compiled_df["unique_identifier"].map(normalize_id)

        out_path = os.path.join(output_directory, output_filename)
        try:
            compiled_df.to_csv(out_path, index=False, encoding='utf-8-sig')
            print(f"[OK] Saved {len(compiled_df)} rows → {output_filename}")
        except Exception as e:
            print(f"[ERROR] Failed to save {output_filename}: {e}")


if __name__ == "__main__":
    print("This script defines data cleaning functions.")
    print("Run them using main.py with --run data cleaning. Must occur after data collection is complete.")
    print("Alternatively, run as as part of data processing with python main.py --run data_processing")
