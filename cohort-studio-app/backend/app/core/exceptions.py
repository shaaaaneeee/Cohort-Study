"""Errors the domain raises. core/errors.py turns each into an HTTP response."""


class StudyError(Exception):
    """The study has design errors. issues holds everything found, warnings included."""

    def __init__(self, issues: list[dict]):
        messages = [i["message"] for i in issues if i["level"] == "error"]
        super().__init__(" ".join(messages))
        self.issues = issues


class AnalysisError(Exception):
    """The data cannot support the analysis as specified."""


class DataSourceError(Exception):
    """The database could not be reached or refused the query."""
