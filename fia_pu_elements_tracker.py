"""
FIA Formula 1 power-unit element tracker.

Dependencies:
    pip install requests beautifulsoup4 pypdf pandas tabulate

Notes:
- The FIA website's HTML and PDF text layout can change; review warnings when it does.
- The component-update rule below preserves the original script's behaviour:
  each parsed row in the "new elements" report increments that driver's component
  count by one. Confirm this interpretation against the specific FIA report format.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
# from tabulate import tabulate


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = (
    "https://www.fia.com/documents/championships/"
    "fia-formula-one-world-championship-14/season/season-2026-2072"
)
AJAX_URL = "https://www.fia.com/decision-document-list/ajax"
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = (10, 60)
REQUEST_PAUSE = 1.0  # seconds between downloads

# These repair known PDF text-extraction artefacts. Add new entries only when
# you have observed them in the extracted text.
TEXT_FIXES = {
    "Geor ge Russell": "George Russell",
    "Pierre Gasl y": "Pierre Gasly",
    "Isack Had": "Isack Hadjar",
    "Nico Hülkenber g": "Nico Hülkenberg",
    "Ser gio Perez": "Sergio Perez",
}

DRIVER_TO_TEAM = {
    "Max Verstappen": "Red Bull Racing",
    "Isack Hadjar": "Red Bull Racing",
    "Oscar Piastri": "McLaren",
    "Lando Norris": "McLaren",
    "Charles Leclerc": "Ferrari",
    "Lewis Hamilton": "Ferrari",
    "George Russell": "Mercedes",
    "Kimi Antonelli": "Mercedes",
    "Lance Stroll": "Aston Martin",
    "Fernando Alonso": "Aston Martin",
    "Pierre Gasly": "Alpine",
    "Franco Colapinto": "Alpine",
    "Esteban Ocon": "Haas F1 Team",
    "Oliver Bearman": "Haas F1 Team",
    "Arvid Lindblad": "Racing Bulls",
    "Liam Lawson": "Racing Bulls",
    "Yuki Tsunoda": "Racing Bulls",
    "Alexander Albon": "Williams",
    "Carlos Sainz": "Williams",
    "Nico Hülkenberg": "Audi",
    "Gabriel Bortoleto": "Audi",
    "Sergio Perez": "Cadillac",
    "Valtteri Bottas": "Cadillac",
}
# FastF1 three-letter codes, so the table can be merged on either name or code.
DRIVER_TO_ABBR = {
    "Max Verstappen": "VER", "Isack Hadjar": "HAD", "Oscar Piastri": "PIA",
    "Lando Norris": "NOR", "Charles Leclerc": "LEC", "Lewis Hamilton": "HAM",
    "George Russell": "RUS", "Kimi Antonelli": "ANT", "Lance Stroll": "STR",
    "Fernando Alonso": "ALO", "Pierre Gasly": "GAS", "Franco Colapinto": "COL",
    "Esteban Ocon": "OCO", "Oliver Bearman": "BEA", "Arvid Lindblad": "LIN",
    "Liam Lawson": "LAW", "Yuki Tsunoda": "TSU", "Alexander Albon": "ALB",
    "Carlos Sainz": "SAI", "Nico Hülkenberg": "HUL", "Gabriel Bortoleto": "BOR",
    "Sergio Perez": "PER", "Valtteri Bottas": "BOT",
}
DRIVER_NAMES = sorted(DRIVER_TO_TEAM, key=len, reverse=True)

# Map the component names used in the "new elements" report to output columns.
COMPONENT_COLUMNS = {
    "ICE": "ICE",
    "TC": "TC",
    "EXH": "EXH",
    "MGU-K": "MGU-K",
    "MGU-H": "MGU-H",
    "ES": "ES",
    "PU-CE": "CE",
    "PU-ANC": "ANC",
}
BASE_COLUMNS = ["Team", "Driver", "ICE", "TC", "EXH", "MGU-K", "ES", "CE", "ANC"]

# The PDF table contains position + driver/team text + seven component counts.
# Counts use \d+ rather than \d{1,2} to avoid assuming a fixed digit width.
COMPLETE_LINE_RE = re.compile(
    r"^\s*(\d{1,2})\s+(.+?)\s+"
    r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$"
)

# Document titles (as shown on the FIA site / in the PDF filename) of the two
# reports this script needs. All other documents are ignored and not downloaded.
USED_SO_FAR_TITLES = (
    "pu elements used per driver",
    "elements used so far",
    "used up to now",
)
NEW_ELEMENTS_TITLES = (
    "new pu elements",
    "new power unit elements",
)

PU_KEYWORDS = (
    "pu elements",
    "pu_elements",
    "pu-elements",
    "power unit",
    "power_unit",
    "power-unit",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger("fia_pu_tracker")


# ---------------------------------------------------------------------------
# HTTP and document discovery
# ---------------------------------------------------------------------------

def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def is_pdf_url(href: str | None) -> bool:
    if not href:
        return False
    return urlparse(href).path.lower().endswith(".pdf")


def looks_like_pu_report(text: str) -> bool:
    text = re.sub(r"[_-]+", " ", text.lower())
    return any(keyword.replace("_", " ") in text for keyword in PU_KEYWORDS)


def find_pdf_in_doc_page(doc_html: str, base_for_doc: str) -> str | None:
    """Return the first PDF link found on an FIA document page."""
    soup = BeautifulSoup(doc_html, "html.parser")

    # Prefer links whose surrounding text suggests a power-unit report.
    candidates = soup.find_all("a", href=True)
    for anchor in candidates:
        href = anchor["href"]
        context = " ".join(
            filter(
                None,
                [
                    anchor.get_text(" ", strip=True),
                    anchor.get("title", ""),
                    anchor.get("aria-label", ""),
                    href,
                ],
            )
        )
        if is_pdf_url(href) and looks_like_pu_report(context):
            return urljoin(base_for_doc, href)

    # Fallback for pages where the PDF filename itself is uninformative.
    for anchor in candidates:
        href = anchor["href"]
        if is_pdf_url(href):
            return urljoin(base_for_doc, href)

    for tag in soup.find_all(["meta", "link"]):
        href = tag.get("content") or tag.get("href")
        if href and is_pdf_url(href):
            return urljoin(base_for_doc, href)

    return None


def classify_report(text: str) -> str | None:
    """
    Classify a document from its title/link text as 'used_so_far' or
    'new_elements'.

    Only titles are used: the body of a "new elements" report contains
    "Previously used ICE" etc., so body text cannot tell the two apart.
    """
    haystack = re.sub(r"[_\-\s]+", " ", text.lower())

    if any(pattern in haystack for pattern in USED_SO_FAR_TITLES):
        return "used_so_far"
    if any(pattern in haystack for pattern in NEW_ELEMENTS_TITLES):
        return "new_elements"
    return None


def safe_filename(url: str) -> str:
    name = Path(urlparse(url).path).name
    return name if name else "fia_document.pdf"


def get_with_retry(
    session: requests.Session, url: str, attempts: int = 5
) -> requests.Response:
    """GET with backoff: the FIA site answers 429 when hit too quickly."""
    for attempt in range(attempts):
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code != 429 or attempt == attempts - 1:
            response.raise_for_status()
            return response
        retry_after = response.headers.get("Retry-After", "")
        delay = int(retry_after) if retry_after.isdigit() else 5 * 2**attempt
        logger.info("429 for %s; retrying in %ds", url, delay)
        time.sleep(delay)
    raise RuntimeError("unreachable")


def download_pdf(session: requests.Session, url: str) -> Path:
    """
    Download a PDF, validating its signature and avoiding partial files.

    FIA file names are unique per published revision, so an existing local
    copy is reused without contacting the site.
    """
    destination = DOWNLOAD_DIR / safe_filename(url)
    if destination.exists() and destination.read_bytes().startswith(b"%PDF-"):
        logger.info("Reused cached PDF %s", destination.name)
        return destination

    temporary = destination.with_suffix(destination.suffix + ".part")
    content = get_with_retry(session, url).content
    if not content.startswith(b"%PDF-"):
        raise ValueError(f"Response did not have a PDF signature: {url}")

    temporary.write_bytes(content)
    temporary.replace(destination)
    logger.info("Downloaded %s", destination.name)
    time.sleep(REQUEST_PAUSE)
    return destination


def discover_events(session: requests.Session) -> dict[str, str]:
    """
    Map each event name (one expander on the season page) to its document-list id.

    The first expander is rendered inline and the others are loaded by AJAX
    from /decision-document-list/ajax/<id>; the first one has no link, so its
    id is read from the "data-id-<id>" class of its list.
    """
    response = get_with_retry(session, BASE_URL)
    soup = BeautifulSoup(response.text, "html.parser")

    events: dict[str, str] = {}
    for wrapper in soup.select("ul.event-wrapper"):
        title = wrapper.select_one(".event-title")
        if title is None:
            continue
        name = title.get_text(" ", strip=True)

        doc_id = None
        match = re.search(r"/(\d+)$", title.get("href") or "")
        if match:
            doc_id = match.group(1)
        else:
            for tag in wrapper.find_all(class_=True):
                id_match = next(
                    (re.fullmatch(r"data-id-(\d+)", c) for c in tag["class"]
                     if c.startswith("data-id-")),
                    None,
                )
                if id_match:
                    doc_id = id_match.group(1)
                    break
        if doc_id:
            events[name] = doc_id
        else:
            logger.warning("No document-list id found for %s", name)

    logger.info("Found %d event(s) on the season page", len(events))
    return events


def fetch_event_html(session: requests.Session, doc_id: str) -> str:
    """Return the HTML of one event expander (loaded via Drupal AJAX)."""
    response = get_with_retry(session, f"{AJAX_URL}/{doc_id}")
    time.sleep(REQUEST_PAUSE)
    return "".join(
        command["data"] for command in response.json()
        if isinstance(command.get("data"), str)
    )


def discover_report_links(html: str) -> list[tuple[str, str, int]]:
    """
    Find the PU report links in one event's HTML.

    Returns (url, report_type, doc_number) tuples, classified from the link
    text so that unrelated documents are never downloaded.
    """
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, tuple[str, int]] = {}

    for anchor in soup.find_all("a", href=True):
        href = urljoin(BASE_URL, anchor["href"])
        if not is_pdf_url(href):
            continue

        label = anchor.get_text(" ", strip=True)
        report_type = classify_report(f"{label} {anchor.get('title', '')}")
        if report_type:
            doc = re.search(r"Doc\s+(\d+)", label)
            found[href] = (report_type, int(doc.group(1)) if doc else 0)

    return [(url, kind, doc) for url, (kind, doc) in found.items()]


def collect_report_pdfs(
    session: requests.Session, links: list[tuple[str, str, int]]
) -> dict[str, list[Path]]:
    """Download one event's PU reports, grouped by type (latest doc first)."""
    reports: dict[str, list[Path]] = {"used_so_far": [], "new_elements": []}

    # A missing report would silently give wrong counts, so errors propagate
    # and the whole event is skipped by main().
    for url, report_type, _ in sorted(links, key=lambda x: -x[2]):
        pdf_path = download_pdf(session, url)
        if pdf_path not in reports[report_type]:
            reports[report_type].append(pdf_path)

    return reports


# ---------------------------------------------------------------------------
# PDF text extraction and parsing
# ---------------------------------------------------------------------------

def extract_text_from_pdf(path: str | Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def apply_text_fixes(text: str) -> str:
    # Only replace whole words, so e.g. "Isack Had" doesn't turn an already
    # correct "Isack Hadjar" into "Isack Hadjarjar".
    for bad, good in TEXT_FIXES.items():
        text = re.sub(re.escape(bad) + r"(?!\w)", good, text)
    return text


def normalise_pdf_text(text: str) -> str:
    """Apply known text fixes and normalise whitespace."""
    return apply_text_fixes(text).replace("\u00a0", " ")


def format_text_for_table(text: str) -> list[str]:
    """Find driver data rows, merging rows split across PDF text lines."""
    cleaned = [
        re.sub(r"\s+", " ", line).strip()
        for line in normalise_pdf_text(text).splitlines()
        if line.strip()
    ]

    result: list[str] = []
    i = 0

    while i < len(cleaned):
        line = cleaned[i]
        if COMPLETE_LINE_RE.fullmatch(line):
            result.append(line)
            i += 1
            continue

        merged = line
        found = False

        # A PDF extractor may split a row over several physical lines.
        for j in range(i + 1, min(i + 4, len(cleaned))):
            if COMPLETE_LINE_RE.fullmatch(cleaned[j]):
                break

            merged = f"{merged} {cleaned[j]}"
            if COMPLETE_LINE_RE.fullmatch(merged):
                result.append(merged)
                i = j + 1
                found = True
                break

        if not found:
            i += 1

    return result


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def extract_driver_name(team_driver: str) -> str | None:
    """Find a known driver name, rather than guessing from capitalisation."""
    normalised = apply_text_fixes(re.sub(r"\s+", " ", team_driver).strip())

    # PDF text can occasionally split a name with spaces inside a word.
    compact = strip_accents(normalised)
    for name in DRIVER_NAMES:
        # Match the known name with flexible whitespace between words.
        pattern = r"(?<!\w)" + r"\s+".join(
            re.escape(strip_accents(part)) for part in name.split()
        ) + r"(?!\w)"
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            # Return the canonical spelling from the mapping.
            return name

    # Handle the observed "Russell" artefact without treating any surname as
    # uniquely identifying unless it belongs to exactly one known driver.
    surname_matches = [
        name for name in DRIVER_NAMES
        if strip_accents(name.split()[-1]).casefold()
        == strip_accents(normalised).casefold()
    ]
    if len(surname_matches) == 1:
        return surname_matches[0]

    return None


def parse_used_so_far_pdf(path: str | Path) -> tuple[pd.DataFrame, str]:
    """Parse the used-so-far report into a base DataFrame and return its text."""
    text = extract_text_from_pdf(path)
    lines = format_text_for_table(text)
    rows = []
    errors = []

    for line in lines:
        match = COMPLETE_LINE_RE.fullmatch(line)
        if not match:
            errors.append(f"Could not parse row: {line}")
            continue

        team_driver = match.group(2).strip()
        driver = extract_driver_name(team_driver)
        if driver is None:
            errors.append(f"Could not identify driver in row: {line}")
            continue

        counts = [int(match.group(i)) for i in range(3, 10)]
        rows.append([DRIVER_TO_TEAM[driver], driver, *counts])

    if errors:
        logger.warning("%d row(s) could not be parsed:", len(errors))
        for error in errors:
            logger.warning("  %s", error)

    if not rows:
        raise ValueError(
            f"No driver rows parsed from {path}. Check the PDF text/layout."
        )

    df = pd.DataFrame(rows, columns=BASE_COLUMNS)

    duplicates = df[df["Driver"].duplicated(keep=False)]
    if not duplicates.empty:
        raise ValueError(
            "Duplicate driver rows detected in used-so-far report: "
            + ", ".join(duplicates["Driver"].tolist())
        )

    return df, text


def parse_new_pu_elements(text: str) -> list[dict]:
    """Parse component-use entries from a 'new elements' report."""
    text = normalise_pdf_text(text)
    lines = [re.sub(r"\s+", " ", line).strip()
             for line in text.splitlines() if line.strip()]

    header_to_component = {
        "previously used ice": "ICE",
        "previously used tc": "TC",
        "previously used exh": "EXH",
        "previously used mgu-k": "MGU-K",
        "previously used es": "ES",
        "previously used pu-ce": "PU-CE",
    }

    def detect_component(line: str) -> str | None:
        lower = line.casefold()
        for header, component in header_to_component.items():
            if header in lower:
                return component
        if "pu-anc" in lower:
            return "PU-ANC"
        return None

    updates: list[dict] = []
    i = 0

    while i < len(lines):
        component = detect_component(lines[i])
        if component is None:
            i += 1
            continue

        j = i + 1
        while j < len(lines):
            row = lines[j]
            lower = row.casefold()

            # A new section begins when another component header is encountered.
            next_component = detect_component(row)
            if next_component is not None:
                break
            if lower.startswith("the following"):
                break

            tokens = row.split()
            if len(tokens) >= 3:
                try:
                    previous = int(tokens[-1])
                except ValueError:
                    previous = None

                driver = extract_driver_name(row)
                if previous is not None and driver is not None:
                    updates.append({
                        "Driver": driver,
                        "Component": component,
                        "Previous": previous,
                    })

            j += 1

        i = max(j, i + 1)

    return updates


# ---------------------------------------------------------------------------
# Reconciliation and output
# ---------------------------------------------------------------------------

def apply_pu_updates(df_base: pd.DataFrame, updates: list[dict]) -> pd.DataFrame:
    """
    Apply component updates.

    This preserves the original script's increment-by-one rule. The 'Previous'
    field is retained for diagnostics but is not treated as the new count.
    Confirm this rule against the precise FIA report semantics before relying
    on the resulting totals.
    """
    df = df_base.copy()

    if "ANC" not in df.columns:
        df["ANC"] = 0

    for update in updates:
        driver = update["Driver"]
        component = update["Component"]

        if component not in COMPONENT_COLUMNS:
            raise ValueError(f"Unknown component {component!r} for {driver}")

        column = COMPONENT_COLUMNS[component]
        mask = df["Driver"].eq(driver)

        if int(mask.sum()) != 1:
            raise ValueError(
                f"Expected exactly one base row for {driver}; found {int(mask.sum())}"
            )

        df.loc[mask, column] = int(df.loc[mask, column].iloc[0]) + 1

        logger.info(
            "Incremented %s for %s (report Previous=%s)",
            column,
            driver,
            update.get("Previous"),
        )

    return df


def choose_report(paths: list[Path], report_type: str) -> Path:
    """
    Choose a report deterministically.

    If multiple candidate reports exist, prefer the most recently modified
    local file. Inspect the logged selection if FIA publishes multiple versions.
    """
    if not paths:
        raise FileNotFoundError(
            f"No {report_type!r} PDF found. Check FIA links and report keywords."
        )
    unique_paths = list(dict.fromkeys(paths))
    selected = max(unique_paths, key=lambda p: p.stat().st_mtime)
    if len(unique_paths) > 1:
        logger.warning(
            "Found %d %s candidates; selected %s. Check that this is the correct report.",
            len(unique_paths), report_type, selected.name
        )
    return selected


def build_event_table(
    event: str, used_path: Path | None, new_paths: list[Path]
) -> pd.DataFrame:
    """Elements used per driver and type as of the end of one event."""
    if used_path is not None:
        logger.info("[%s] used-so-far report: %s", event, used_path.name)
        df_base, _ = parse_used_so_far_pdf(used_path)
    else:
        # First event of the season: every driver starts with one new element
        # of each type ("All drivers will start the first Competition ... with
        # new PU elements").
        logger.info("[%s] no used-so-far report; starting from one of each", event)
        df_base = pd.DataFrame(
            [[team, driver, *[1] * 7] for driver, team in DRIVER_TO_TEAM.items()],
            columns=BASE_COLUMNS,
        )

    updates: list[dict] = []
    for path in new_paths:
        logger.info("[%s] parsing new-element report: %s", event, path.name)
        updates.extend(parse_new_pu_elements(extract_text_from_pdf(path)))
    logger.info("[%s] parsed %d component update(s)", event, len(updates))

    df = apply_pu_updates(df_base, updates)
    df.insert(0, "Event", event)
    df.insert(3, "Abbreviation", df["Driver"].map(DRIVER_TO_ABBR))
    return df


def main() -> pd.DataFrame:
    """
    Build one table for the whole season: one row per (Event, Driver) with the
    cumulative number of elements used of each type at that event.

    Merge it with other tables on ["Event", "Driver"] (full name) or
    ["Event", "Abbreviation"]. Event matches FastF1's EventName.
    """
    session = make_session()
    tables: list[pd.DataFrame] = []

    for event, doc_id in discover_events(session).items():
        try:
            links = discover_report_links(fetch_event_html(session, doc_id))
            if not links:
                logger.info("[%s] no PU reports published yet", event)
                continue

            reports = collect_report_pdfs(session, links)
            used = reports["used_so_far"][0] if reports["used_so_far"] else None
            tables.append(build_event_table(event, used, reports["new_elements"]))
        except Exception:
            logger.exception("[%s] failed; skipping event", event)

    if not tables:
        raise RuntimeError("No PU element tables could be built.")

    # Calendar order: the site lists the latest event first.
    df_season = pd.concat(tables[::-1], ignore_index=True)

    # The first event is built from the full driver map, which may contain
    # drivers who never raced; keep only drivers seen in a real report.
    first_event = tables[-1]["Event"].iloc[0]
    reported = set(df_season.loc[df_season["Event"] != first_event, "Driver"])
    df_season = df_season[
        (df_season["Event"] != first_event) | df_season["Driver"].isin(reported)
    ].reset_index(drop=True)

    if df_season.duplicated(["Event", "Driver"]).any():
        raise ValueError("Duplicate (Event, Driver) rows in season table")
        
    return df_season


def get_pu_season_table() -> pd.DataFrame:
    """
    Cumulative PU element usage for every (Event, Driver) in calendar order.

    Columns the FIA reports do not track (e.g. MGU-H) are returned as NaN so
    callers can select them.
    """
    df_season = main()
    columns = ["Event", "Driver", "Abbreviation", "Team", "ICE", "TC", "MGU-H", "MGU-K", "ES", "CE"]
    return df_season.reindex(columns=columns).reset_index(drop=True)


if __name__ == "__main__":
    print(main().to_string(index=False))
