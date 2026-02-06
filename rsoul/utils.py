import os
import re


def sanitize_folder_name(folder_name):
    valid_characters = re.sub(r'[<>:."/\\|?*]', "", folder_name)
    return valid_characters.strip()


def is_docker():
    return os.getenv("IN_DOCKER") is not None


def get_current_page(path: str, default_page=1) -> int:
    if os.path.exists(path):
        with open(path, "r") as file:
            page_string = file.read().strip()
            if page_string:
                return int(page_string)
            else:
                with open(path, "w") as file:
                    file.write(str(default_page))
                return default_page
    else:
        with open(path, "w") as file:
            file.write(str(default_page))
        return default_page


def update_current_page(path: str, page: int) -> None:
    with open(path, "w") as file:
        file.write(str(page))


def normalize_for_matching(text: str) -> str:
    """Normalize text for better matching by handling common variations"""
    # Convert to lowercase
    text = text.lower()
    # Replace underscores with spaces
    text = text.replace("_", " ")
    # Remove common punctuation that might vary
    text = re.sub(r"[^\w\s]", " ", text)
    # Normalize multiple spaces to single space
    text = re.sub(r"\s+", " ", text)
    # Strip whitespace
    return text.strip()


def jaccard_similarity(str_a: str, str_b: str) -> tuple[float, int, int]:
    """Calculate Jaccard similarity between two strings based on word tokens.

    Args:
        str_a: First string
        str_b: Second string

    Returns:
        Tuple of (jaccard_score, overlap_count, union_count)
    """
    set_a = set(normalize_for_matching(str_a).split())
    set_b = set(normalize_for_matching(str_b).split())

    if not set_a or not set_b:
        return 0.0, 0, 0

    intersection = set_a & set_b
    union = set_a | set_b

    overlap_count = len(intersection)
    union_count = len(union)

    score = overlap_count / union_count if union_count > 0 else 0.0
    return score, overlap_count, union_count


def length_ratio(str_a: str, str_b: str) -> float:
    """Calculate length ratio between two strings.

    Returns:
        Ratio of shorter/longer string (0.0-1.0)
    """
    len_a, len_b = len(str_a), len(str_b)
    if len_a == 0 or len_b == 0:
        return 0.0
    return min(len_a, len_b) / max(len_a, len_b)


def extract_author_title(filename: str) -> tuple[str, str]:
    """Extract author and title components from a filename.

    Tries common separators: " - ", " _ ", " by ".
    Handles both "Author - Title" and "Title - Author" patterns.
    Strips file extension before parsing.

    Args:
        filename: Filename to parse

    Returns:
        Tuple of (part1, part2) or (filename, "") if no separator found
    """
    # Remove extension
    name = filename.rsplit(".", 1)[0] if "." in filename else filename

    # Try common separators in order of preference
    separators = [" - ", " _ ", " by "]

    for sep in separators:
        if sep in name:
            parts = name.split(sep, 1)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()

    return name.strip(), ""


def title_contained_in_filename(target_title: str, filename: str) -> bool:
    """Check if the target title is contained in the filename with fuzzy matching"""
    normalized_target = normalize_for_matching(target_title)
    normalized_filename = normalize_for_matching(filename)

    # Check direct containment
    if normalized_target in normalized_filename:
        return True

    # Check word-by-word containment for partial matches
    target_words = set(normalized_target.split())
    filename_words = set(normalized_filename.split())

    # If most of the target words are in the filename, it's likely a match
    if not target_words:
        return False

    overlap = len(target_words.intersection(filename_words))
    return overlap >= len(target_words) * 0.7  # 70% word overlap
