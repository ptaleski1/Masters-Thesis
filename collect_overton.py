import requests
import pandas as pd
import os
import re
import time
import sys
import utils
from utils import extract_plain_doi
import pyalex
from pyalex import Works, Authors, Sources, Institutions, Topics, Publishers, Funders
pyalex.config.email = #INSERT YOUR OPENALEX ACCOUNT EMAIL HERE


def get_openalex_doi(title):
    """
    Query OpenAlex by title to get the corresponding DOI.
    """
    url = f"https://api.openalex.org/works?filter=title.search:{title}"
    try:
        response = requests.get(url)
        data = response.json()
        target_title = title.lower()
        for result in data.get("results", []):
            if result["title"].lower() == target_title:
                return result.get("doi")
    except Exception as e:
        print(f"OpenAlex error for title '{title}': {e}")
    return None

API_KEY = #INSERT YOUR OVERTON API KEY HERE



def collect_overton_first_order(output_dir="raw_data_collection"):
    """
    Queries Overton for each to get first-order citing policy documents.
    Saves each result to a file named like {doi}_overton_first_order.csv.
    """
    os.makedirs(output_dir, exist_ok=True)

    dois = [
        "10.1126/science.1213362", "10.1038/nature10831",
        "10.1126/science.1072266", "10.1128/jvi.75.3.1205-1210.2001",
        "10.1371/journal.pone.0188453"
    ]

    for doi in dois:
        print(f"Searching for policy documents that cite DOI: {doi}...")

        results = []

        params = {
            "plain_dois_cited": doi,
            "format": "json",
            "api_key": API_KEY,
            "show_search_facets": "true",
        }

        response = requests.get("https://app.overton.io/documents.php", params=params)
        if response.status_code != 200:
            raise Exception(f"Request failed: {response.status_code} - {response.text}")

        data = response.json()
        results.extend(data.get("results", []))
        next_page_url = data.get("query", {}).get("next_page_url")

        # Fetch all additional pages
        while next_page_url:
            time.sleep(1.0)  # rate lmiits with calling API
            next_response = requests.get(next_page_url)
            if next_response.status_code != 200:
                print(f"Failed to fetch next page: {next_response.status_code}")
                break
            data = next_response.json()
            results.extend(data.get("results", []))
            next_page_url = data.get("query", {}).get("next_page_url")

        print(f"Found {len(results)} citing policy documents.")

        # Extract fields into structured rows
        records = []

        for item in results:
            source = item.get("source", {})
            record = {
                "Overton id": item.get("policy_document_id"),
                "Title": item.get("title"),
                "Translated title": item.get("translated_title"),
                "Document type": item.get("overton_policy_document_series"),
                "Published_on": item.get("published_on"),
                "Document URL": item.get("document_url"),
                "Source specific tags": ", ".join(item.get("source_tags", [])) or None,
                "Top topics": ", ".join(item.get("topics", [])[:3]) if item.get("topics") else None,
                "Languages": ", ".join(item.get("languages", [])) or None,
                "Document theme": ", ".join(item.get("classifications", [])) or None,
                "Policy Document DOIs": next((oid for oid in item.get("other_identifiers", []) if oid.startswith("10.")), None)
            }
            records.append(record)

        # Clean DOI for filename
        safe_doi = doi.strip().replace("/", "_", 1)
        output_file = os.path.join(output_dir, f"{safe_doi}_overton_first_order.csv")

        try:
            df = pd.DataFrame(records)
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
        except Exception as e:
            print(f"Error writing file for {doi}: {e}")

def collect_overton_second_order(source_dir="raw_data_collection"):
    """
    For each Overton first-order file, fetch all policy documents that cite those policy documents
    (i.e. second-order), and save to a file named like {doi}_overton_second_order.csv.
    """
    os.makedirs(source_dir, exist_ok=True)

    for filename in os.listdir(source_dir):
        if not filename.endswith("_overton_first_order.csv"):
            continue

        print(f"\nProcessing second-order for: {filename}")
        doi_part = filename.replace("_overton_first_order.csv", "")
        input_path = os.path.join(source_dir, filename)
        output_path = os.path.join(source_dir, f"{doi_part}_overton_second_order.csv")

        try:
            df = pd.read_csv(input_path, encoding='utf-8-sig')
        except Exception as e:
            print(f"Failed to read {input_path}: {e}")
            continue

        overton_ids = df["Overton id"].dropna().astype(str).unique()
        all_records = []

        for oid in overton_ids:
            print(f"Fetching citing documents for Overton ID: {oid}")
            results = []

            params = {
                "cites_policy_document_id": oid,
                "format": "json",
                "api_key": API_KEY,
                "show_search_facets": "false"
            }

            response = requests.get("https://app.overton.io/documents.php", params=params)
            if response.status_code != 200:
                print(f"Request failed for ID {oid}: {response.status_code}")
                continue
            
            time.sleep(1.0)

            data = response.json()
            results.extend(data.get("results", []))
            next_page_url = data.get("query", {}).get("next_page_url")

            while next_page_url:
                time.sleep(1.0)
                next_response = requests.get(next_page_url)
                if next_response.status_code != 200:
                    print(f"Failed to fetch next page: {next_response.status_code}")
                    break
                data = next_response.json()
                results.extend(data.get("results", []))
                next_page_url = data.get("query", {}).get("next_page_url")

            for item in results:
                source = item.get("source", {})
                record = {
                    "Overton id": item.get("policy_document_id"),
                    "Title": item.get("title"),
                    "Translated title": item.get("translated_title"),
                    "Document type": item.get("overton_policy_document_series"),
                    "Published_on": item.get("published_on"),
                    "Document URL": item.get("document_url"),
                    "Source specific tags": ", ".join(item.get("source_tags", []) or []),
                    "Top topics": ", ".join(item.get("topics", [])[:3]) if item.get("topics") else None,
                    "Languages": ", ".join(item.get("languages", [])) or None,
                    "Document theme": ", ".join(item.get("classifications", []) or []),
                    "Cited Overton ID": oid,
                    "Policy Document DOIs": next((oid for oid in item.get("other_identifiers", []) if oid.startswith("10.")), None)
                }
                all_records.append(record)

        try:
            pd.DataFrame(all_records).to_csv(output_path, index=False, encoding='utf-8-sig')
            print(f"Saved {len(all_records)} second-order records to: {output_path}")
        except Exception as e:
            print(f"Failed to write output for {doi_part}: {e}")



# Second-order Overton source extraction from first-order OpenAlex sources

def collect_overton_second_order_oa_first_order(source_dir="raw_data_collection"):

    """For each OpenAlex first-order CSV, query Overton for citing policy docs and save a second-order CSV."""

    search_url = 'https://app.overton.io/documents.php'
    
    for filename in os.listdir(source_dir):
        if filename.startswith("openalex_") and filename.endswith("_first_order.csv"):
            openalex_id = filename.split("_")[1]
            input_path = os.path.join(source_dir, filename)
            df_input = pd.read_csv(input_path)

            dois = df_input["doi"].dropna().apply(extract_plain_doi).dropna().unique()
            print(f"\nProcessing {len(dois)} DOIs from {filename}...")

            records = []

            for doi in dois:
                start = time.time()
                params = {
                    "plain_dois_cited": doi,
                    "format": "json",
                    "api_key": API_KEY,
                    "show_search_facets": "true",
                }

                retries = 3
                for attempt in range(retries):
                    response = requests.get(search_url, params=params)
                    if response.status_code == 200:
                        break
                    elif response.status_code == 429:
                        print("Rate limit hit, waiting 60 seconds...")
                        time.sleep(60)
                    else:
                        print(f"Request failed (status {response.status_code})")
                        response = None
                        break

                if response is None or response.status_code != 200:
                    continue

                try:
                    # Fetch all pages of results
                    results = []
                    data = response.json()
                    results.extend(data.get("results", []))
                    next_page_url = data.get("query", {}).get("next_page_url")

                    while next_page_url:
                        time.sleep(1.0)
                        next_response = requests.get(next_page_url)
                        if next_response.status_code != 200:
                            print(f"Failed to fetch next page: {next_response.status_code}")
                            break
                        data = next_response.json()
                        results.extend(data.get("results", []))
                        next_page_url = data.get("query", {}).get("next_page_url")

                    # --- Extract structured fields ---
                    for item in results:
                        source = item.get("source", {})
                        record = {
                            "first_order_doi": doi,
                            "Overton id": item.get("policy_document_id"),
                            "Title": item.get("title"),
                            "Translated title": item.get("translated_title"),
                            "Document type": item.get("overton_policy_document_series"),
                            "Published_on": item.get("published_on"),
                            "Document URL": item.get("document_url"),
                            "Source specific tags": ", ".join(item.get("source_tags", [])) or None,
                            "Top topics": ", ".join(item.get("topics", [])[:3]) if item.get("topics") else None,
                            "Languages": ", ".join(item.get("languages", [])) or None,
                            "Document theme": ", ".join(item.get("classifications", [])) or None,
                            "Policy Document DOIs": next((oid for oid in item.get("other_identifiers", []) if oid.startswith("10.")), None)
                        }
                        records.append(record)

                except Exception as e:
                    print(f"Error parsing response for DOI {doi}: {e}")

                print(f"Processed {doi} in {time.time() - start:.2f}s")
                time.sleep(1.0)

            # Save results
            df_out = pd.DataFrame(records)
            output_filename = f"openalex_{openalex_id}_overton_second_order.csv"
            output_path = os.path.join(source_dir, output_filename)
            df_out.to_csv(output_path, index=False, encoding='utf-8-sig')
            print(f"Saved {len(df_out)} records to {output_filename}")



def collect_overton_second_order_alt_first_order(source_dir="raw_data_collection"):

    """Match Altmetric policy/patent titles to DOIs via OpenAlex, query Overton, and save second-order CSVs."""

    search_url = 'https://app.overton.io/documents.php'
    results_summary = []

    for filename in os.listdir(source_dir):
        match = re.match(r"altmetric_([a-z0-9]+)_first_order_mentions(?:\.csv)?", filename, re.IGNORECASE)
        if not match:
            continue

        altmetric_id = match.group(1)
        filepath = os.path.join(source_dir, filename)
        print(f"\nProcessing file: {filename}")

        try:
            df = pd.read_csv(filepath)
        except Exception as e:
            print(f"Failed to read {filename}: {e}")
            continue

        if "source_type" not in df.columns or "title" not in df.columns:
            print(f"Missing expected columns in {filename}")
            continue

        # Normalize title for reliable matching
        df_filtered = df[df["source_type"].isin(["policy", "patent"])].copy()

        # Match DOIs via OpenAlex
        dois = []
        for title in df_filtered["title"]:
            doi = get_openalex_doi(title)
            dois.append(doi)

        df_filtered["first_order_doi"] = dois

        # Merge matched DOIs back into the original DataFrame
        df_updated = df.merge(df_filtered[["title", "first_order_doi"]], on="title", how="left")

        output_path = os.path.join(source_dir, filename)
        df_updated.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"Updated and saved DOIs to {output_path}")

        # Get unique DOIs for Overton search 
        matched_dois = df_filtered["first_order_doi"].dropna().apply(extract_plain_doi).dropna().unique()
    
        # Query Overton for each DOI
        records = []

        for doi in matched_dois:
            start = time.time()
            params = {
                "plain_dois_cited": doi,
                "format": "json",
                "api_key": API_KEY,
                "show_search_facets": "true",
            }

            retries = 3
            for attempt in range(retries):
                response = requests.get(search_url, params=params)
                if response.status_code == 200:
                    break
                elif response.status_code == 429:
                    print("Rate limit hit, waiting 60 seconds...")
                    time.sleep(60)
                else:
                    print(f"Request failed (status {response.status_code})")
                    response = None
                    break

            if response is None or response.status_code != 200:
                continue

            try:
                # Fetch all pages of results 
                results = []
                data = response.json()
                results.extend(data.get("results", []))
                next_page_url = data.get("query", {}).get("next_page_url")

                while next_page_url:
                    time.sleep(1.0)
                    next_response = requests.get(next_page_url)
                    if next_response.status_code != 200:
                        print(f"Failed to fetch next page: {next_response.status_code}")
                        break
                    data = next_response.json()
                    results.extend(data.get("results", []))
                    next_page_url = data.get("query", {}).get("next_page_url")

                # Extract structured fields 
                for item in results:
                    source = item.get("source", {})
                    record = {
                        "first_order_doi": doi,
                        "Overton id": item.get("policy_document_id"),
                        "Title": item.get("title"),
                        "Translated title": item.get("translated_title"),
                        "Document type": item.get("overton_policy_document_series"),
                        "Published_on": item.get("published_on"),
                        "Document URL": item.get("document_url"),
                        "Source specific tags": ", ".join(item.get("source_tags", [])) or None,
                        "Top topics": ", ".join(item.get("topics", [])[:3]) if item.get("topics") else None,
                        "Languages": ", ".join(item.get("languages", [])) or None,
                        "Document theme": ", ".join(item.get("classifications", [])) or None,
                        "Policy Document DOIs": next((oid for oid in item.get("other_identifiers", []) if oid.startswith("10.")), None)
                    }
                    records.append(record)

            except Exception as e:
                print(f"Error parsing response for DOI {doi}: {e}")

            print(f"Processed {doi} in {time.time() - start:.2f}s")
            time.sleep(1.0)

        # Save to csv
        df_out = pd.DataFrame(records)
        overton_output = os.path.join(source_dir, f"altmetric_{altmetric_id}_overton_second_order.csv")
        df_out.to_csv(overton_output, index=False, encoding="utf-8-sig")
        print(f"Saved {len(df_out)} records to {overton_output}")


if __name__ == "__main__":
    print("This script defines Overton data collection functions.")
    print("Run them using main.py with --run, e.g.:")
    print("  python main.py --run overton_first_order")