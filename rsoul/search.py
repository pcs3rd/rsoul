import time
import logging
import os
import math
from typing import Any, Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Context

from .display import print_search_summary
from .utils import get_current_page, update_current_page
from .types import Book

logger = logging.getLogger(__name__)


def generate_fallback_queries(author_name: str, book_title: str, max_fallbacks: int) -> List[str]:
    """Generate progressively degraded search queries for blocked word workaround.

    Strategy:
    1. First name + full title
    2. First name + title with word 0 dropped
    3. First name + title with word 1 dropped
    ...continues left-to-right until max_fallbacks reached

    Args:
        author_name: Full author name
        book_title: Full book title
        max_fallbacks: Maximum number of fallback queries to generate

    Returns:
        List of fallback query strings
    """
    queries = []
    first_name = author_name.split()[0] if author_name else author_name
    title_words = book_title.split()

    # Step 1: First name + full title
    queries.append(f"{first_name} - {book_title}")

    # Steps 2+: Drop words left-to-right
    for i in range(min(len(title_words), max_fallbacks - 1)):
        remaining = " ".join(title_words[:i] + title_words[i + 1 :])
        if remaining:
            queries.append(f"{first_name} - {remaining}")

    return queries[:max_fallbacks]


def execute_search(ctx: "Context", query: str, search_type: str) -> Tuple[List[Dict[str, Any]], str]:
    """Execute a single SLSKD search and return results.

    Args:
        ctx: Application context
        query: Search query string
        search_type: Label for display (e.g., "main", "fallback-1")

    Returns:
        Tuple of (search results list, search ID for cleanup)
    """
    print_search_summary(query, 0, search_type, "searching")

    search = ctx.slskd.searches.search_text(
        searchText=query,
        searchTimeout=ctx.config.getint("Search Settings", "search_timeout", fallback=5000),
        filterResponses=True,
        maximumPeerQueueLength=ctx.config.getint("Search Settings", "maximum_peer_queue", fallback=50),
        minimumPeerUploadSpeed=ctx.config.getint("Search Settings", "minimum_peer_upload_speed", fallback=0),
    )

    time.sleep(10)

    while ctx.slskd.searches.state(search["id"], False)["state"] == "InProgress":
        time.sleep(1)

    results = ctx.slskd.searches.search_responses(search["id"])
    print_search_summary(query, len(results), search_type, "completed")

    return results, search["id"]


def get_books(ctx: "Context", search_source: str, search_type: str, page_size: int) -> List[Book]:
    """Get books from Readarr based on search source and type."""
    current_page_file_path = os.path.join(ctx.config_dir, ".current_page.txt")

    api_method = ctx.readarr.get_missing if search_source == "missing" else ctx.readarr.get_cutoff

    try:
        wanted = api_method(page_size=page_size, sort_dir="ascending", sort_key="title")
    except Exception:
        logger.error(f"An error occurred when attempting to get records from {search_source}", exc_info=True)
        return []

    total_wanted = wanted["totalRecords"]
    wanted_records: List[Book] = []

    if search_type == "all":
        page = 1
        while len(wanted_records) < total_wanted:
            try:
                wanted = api_method(page=page, page_size=page_size, sort_dir="ascending", sort_key="title")
                wanted_records.extend(wanted["records"])
            except Exception:
                logger.error(f"Failed to grab records from {search_source} page {page}", exc_info=True)
                break
            page += 1

    elif search_type == "incrementing_page":
        page = get_current_page(current_page_file_path)
        try:
            wanted_records = api_method(page=page, page_size=page_size, sort_dir="ascending", sort_key="title")["records"]
        except Exception:
            logger.error(f"Failed to grab record from {search_source}", exc_info=True)

        page = 1 if page >= math.ceil(total_wanted / page_size) else page + 1
        update_current_page(current_page_file_path, page)

    elif search_type == "first_page":
        wanted_records = wanted["records"]
    else:
        raise ValueError(f"[Search Settings] - {search_type = } is not valid")

    return wanted_records
