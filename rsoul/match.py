import difflib
import logging
import re
from typing import Any, Optional, Dict, List
from .display import print_match_details
from .utils import normalize_for_matching, title_contained_in_filename, jaccard_similarity, length_ratio, extract_author_title

logger = logging.getLogger(__name__)


def verify_filetype(file: Dict[str, Any], allowed_filetype: str) -> bool:
    current_filetype = file["filename"].split(".")[-1].lower()
    logger.debug(f"Current file type: {current_filetype}")
    if current_filetype == allowed_filetype.split(" ")[0]:
        return True
    else:
        return False


def check_ratio(separator: str, ratio: float, book_filename: str, slskd_filename: str, minimum_match_ratio: float) -> float:
    if ratio < minimum_match_ratio:
        if separator != "":
            book_filename_word_count = len(book_filename.split()) * -1
            truncated_slskd_filename = " ".join(slskd_filename.split(separator)[book_filename_word_count:])
            ratio = difflib.SequenceMatcher(None, book_filename, truncated_slskd_filename).ratio()
        else:
            ratio = difflib.SequenceMatcher(None, book_filename, slskd_filename).ratio()
        return ratio
    return ratio


def book_match(
    target: Dict[str, Any],
    slskd_files: List[Dict[str, Any]],
    username: str,
    filetype: str,
    ignored_users: List[str],
    minimum_match_ratio: float,
    min_length_ratio: float = 0.4,
    min_jaccard_ratio: float = 0.25,
    min_word_overlap: int = 2,
    min_title_jaccard: float = 0.3,
    min_author_jaccard: float = 0.5,
) -> Optional[Dict[str, Any]]:
    """
    Match target book with available files, filtering by correct filetype.
    Enhanced to handle variations in punctuation, underscores, and additional text.

    Pre-filters applied before fuzzy matching:
    - Length ratio gate: Rejects if string lengths differ too much
    - Jaccard token overlap: Rejects if word overlap is too low
    - Minimum word overlap: Rejects if fewer than N words match
    - Component-wise matching: Matches author and title segments separately

    Args:
        target: Target book information
        slskd_files: List of available files
        username: Username of the file owner
        filetype: Required file type (e.g., 'epub', 'pdf')
        ignored_users: List of ignored users
        minimum_match_ratio: Minimum ratio to consider a match
        min_length_ratio: Minimum length ratio (shorter/longer) - default 0.4
        min_jaccard_ratio: Minimum Jaccard similarity threshold - default 0.25
        min_word_overlap: Minimum number of overlapping words required - default 2
        min_title_jaccard: Minimum Jaccard for title component - default 0.3
        min_author_jaccard: Minimum Jaccard for author component - default 0.5

    Returns:
        Matching file object or None
    """
    book_title = target["book"]["title"]
    author_name = target["author"]["authorName"]
    best_match = 0.0
    current_match = None

    # Filter files by the correct filetype first
    filtered_files = []
    for slskd_file in slskd_files:
        if verify_filetype(slskd_file, filetype):
            filtered_files.append(slskd_file)

    # If no files match the desired filetype, return None
    if not filtered_files:
        logger.debug(f"No files found matching filetype: {filetype}")
        return None

    for slskd_file in filtered_files:
        slskd_filename = slskd_file["filename"].split("\\")[-1]

        # Build expected filename pattern for pre-filter comparison
        expected_pattern = f"{book_title} - {author_name}.{filetype.split(' ')[0]}"

        # Pre-filter 1: Length ratio gate
        len_ratio = length_ratio(expected_pattern, slskd_filename)
        if len_ratio < min_length_ratio:
            logger.debug(f"Skipping {slskd_filename}: length ratio {len_ratio:.2f} < {min_length_ratio}")
            continue

        # Pre-filter 2: Jaccard token overlap
        jaccard_score, overlap_count, _ = jaccard_similarity(expected_pattern, slskd_filename)
        if jaccard_score < min_jaccard_ratio:
            logger.debug(f"Skipping {slskd_filename}: Jaccard {jaccard_score:.2f} < {min_jaccard_ratio}")
            continue

        # Pre-filter 3: Minimum word overlap
        if overlap_count < min_word_overlap:
            logger.debug(f"Skipping {slskd_filename}: word overlap {overlap_count} < {min_word_overlap}")
            continue

        # Pre-filter 4: Component-wise matching (author vs author, title vs title)
        found_part1, found_part2 = extract_author_title(slskd_filename)

        if found_part2:  # Only apply if we found a separator
            # Try both orderings: "Author - Title" and "Title - Author"
            # Calculate scores for both interpretations
            author_as_p1 = jaccard_similarity(author_name, found_part1)[0]
            title_as_p2 = jaccard_similarity(book_title, found_part2)[0]
            score_order1 = min(author_as_p1, title_as_p2)  # Author-Title order

            author_as_p2 = jaccard_similarity(author_name, found_part2)[0]
            title_as_p1 = jaccard_similarity(book_title, found_part1)[0]
            score_order2 = min(author_as_p2, title_as_p1)  # Title-Author order

            # Use the better ordering
            if score_order1 >= score_order2:
                author_score, title_score = author_as_p1, title_as_p2
            else:
                author_score, title_score = author_as_p2, title_as_p1

            # Both components must meet their thresholds
            if author_score < min_author_jaccard:
                logger.debug(f"Skipping {slskd_filename}: author Jaccard {author_score:.2f} < {min_author_jaccard}")
                continue

            if title_score < min_title_jaccard:
                logger.debug(f"Skipping {slskd_filename}: title Jaccard {title_score:.2f} < {min_title_jaccard}")
                continue

            logger.debug(f"Component match passed: author={author_score:.2f}, title={title_score:.2f}")

        logger.info(f"Checking ratio on {slskd_filename} vs wanted {book_title} - {author_name}.{filetype.split(' ')[0]}")

        # First, check if this looks like a very good match based on title containment
        title_bonus = 0.0
        if title_contained_in_filename(book_title, slskd_filename):
            title_bonus = 0.3  # Significant bonus for files that clearly contain the target title
            logger.info(f"Title containment bonus applied: +{title_bonus}")

        # Try multiple filename patterns for matching
        patterns_to_try = [
            f"{book_title} - {author_name}.{filetype.split(' ')[0]}",
            f"{author_name} - {book_title}.{filetype.split(' ')[0]}",
            f"{book_title}.{filetype.split(' ')[0]}",
            f"{author_name} {book_title}.{filetype.split(' ')[0]}",
        ]

        max_ratio = 0.0

        for pattern in patterns_to_try:
            # Direct ratio
            ratio = difflib.SequenceMatcher(None, pattern, slskd_filename).ratio()
            max_ratio = max(max_ratio, ratio)

            # Try with normalized strings for better matching
            normalized_pattern = normalize_for_matching(pattern)
            normalized_filename = normalize_for_matching(slskd_filename)
            normalized_ratio = difflib.SequenceMatcher(None, normalized_pattern, normalized_filename).ratio()
            max_ratio = max(max_ratio, normalized_ratio)

            # Try with different separators
            ratio = check_ratio(" ", ratio, pattern, slskd_filename, minimum_match_ratio)
            max_ratio = max(max_ratio, ratio)

            ratio = check_ratio("_", ratio, pattern, slskd_filename, minimum_match_ratio)
            max_ratio = max(max_ratio, ratio)

        # Apply title bonus if applicable
        final_ratio = max_ratio + title_bonus

        if final_ratio > best_match:
            logger.info(f"New best match found! Ratio: {max_ratio:.3f} + Title bonus: {title_bonus:.3f} = {final_ratio:.3f}")
            best_match = final_ratio
            current_match = slskd_file
        else:
            logger.info(f"Ratio: {max_ratio:.3f} + Title bonus: {title_bonus:.3f} = {final_ratio:.3f} (not better than current best: {best_match:.3f})")

    if (current_match != None) and (username not in ignored_users) and (best_match >= minimum_match_ratio):
        # Log match found (toned down - details logged at DEBUG level)
        short_filename = current_match["filename"].split("\\")[-1] if "\\" in current_match["filename"] else current_match["filename"]
        logger.info(f"Match found: {short_filename} (ratio: {best_match:.3f})")

        # Print match details at debug level
        print_match_details(current_match["filename"], best_match, username, filetype)

        return current_match

    return None
