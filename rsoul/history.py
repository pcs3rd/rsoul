import json
import os
import logging
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)


class HistoryManager:
    """
    Manages a persistent list of failed downloads to prevent re-queueing.
    """

    def __init__(self, config_dir: str):
        self.file_path = os.path.join(config_dir, "failed_downloads.json")
        self.history: List[Dict[str, str]] = []
        self.load()

    def load(self):
        """Load history from JSON file."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load history from {self.file_path}: {e}")
                self.history = []
        else:
            self.history = []

    def save(self):
        """Save history to JSON file."""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save history to {self.file_path}: {e}")

    def add_failure(self, username: str, book_title: str, reason: str = ""):
        """
        Record a failed download/import.

        Args:
            username: The Soulseek username.
            book_title: The canonical book title from Readarr.
            reason: Optional reason for failure.
        """
        if not username or not book_title:
            return

        # Check if already exists to avoid duplicates
        if self.is_failed(username, book_title):
            return

        entry = {"username": username, "book_title": book_title, "timestamp": datetime.now().isoformat(), "reason": reason}
        self.history.append(entry)
        logger.info(f"Added to blocklist: User '{username}' for Book '{book_title}'")
        self.save()

    def is_failed(self, username: str, book_title: str) -> bool:
        """
        Check if a username/book combo is in the blocklist.
        Case-insensitive comparison.
        """
        if not username or not book_title:
            return False

        target_user = username.strip().lower()
        target_book = book_title.strip().lower()

        for entry in self.history:
            h_user = entry.get("username", "").strip().lower()
            h_book = entry.get("book_title", "").strip().lower()

            if h_user == target_user and h_book == target_book:
                return True

        return False
