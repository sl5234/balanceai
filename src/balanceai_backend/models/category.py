from dataclasses import dataclass, asdict


@dataclass
class Category:
    name: str
    description: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Category":
        return cls(name=d["name"], description=d["description"])
