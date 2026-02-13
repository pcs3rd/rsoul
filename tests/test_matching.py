import sys
import os
import logging

# Add parent directory to path to import rsoul
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rsoul.match import book_match
from rsoul.utils import title_contained_in_filename, normalize_for_matching
from rsoul.postprocess import check_swapped_author_title, check_title_similarity
from rsoul.backends.stacks_backend import score_aa_result

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_matching")


def test_extension_stripping():
    print("\n--- Testing Extension Stripping ---")

    # Test case 1: "Tales of the Unknown.epub" vs "Tales of the Unknown"
    # Using longer title to avoid min_length_ratio (0.4) issues with short titles
    book_title = "Tales of the Unknown"
    author_name = "Author Name"
    target = {"book": {"title": book_title}, "author": {"authorName": author_name}}

    files = [
        {"filename": "Tales of the Unknown.epub", "size": 1000, "username": "user1"},
        {"filename": "Tales of the Unknown.mobi", "size": 1000, "username": "user1"},
        {"filename": "Tales of the Unknown (epub).epub", "size": 1000, "username": "user1"},
    ]

    # Run book_match
    match = book_match(
        target=target,
        slskd_files=files,
        username="user1",
        filetype="epub",
        ignored_users=[],
        minimum_match_ratio=0.8,
        min_length_ratio=0.4,
        min_jaccard_ratio=0.25,
        min_word_overlap=1,
        min_title_jaccard=0.3,
        min_author_jaccard=0.5,
    )

    if match and match["filename"] == "Tales of the Unknown.epub":
        print("PASS: Matched 'Tales of the Unknown.epub'")
    else:
        print(f"FAIL: Expected match for 'Tales of the Unknown.epub', got {match.get('filename') if match else 'None'}")


def test_partial_title_strictness():
    print("\n--- Testing Partial Title Strictness ---")

    # "The Great Book" vs "Great Book" (should pass 80% check)
    t1 = "The Great Book"
    f1 = "Great Book.epub"
    if title_contained_in_filename(t1, f1):
        print(f"PASS: '{t1}' contained in '{f1}' (ignoring 'The')")
    else:
        print(f"FAIL: '{t1}' NOT contained in '{f1}'")

    # "The Great Book" vs "The Great Cook" (should fail)
    t2 = "The Great Book"
    f2 = "The Great Cook.epub"
    if not title_contained_in_filename(t2, f2):
        print(f"PASS: '{t2}' correctly NOT contained in '{f2}'")
    else:
        print(f"FAIL: '{t2}' falsely contained in '{f2}'")

    # "Introduction to Algorithms" vs "Algorithms" (should fail strict check if < 80%)
    t3 = "Introduction to Algorithms"
    f3 = "Algorithms.pdf"
    # Words: {introduction, to, algorithms} (3) vs {algorithms} (1). Overlap 1/3 = 33%. Should fail.
    if not title_contained_in_filename(t3, f3):
        print(f"PASS: '{t3}' correctly NOT contained in '{f3}' (only 33% overlap)")
    else:
        print(f"FAIL: '{t3}' falsely contained in '{f3}'")


def test_stacks_scoring():
    print("\n--- Testing Stacks Scoring ---")

    # Case: Perfect Author, Wrong Title
    # Author: "John Doe", Title: "My Life"
    # File: "John Doe - His Life.epub"

    path = "John Doe - His Life.epub"
    book_title = "My Life"
    author_name = "John Doe"
    series_title = ""

    score = score_aa_result(path, book_title, author_name, series_title, min_match_ratio=0.6)
    print(f"Score for '{path}' against '{book_title}': {score:.2f}")

    if score < 0.6:
        print("PASS: Low score for wrong title despite perfect author match")
    else:
        print("FAIL: High score for wrong title")

    # Case: Correct Author, Correct Title
    path2 = "John Doe - My Life.epub"
    score2 = score_aa_result(path2, book_title, author_name, series_title, min_match_ratio=0.6)
    print(f"Score for '{path2}' against '{book_title}': {score2:.2f}")

    if score2 >= 0.6:
        print("PASS: High score for correct match")
    else:
        print("FAIL: Low score for correct match")


def test_swapped_metadata():
    print("\n--- Testing Swapped Metadata ---")

    # Metadata Title = Author Name
    # Expected Author = Author Name
    # Expected Title = Book Title

    meta_title = "John Doe"  # Swapped
    expected_author = "John Doe"
    expected_title = "My Life"

    is_swapped = check_swapped_author_title(meta_title, expected_author, expected_title)

    if is_swapped:
        print("PASS: Detected swapped metadata")
    else:
        print("FAIL: Did not detect swapped metadata")


if __name__ == "__main__":
    test_extension_stripping()
    test_partial_title_strictness()
    test_stacks_scoring()
    test_swapped_metadata()
