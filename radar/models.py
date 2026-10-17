from dataclasses import dataclass, field


@dataclass
class Post:
    id: str                 # globally unique, e.g. "reddit:abc123"
    source: str             # reddit | beatapi | rss | search
    title: str
    text: str
    url: str
    author: str = ""
    created_utc: float = 0.0
    meta: dict = field(default_factory=dict)


@dataclass
class Lead:
    post: Post
    service_id: str
    service_name: str
    summary: str
    urgency: str            # high | medium | low
    budget_clue: str
    location: str
    score: int
    reason: str
    draft: str
