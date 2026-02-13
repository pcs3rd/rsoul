import logging
import time
from typing import List, Optional, Any, Dict, Tuple, TYPE_CHECKING
from pathlib import Path

from .base import (
    DownloadBackend,
    SearchResult,
    DownloadTask,
    DownloadTarget,
    DownloadStatus,
)
from . import register_backend

if TYPE_CHECKING:
    from ..config import Context

from ..download import slskd_do_enqueue, slskd_download_status, downloads_all_done
from ..match import book_match, verify_filetype
from ..display import print_search_summary

logger = logging.getLogger(__name__)


def _generate_fallback_queries(author_name: str, book_title: str, max_fallbacks: int) -> List[str]:
    """Generate progressively degraded search queries for blocked word workaround.

    Strategy:
    1. First name + full title
    2. First name + title with word 0 dropped
    3. First name + title with word 1 dropped
    ...continues left-to-right until max_fallbacks reached
    """
    queries = []
    first_name = author_name.split()[0] if author_name else author_name
    title_words = book_title.split()

    # Step 1: First name + full title
    queries.append(f"{first_name} - {book_title}")

    # Steps 2+: Drop words left-to-right
    for i in range(min(len(title_words), max_fallbacks - 1)):
        remaining = " ".join(title_words[:i] + title_words[i + 1:])
        if remaining:
            queries.append(f"{first_name} - {remaining}")

    return queries[:max_fallbacks]


def _execute_search(ctx: "Context", query: str, search_type: str) -> Tuple[List[Dict[str, Any]], str]:
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


@register_backend("slskd")
class SlskdBackend(DownloadBackend):
    """slskd implementation of DownloadBackend."""

    def __init__(self, ctx: "Context"):
        self.ctx = ctx
        self.client = ctx.slskd
        self.config = ctx.config

    @property
    def name(self) -> str:
        return "slskd"

    @property
    def priority(self) -> int:
        return self.config.getint("Backends", "slskd_priority", fallback=10)

    @property
    def download_dir(self) -> str:
        """Base directory where slskd saves files."""
        return self.config.get("Slskd", "download_dir", fallback="")

    @property
    def readarr_download_dir(self) -> str:
        """Directory path as seen by Readarr (mapped path)."""
        return self.config.get("Slskd", "readarr_download_dir", fallback=self.download_dir)

    def is_available(self) -> bool:
        """Check if slskd is configured and reachable."""
        if not self.config.has_section("Slskd"):
            return False
        try:
            # Simple check to see if client is reachable
            self.client.options.get()
            return True
        except Exception:
            return False

    def search(self, target: DownloadTarget) -> List[SearchResult]:
        """Search for a book on Soulseek via slskd."""
        author_name = target.author_name
        book_title = target.book_title
        allowed_filetypes = target.allowed_filetypes

        delete_searches = self.config.getboolean("Slskd", "delete_searches", fallback=True)

        # Build queries
        queries = []
        queries.append(f"{author_name} - {book_title}")

        if ":" in book_title:
            main_title = book_title.split(":")[0].strip()
            queries.append(f"{author_name} - {main_title}")

        max_fallbacks = self.config.getint("Search Settings", "max_search_fallbacks", fallback=5)
        queries.extend(_generate_fallback_queries(author_name, book_title, max_fallbacks))

        all_results: List[SearchResult] = []
        seen_queries = set()

        # Prepare target dict for book_match
        target_dict = {
            "book": target.readarr_book or {"title": target.book_title, "id": target.book_id, "seriesTitle": target.series_title},
            "author": target.readarr_author or {"authorName": target.author_name},
        }

        for i, query in enumerate(queries):
            if query in seen_queries:
                continue
            seen_queries.add(query)

            search_label = "main" if i == 0 else f"fallback-{i}"
            try:
                search_results, search_id = _execute_search(self.ctx, query, search_label)
            except Exception as e:
                logger.error(f"Search failed for query '{query}': {e}")
                continue

            if delete_searches:
                try:
                    self.client.searches.delete(search_id)
                except Exception:
                    pass

            if search_results:
                file_cache: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
                for result in search_results:
                    username = result["username"]
                    # Skip if in history (failed previously)
                    if self.ctx.history and self.ctx.history.is_failed(username, book_title):
                        continue

                    if username not in file_cache:
                        file_cache[username] = {}

                    for file in result["files"]:
                        for ext in allowed_filetypes:
                            if verify_filetype(file, ext):
                                if ext not in file_cache[username]:
                                    file_cache[username][ext] = []
                                file_cache[username][ext].append(file)

                # Match for each user
                for username, types in file_cache.items():
                    for ext, files in types.items():
                        match = book_match(
                            target_dict,
                            files,
                            username,
                            ext,
                            ignored_users=self.config.get("Search Settings", "ignored_users", fallback="").split(","),
                            minimum_match_ratio=self.config.getfloat("Search Settings", "minimum_filename_match_ratio", fallback=0.5),
                            min_length_ratio=self.config.getfloat("Search Settings", "min_length_ratio", fallback=0.4),
                            min_jaccard_ratio=self.config.getfloat("Search Settings", "min_jaccard_ratio", fallback=0.25),
                            min_word_overlap=self.config.getint("Search Settings", "min_word_overlap", fallback=2),
                            min_title_jaccard=self.config.getfloat("Search Settings", "min_title_jaccard", fallback=0.3),
                            min_author_jaccard=self.config.getfloat("Search Settings", "min_author_jaccard", fallback=0.5),
                        )

                        if match:
                            file_dir = match["filename"].rsplit("\\", 1)[0] if "\\" in match["filename"] else ""
                            filename = match["filename"].split("\\")[-1]

                            sr = SearchResult(
                                title=target.book_title,
                                author=target.author_name,
                                filename=filename,
                                size_bytes=match["size"],
                                extension=ext,
                                backend_name=self.name,
                                source_id=f"{username}|{match['filename']}",
                                username=username,
                                extra={
                                    "username": username,
                                    "file_dir": file_dir,
                                    "files": [match],
                                },
                            )
                            all_results.append(sr)

                # If we found any matches for this query, stop searching further queries
                if all_results:
                    break

        return all_results

    def download(self, target: DownloadTarget, result: SearchResult) -> Optional[DownloadTask]:
        """Initiate download of a Soulseek file."""
        username = result.extra["username"]
        files = result.extra["files"]
        file_dir = result.extra["file_dir"]

        # Ensure full paths for files before enqueuing
        for i in range(len(files)):
            if "\\" not in files[i]["filename"]:
                files[i]["filename"] = file_dir + "\\" + files[i]["filename"]

        downloads = slskd_do_enqueue(self.client, username, files, file_dir)

        if not downloads:
            logger.warning(f"Failed to enqueue download for {target.book_title} from {username}")
            return None

        # Log what was enqueued
        short_filename = result.filename.split("\\")[-1] if "\\" in result.filename else result.filename
        logger.info(f"Enqueued: {short_filename} from {username}")

        # local_dir should be the flattened directory name (bottom-most folder)
        local_dir = file_dir.split("\\")[-1] if file_dir else ""

        # Use (username, filename) as task_id
        task_id = f"{username}|{result.filename}"

        return DownloadTask(
            task_id=task_id,
            backend_name=self.name,
            status=DownloadStatus.QUEUED,
            book_title=target.book_title,
            author_name=target.author_name,
            book_id=target.book_id,
            filename=result.filename,
            series_title=target.series_title,
            local_dir=local_dir,
            extra={"username": username, "file_dir": file_dir, "files": downloads, "slskd_id": downloads[0]["id"] if downloads else None},
        )

    def get_status(self, task: DownloadTask) -> DownloadTask:
        """Poll slskd for transfer status."""
        downloads = task.extra.get("files", [])
        if not downloads:
            task.status = DownloadStatus.FAILED
            task.error_message = "No files in task"
            return task

        ok = slskd_download_status(self.client, downloads)
        if not ok:
            logger.debug(f"Failed to get status for some files in task {task.task_id}")

        all_succeeded, has_errors = downloads_all_done(downloads)

        if all_succeeded:
            task.status = DownloadStatus.COMPLETED
            task.progress_percent = 100.0
            return task

        # Fail fast: if any file has a terminal error, don't wait for others
        if has_errors:
            states = set(
                f.get("status", {}).get("state", "")
                for f in downloads
                if f.get("status")
            )
            task.status = DownloadStatus.FAILED
            task.error_message = f"File(s) failed: {', '.join(sorted(states))}"
            return task

        # Map remaining slskd states to DownloadStatus
        states = [f.get("status", {}).get("state", "") for f in downloads if f.get("status")]

        if any(s == "Downloading" for s in states):
            task.status = DownloadStatus.DOWNLOADING
            # Calculate aggregate progress
            total_size = sum(f.get("size", 0) for f in downloads)
            bytes_transferred = sum(f.get("status", {}).get("bytesTransferred", 0) for f in downloads if f.get("status"))
            if total_size > 0:
                task.progress_percent = (bytes_transferred / total_size) * 100
        elif any(s == "Queued, Remotely" for s in states):
            task.status = DownloadStatus.QUEUED
        else:
            # Pending/initializing states
            task.status = DownloadStatus.PENDING

        return task

    def cancel(self, task: DownloadTask) -> bool:
        """Cancel the download in slskd."""
        username = task.extra.get("username")
        files = task.extra.get("files", [])
        if not username or not files:
            return False

        success = True
        for file in files:
            try:
                self.client.transfers.cancel_download(username=username, id=file["id"])
            except Exception as e:
                logger.error(f"Failed to cancel download {file.get('id')} for {username}: {e}")
                success = False
        return success

    def cleanup(self, task: DownloadTask) -> None:
        """Remove completed downloads from slskd."""
        try:
            self.client.transfers.remove_completed_downloads()
        except Exception as e:
            logger.warning(f"Failed to cleanup completed downloads in slskd: {e}")

    def reconcile_task(self, task_data: Dict[str, Any]) -> Optional[DownloadTask]:
        """Reconcile a persisted task with live slskd state."""
        username = task_data.get("extra", {}).get("username")
        filename = task_data.get("filename")
        local_dir = task_data.get("local_dir", "")

        if not username or not filename:
            return None

        try:
            # Query slskd for all downloads to find matching transfer
            all_downloads = self.client.transfers.get_all_downloads()

            for user_transfer in all_downloads:
                if user_transfer["username"] == username:
                    for directory in user_transfer["directories"]:
                        for file in directory["files"]:
                            slskd_filename = file["filename"]
                            if slskd_filename == filename or slskd_filename.split("\\")[-1] == filename:
                                # Found it! Re-create task with updated data
                                new_files = [{"filename": file["filename"], "id": file["id"], "size": file["size"], "username": username, "file_dir": directory["directory"]}]

                                task_data["extra"]["files"] = new_files
                                task_data["extra"]["slskd_id"] = file["id"]
                                task_data["extra"]["file_dir"] = directory["directory"]

                                task = DownloadTask(
                                    task_id=task_data["task_id"],
                                    backend_name=self.name,
                                    status=DownloadStatus.PENDING,
                                    book_title=task_data["book_title"],
                                    author_name=task_data["author_name"],
                                    book_id=task_data["book_id"],
                                    filename=task_data["filename"],
                                    series_title=task_data.get("series_title", ""),
                                    local_dir=task_data.get("local_dir", ""),
                                    extra=task_data["extra"],
                                )
                                return self.get_status(task)

            # If not found in slskd, check if it's already on disk in the download dir
            if self.download_dir and local_dir:
                local_path = Path(self.download_dir) / local_dir / filename
                if local_path.exists():
                    return DownloadTask(
                        task_id=task_data["task_id"],
                        backend_name=self.name,
                        status=DownloadStatus.COMPLETED,
                        book_title=task_data["book_title"],
                        author_name=task_data["author_name"],
                        book_id=task_data["book_id"],
                        filename=filename,
                        series_title=task_data.get("series_title", ""),
                        local_dir=local_dir,
                        output_path=local_path,
                        progress_percent=100.0,
                        extra=task_data["extra"],
                    )

            return None

        except Exception as e:
            logger.error(f"Error reconciling slskd task: {e}")
            return None
