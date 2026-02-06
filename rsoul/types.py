from typing import TypedDict, List, Optional, Any, Dict


class Book(TypedDict, total=False):
    title: str
    seriesTitle: str
    id: int
    authorId: int
    monitored: bool


class Author(TypedDict, total=False):
    authorName: str
    qualityProfileId: int


class SlskdFile(TypedDict, total=False):
    filename: str
    size: int
    id: Optional[str]
    status: Optional[Dict[str, Any]]
    retry: Optional[int]
    file_dir: Optional[str]
    username: Optional[str]


class SlskdDirectory(TypedDict):
    files: List[SlskdFile]
    name: str
