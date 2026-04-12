import datetime
import json
from dataclasses import dataclass, field

from appdevcommons.unique_id import UniqueIdGenerator


@dataclass
class ReportDefinition:
    name: str
    prompt: str
    sql_template: str
    description: str
    unparameterized_sql: str | None = None
    parameters: list[dict] = field(default_factory=list)
    report_definition_id: str = field(default_factory=UniqueIdGenerator.generate_id)
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "report_definition_id": self.report_definition_id,
            "name": self.name,
            "prompt": self.prompt,
            "sql_template": self.sql_template,
            "description": self.description,
            "unparameterized_sql": self.unparameterized_sql,
            "parameters": self.parameters,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReportDefinition":
        d = dict(d)
        if isinstance(d.get("parameters"), str):
            d["parameters"] = json.loads(d["parameters"])
        elif d.get("parameters") is None:
            d["parameters"] = []
        return cls(**d)
