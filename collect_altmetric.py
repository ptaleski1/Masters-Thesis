
from pyaltmetric import Altmetric
import requests
import csv
import hashlib
import pandas as pd
import os
import time
import unicodedata
from urllib.parse import quote
import re
import pyalex
from pyalex import Works, Authors, Sources, Institutions, Topics, Publishers, Funders
pyalex.config.email = #INSERT YOUR OPENALEX ACCOUNT EMAIL HERE
from time import sleep
import utils
from utils import clean, init_output
import sys


API_KEY = #INSERT YOUR ALTMETRIC DETAILS API KEY HERE
wanted_sources = ["blogs", "video", "news", "policy", "guideline", "patent", "wikipedia"]

def collect_altmetric_first_order(source_dir="raw_data_collection"):
    """Fetch Altmetric first-order mentions for a DOI list and save per-ID CSVs."""

    os.makedirs(source_dir, exist_ok=True)
    dois = [
    "10.1126/science.1213362", "10.1038/nature10831",
    "10.1126/science.1072266", "10.1128/JVI.75.3.1205-1210.2001",
    "10.1371/journal.pone.0188453"
    ]
    
    for doi in dois:
        url = f"https://api.altmetric.com/v1/fetch/doi/{doi}?key={API_KEY}"
        print(f"Fetching Altmetric ID for: {doi}")
        response = requests.get(url)

        if response.status_code != 200:
            print(f"Failed: {response.status_code}")
            continue

        altmetric_id = response.json().get("altmetric_id")
        if not altmetric_id:
            continue

        detail_url = f"https://api.altmetric.com/v1/fetch/id/{altmetric_id}?key={API_KEY}"
        detail_response = requests.get(detail_url)
        posts = detail_response.json().get("posts", {})

        output_file = os.path.join(source_dir, f"altmetric_{altmetric_id}_first_order_mentions.csv")
        with open(output_file, "w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.writer(csvfile, quotechar='"', quoting=csv.QUOTE_ALL)
            writer.writerow(["altmetric_id", "doi", "source_type", "title", "url", "posted_on",
                             "summary"])

            for source_type in wanted_sources:
                for mention in posts.get(source_type, []):
                    writer.writerow([
                        altmetric_id, doi, source_type,
                        clean(mention.get("title", "")), clean(mention.get("url", "")),
                        mention.get("posted_on", ""), clean(mention.get("summary", ""))
                    ])
        print(f"Saved Altmetric data to: {output_file}")



def collect_altmetric_second_order_oa_first_order(source_dir="raw_data_collection"):
    """From OpenAlex first-order CSVs, find DOIs and fetch Altmetric second-order mentions."""

    # Loop through all relevant OpenAlex first-order files
    for filename in os.listdir(source_dir):
        if not filename.startswith("openalex_") or not filename.endswith("_first_order.csv"):
            continue  

        # Extract OpenAlex ID from filename
        openalex_id = filename.split("_")[1]
        filepath = os.path.join(source_dir, filename)

        # Load the CSV file and extract any DOIs found in the cells
        with open(filepath, newline='', encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = list(reader)

        dois = set()
        for row in rows:
            for cell in row:
                if "doi.org/" in cell:
                    doi = cell.strip().split("doi.org/")[-1]
                    dois.add(doi)

        # Process each DOI to retrieve Altmetric second-order data
        for doi in dois:
            url = f"https://api.altmetric.com/v1/fetch/doi/{doi}?key={API_KEY}"
            response = requests.get(url)
            if response.status_code != 200:
                continue  

            try:
                data = response.json()
                altmetric_id = data.get("altmetric_id")
                if not altmetric_id:
                    continue  
            except:
                continue  

            # Fetch detailed post data using the Altmetric ID
            detail_url = f"https://api.altmetric.com/v1/fetch/id/{altmetric_id}?key={API_KEY}"
            detail_response = requests.get(detail_url)
            if detail_response.status_code != 200:
                continue  

            try:
                details = detail_response.json()
                posts_raw = details.get("posts", {})

                # Ensure posts are in dictionary format. If not, assign to 'unknown'
                if isinstance(posts_raw, dict):
                    posts = posts_raw
                elif isinstance(posts_raw, list):
                    posts = {"unknown": posts_raw}
                else:
                    posts = {}

                # Prepare output CSV file
                output_file = os.path.join(
                    source_dir,
                    f"openalex_{openalex_id}_altmetric_second_order.csv"
                )

                with open(output_file, "a", newline="", encoding="utf-8-sig") as csvfile:
                    writer = csv.writer(csvfile, quotechar='"', quoting=csv.QUOTE_ALL)

                    # Write header if file is empty
                    if os.stat(output_file).st_size == 0:
                        writer.writerow([
                            "original_doi", "altmetric_id", "source_type", "title", "url", "posted_on",
                            "summary"
                        ])

                    # Loop through wanted source types plus fallback "unknown"
                    for source_type in wanted_sources + ["unknown"]:
                        for mention in posts.get(source_type, []):
                            writer.writerow([
                                doi,
                                altmetric_id,
                                source_type,
                                clean(mention.get("title", "")),
                                clean(mention.get("url", "")),
                                mention.get("posted_on", ""),
                                clean(mention.get("summary", ""))
                            ])
            except Exception as e:
                print(f"Error processing second-order data for DOI {doi}: {e}")



def collect_altmetric_second_order_ov_first_order(source_dir="raw_data_collection"):
    """From Overton first-order CSVs, fetch Altmetric second-order mentions and append to a combined CSV."""

    output_file = os.path.join(source_dir, "combined_altmetric_second_order_ov_first_order.csv")

    init_output(output_file, [
        "linked_to_doi", "source", "original_doi", "altmetric_id", "source_type",
        "title", "url", "posted_on", "summary"
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
                        alt_url = f"https://api.altmetric.com/v1/fetch/doi/{doi}?key={API_KEY}"
                        r = requests.get(alt_url)
                        if r.status_code != 200:
                            continue

                        data = r.json()
                        altmetric_id = data.get("altmetric_id")
                        if not altmetric_id:
                            continue

                        detail_url = f"https://api.altmetric.com/v1/fetch/id/{altmetric_id}?key={API_KEY}"
                        detail_response = requests.get(detail_url)
                        if detail_response.status_code != 200:
                            continue

                        details = detail_response.json()
                        posts = details.get("posts", {})
                        if not isinstance(posts, dict):
                            continue
                        with open(output_file, "a", newline="", encoding="utf-8-sig") as f_out:
                            writer = csv.writer(f_out, quotechar='"', quoting=csv.QUOTE_ALL)
                            for source_type in wanted_sources:
                                mentions = posts.get(source_type, [])
                                for mention in mentions:
                                    writer.writerow([
                                        linked_to_doi, "altmetric", doi, altmetric_id,
                                        source_type,
                                        clean(mention.get("title", "")),
                                        clean(mention.get("url", "")),
                                        mention.get("posted_on", ""),
                                        clean(mention.get("summary", ""))
                                    ])
                        print(f"[Altmetric] Done: {doi}")
                    except Exception as e:
                        print(f"[Altmetric] Error with DOI {doi}: {e}")

                    time.sleep(1.0)
               

if __name__ == "__main__":
    print("This script defines Altmetric data collection functions.")
    print("Run them using main.py with --run, e.g.:")
    print("  python main.py --run altmetric_first_order")