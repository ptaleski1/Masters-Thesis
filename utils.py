import unicodedata
import pandas as pd
import re
import os
import csv

def clean(text):
    """
    Clean text for CSV output for raw data files:
    - Normalize unicode characters
    - Replace line breaks and carriage returns
    - Strip leading/trailing whitespace
    """
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKC", text)
    return text.replace("\n", " ").replace("\r", " ").strip()


def extract_plain_doi(full_doi_url):
    """Extract DOI from a full URL or string."""
    match = re.search(r'10\.\d{4,9}/[\S]+', str(full_doi_url))
    return match.group(0) if match else None


def normalize_id(val):
    """Normalize identifier: lowercase, trim, remove BOM/DOI prefixes, strip trailing slash."""
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

def init_output(file_path, header):
    """Initialize CSV file with header if it doesn't already exist or is empty."""
    if not os.path.exists(file_path) or os.stat(file_path).st_size == 0:
        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, quotechar='"', quoting=csv.QUOTE_ALL)
            writer.writerow(header)