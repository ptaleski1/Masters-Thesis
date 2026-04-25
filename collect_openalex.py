
import pyalex
from pyalex import Works, Authors, Sources, Institutions, Topics, Publishers, Funders
import csv
import time
import requests
pyalex.config.email = #INSERT YOUR OPENALEX ACCOUNT EMAIL HERE
import re
import os
import pandas as pd
import sys
import utils
from utils import extract_plain_doi, init_output, clean


def extract_list(data, key):
    """
    Extract a semicolon-separated list of values from a list of dictionaries.
    """
    return "; ".join(str(item.get(key, "")) or "" for item in data)


def extract_nested(data, key1, key2):
    """
    Extract a semicolon-separated list of nested values from a list of dictionaries.
    """
    return "; ".join(str(item.get(key1, {}).get(key2, "")) or "" for item in data)

def get_citing_works(openalex_id):
    """Fetch all works that cite the given OpenAlex ID."""
    citing_works = []
    page = 1
    while True:
        url = f"https://api.openalex.org/works?filter=cites:{openalex_id}&per-page=200&page={page}"
        r = requests.get(url)
        if r.status_code != 200:
            break
        data = r.json()
        citing_works.extend(data.get("results", []))
        if not data.get("meta", {}).get("next_cursor"):
            break
        page += 1
        time.sleep(1.1)  # Rate limiting
    return citing_works

def get_openalex_id(doi):
    """Given a DOI, fetch the corresponding OpenAlex ID."""
    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    r = requests.get(url)
    if r.status_code == 200:
        return r.json().get("id", "").split("/")[-1]
    return None

header = [
    "id", "doi", "title", "publication_date", "type",
    "cited_by_api_url", "primary_topic.display_name", "primary_topic.subfield.display_name", "primary_topic.domain.display_name",
    "topics.display_name", "topics.field.display_name", "topics.domain.display_name",
    "keywords.display_name", "concepts.display_name", "mesh.descriptor_name", "mesh.qualifier_name"
]

openalex_ids = [
"W2158112812", "W2112170460", "W2782702360",
"W2043170430", "W2155996896"
]


def collect_openalex_first_order(source_dir="raw_data_collection"):
    """
    Fetch first-order citing works from OpenAlex, save metadata to CSVs,
    and write citing DOIs to a single file (no return).
    """

    os.makedirs(source_dir, exist_ok=True)

    all_citing_dois = set()

    for openalex_id in openalex_ids:
        per_page = 200
        cursor = "*"
        all_works = []
        filename = f"openalex_{openalex_id}_first_order.csv"

        while cursor:
            url = f"https://api.openalex.org/works?filter=cites:{openalex_id}&per-page={per_page}&cursor={cursor}"
            print(f"Fetching: {url}")
            response = requests.get(url)
            data = response.json()
            all_works.extend(data['results'])
            cursor = data.get('meta', {}).get('next_cursor')
            time.sleep(1)

        csv_file = os.path.join(source_dir, filename)
        with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(header)

            for work in all_works:
                ids = work.get("ids") or {}
                primary_topic = work.get("primary_topic") or {}
                topics = work.get("topics") or []
                keywords = work.get("keywords") or []
                concepts = work.get("concepts") or []
                mesh = work.get("mesh") or []

                writer.writerow([
                    work.get("id", ""),
                    work.get("doi", ""),
                    work.get("title", ""),
                    work.get("publication_date", ""),
                    work.get("type", ""),
                    work.get("cited_by_api_url", ""),
                    primary_topic.get("display_name", ""),
                    primary_topic.get("subfield", {}).get("display_name", ""),
                    primary_topic.get("domain", {}).get("display_name", ""),
                    extract_list(topics, "display_name"),
                    extract_nested(topics, "field", "display_name"),
                    extract_nested(topics, "domain", "display_name"),
                    extract_list(keywords, "display_name"),
                    extract_list(concepts, "display_name"),
                    extract_list(mesh, "descriptor_name"),
                    extract_list(mesh, "qualifier_name")
                ])

        print(f"Saved first-order results for {openalex_id} to {csv_file}")


def collect_openalex_second_order(source_dir="raw_data_collection"):
    """
    Extract second-order OpenAlex citations for each openalex_id in openalex_ids.
    For each first-order result file, fetch all works that cite them and save to *_second_order.csv.
    """
    os.makedirs(source_dir, exist_ok=True)

    for openalex_id in openalex_ids:
        print(f"\n Starting second-order extraction for {openalex_id}")

        first_order_path = os.path.join(source_dir, f"openalex_{openalex_id}_first_order.csv")
        second_order_path = os.path.join(source_dir, f"openalex_{openalex_id}_second_order.csv")

        second_order_ids = set()
        with open(first_order_path, newline='', encoding='utf-8-sig') as csvfile, \
            open(second_order_path, "w", newline="", encoding="utf-8-sig") as f2:

            reader = csv.DictReader(csvfile)
            writer = csv.writer(f2)
            writer.writerow(["cites_first_order_id"] + header)

            for row in reader:
                parent_id = row["id"]
                citing_url = row["cited_by_api_url"]
                if not citing_url:
                    continue

                print(f"Fetching 2nd-order from: {citing_url}")
                second_cursor = "*"

                while second_cursor:
                    try:
                        url2 = f"{citing_url}&per-page=200&cursor={second_cursor}"
                        response2 = requests.get(url2)
                        data2 = response2.json()
                        for citing_work in data2.get("results", []):
                            wid = citing_work.get("id")
                            if wid in second_order_ids:
                                continue
                            second_order_ids.add(wid)

                            ids = citing_work.get("ids") or {}
                            primary_topic = citing_work.get("primary_topic") or {}
                            topics = citing_work.get("topics") or []
                            keywords = citing_work.get("keywords") or []
                            concepts = citing_work.get("concepts") or []
                            mesh = citing_work.get("mesh") or []

                            writer.writerow([
                                parent_id
                            ] + [
                                citing_work.get("id", ""),
                                citing_work.get("doi", ""),
                                citing_work.get("title", ""),
                                citing_work.get("publication_date", ""),
                                citing_work.get("type", ""),
                                citing_work.get("cited_by_api_url", ""),
                                primary_topic.get("display_name", ""),
                                primary_topic.get("subfield", {}).get("display_name", ""),
                                primary_topic.get("domain", {}).get("display_name", ""),
                                extract_list(topics, "display_name"),
                                extract_nested(topics, "field", "display_name"),
                                extract_nested(topics, "domain", "display_name"),
                                extract_list(keywords, "display_name"),
                                extract_list(concepts, "display_name"),
                                extract_list(mesh, "descriptor_name"),
                                extract_list(mesh, "qualifier_name")
                            ])
                        second_cursor = data2.get('meta', {}).get('next_cursor')
                        time.sleep(1)
                    except Exception as e:
                        print(f"Error fetching second-order data for {parent_id}: {e}")
                        break

        print(f"Done: second-order saved to {second_order_path}")



def collect_openalex_second_order_ov_first_order(source_dir="raw_data_collection"):
    """From Overton first-order CSVs, pull OpenAlex citing sources for each policy DOI and append to a combined CSV."""
    
    output_file = os.path.join(source_dir, "combined_openalex_second_order_ov_first_order.csv")

    init_output(output_file, [
        "linked_to_doi", "source", "original_doi", "id", "doi", "title",
        "publication_date", "type", "cited_by_api_url", "primary_topic.display_name", "primary_topic.subfield.display_name",
        "primary_topic.domain.display_name", "topics.display_name", "topics.field.display_name",
        "topics.domain.display_name", "keywords.display_name", "concepts.display_name",
        "mesh.descriptor_name", "mesh.qualifier_name"
    ])

    for filename in os.listdir(source_dir):
        if not filename.endswith("_overton_first_order.csv"):
            continue

        linked_to_doi = filename.split("_")[0]
        filepath = os.path.join(source_dir, filename)

        with open(filepath, newline='', encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw = row.get("Policy Document DOIs") or row.get("policy_document_dois", "")
                if not raw:
                    continue

                for doi in raw.split(";"):
                    doi = doi.strip()
                    if not doi:
                        continue
                    try:
                        openalex_id = get_openalex_id(doi)
                        if openalex_id:
                            citing_works = get_citing_works(openalex_id)
                            with open(output_file, "a", newline="", encoding="utf-8-sig") as f_out:
                                writer = csv.writer(f_out, quotechar='"', quoting=csv.QUOTE_ALL)
                                for work in citing_works:
                                    writer.writerow([
                                        linked_to_doi, "openalex", doi,
                                        work.get("id", ""), work.get("doi", ""), clean(work.get("title", "")),
                                        work.get("publication_date", ""),
                                        work.get("type", ""),
                                        work.get("cited_by_api_url", ""),
                                        work.get("primary_topic", {}).get("display_name", ""),
                                        work.get("primary_topic", {}).get("subfield", {}).get("display_name", ""),
                                        work.get("primary_topic", {}).get("domain", {}).get("display_name", ""),
                                        "; ".join([t.get("display_name", "") for t in work.get("topics", []) if t.get("display_name")]),
                                        "; ".join([t.get("field", {}).get("display_name", "") for t in work.get("topics", []) if t.get("field")]),
                                        "; ".join([t.get("domain", {}).get("display_name", "") for t in work.get("topics", []) if t.get("domain")]),
                                        "; ".join([k.get("display_name", "") for k in work.get("keywords", [])]) if "keywords" in work else "",
                                        "; ".join([c.get("display_name", "") for c in work.get("concepts", []) if c.get("display_name")]),
                                        "; ".join([m.get("descriptor_name", "") for m in work.get("mesh", []) if m.get("descriptor_name")]) if "mesh" in work else "",
                                        "; ".join([m.get("qualifier_name", "") for m in work.get("mesh", []) if m.get("qualifier_name")]) if "mesh" in work else ""
                                    ])
                        print(f"[OpenAlex] Done: {doi}")
                    except Exception as e:
                        print(f"[OpenAlex] Error with DOI {doi}: {e}")
                    time.sleep(1.0)

if __name__ == "__main__":
    print("This script defines OpenAlex data collection functions.")
    print("Run them using main.py with --run, e.g.:")
    print("  python main.py --run openalex_first_order")