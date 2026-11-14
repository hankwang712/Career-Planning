import re

from .storage import normalized
from .schemas import ModelOutput
from typing import Annotated, Literal
from pydantic import StringConstraints


OPERATIONS = ("ADD", "NOOP", "ENRICH", "REPLACE", "CONFLICT", "RETRACT")
FACT_SLOTS = {"school", "education", "graduation", "major"}
LIST_SLOTS = {"target_city", "target_role", "industry"}


class DecisionOutput(ModelOutput):
    operation: Literal["ADD", "NOOP", "ENRICH", "REPLACE", "CONFLICT", "RETRACT"]
    target_id: str | None
    value: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    reason: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    requires_confirmation: bool

REPLACEMENT_CUE = r"纠正|更正|记错|改为|改成|其实|实际|之前.*(?:错|不对)|重新|恢复|只考虑|不再|不是.*而是|instead|replace|correct"
EXCLUSIVE_CUE = r"纠正|更正|记错|改为|改成|只考虑|不再|不是.*而是|instead|replace|correct"
ADDITIVE_CUE = r"也可以|也考虑|还可以|还考虑|同时考虑|另外|新增|补充|还会|也会|还学会"


def _members(value):
    return {normalized(part): part.strip() for part in re.split(r"[、,，;；/]", value) if part.strip()}


def _enriched_value(old, candidate, proposed):
    """Compose a union from supported values; the model cannot add a third claim."""
    before, after = old["value"], candidate["value"]
    if candidate["key"] in {"target_city", "target_role", "industry"}:
        members = _members(before)
        members.update({key: value for key, value in _members(after).items() if key not in members})
        if _members(proposed).keys() != members.keys():
            raise ValueError("List enrichment must retain old and new members without invention")
        return "、".join(members.values())
    if candidate["key"] in {"education", "graduation", "major", "salary", "availability"}:
        raise ValueError("A single-valued attribute needs correction or conflict resolution")
    left, right, result = normalized(before), normalized(after), normalized(proposed)
    if right in left and result == left:
        return before
    if left in right and result == right:
        return after
    join = r"[、，,;；。]*(?:并且|并|还|也|以及|同时|此外|而且|和)?"
    if not any(re.fullmatch(re.escape(first) + join + re.escape(second), result)
               for first, second in ((left, right), (right, left))):
        raise ValueError("Enrichment must preserve supported old and candidate text")
    return before + "；" + after


def _decision(operation, old, value, reason, confirm=False):
    return {"operation": operation, "target_id": old["id"] if old else None, "value": value, "reason": reason,
            "requires_confirmation": confirm}


def automatic_decision(candidate, matches):
    """Decide how a candidate relates to existing memory using only the user's own words.

    The relation never needs a second model call: anything not clearly an addition, repeat or explicit
    replacement becomes a CONFLICT that the user confirms, which is the safe side for career facts.
    """
    old = next((row for row in matches if ":conflict:" not in row["id"] and
                normalized(row["subject"]) == normalized(candidate["subject"])), None)
    operation, key, value = candidate["operation"], candidate["key"], candidate["value"]
    quote = " ".join(item["quote"] for item in candidate["evidence"])
    if operation == "retract":
        return {"operation": "RETRACT", "target_id": old["id"] if old else None,
                "value": old["value"] if old else value, "reason": "explicit_retraction", "requires_confirmation": False}
    if not old:
        if matches:
            return None  # only unresolved conflict rows exist for this slot; the caller skips the candidate
        return _decision("ADD", None, value, "new_slot")
    if old["status"] == "retracted" and operation != "correct":
        return _decision("NOOP", old, old["value"], "keep_retracted")
    if operation == "correct":
        return _decision("REPLACE", old, value, "explicit_correction")
    if normalized(old["value"]) == normalized(value):
        return _decision("NOOP", old, old["value"], "duplicate")
    if key in FACT_SLOTS:
        return _decision("CONFLICT", old, value, "unconfirmed_fact_change", True)
    replaces = bool(re.search(REPLACEMENT_CUE, quote, re.I)) and not (
        re.search(ADDITIVE_CUE, quote) and not re.search(EXCLUSIVE_CUE, quote, re.I))
    additive = bool(re.search(ADDITIVE_CUE, quote)) and not re.search(r"只考虑|不再|改为|改成|纠正|更正", quote)
    if key in LIST_SLOTS:
        before, after = _members(old["value"]), _members(value)
        if replaces:
            return _decision("REPLACE", old, value, "explicit_replacement")
        if after.keys() <= before.keys():
            return _decision("NOOP", old, old["value"], "already_saved")
        if additive:
            merged = dict(before)
            merged.update({name: item for name, item in after.items() if name not in merged})
            return _decision("ENRICH", old, "、".join(merged.values()), "supported_addition")
        return _decision("CONFLICT", old, value, "unconfirmed_list_change", True)
    if key == "constraint":
        if normalized(value) in normalized(old["value"]) and not re.search(ADDITIVE_CUE, quote):
            return _decision("NOOP", old, old["value"], "already_saved")
        if replaces:
            return _decision("REPLACE", old, value, "explicit_replacement")
        if additive:
            return _decision("ENRICH", old, old["value"] + "；" + value, "supported_addition")
        return _decision("CONFLICT", old, value, "unconfirmed_change", True)
    if replaces or candidate["kind"] == "communication" and not re.search(ADDITIVE_CUE, quote):
        return _decision("REPLACE", old, value, "newer_statement" if not replaces else "explicit_replacement")
    return _decision("CONFLICT", old, value, "unconfirmed_change", True)


def validate_decision(raw, candidate, matches):
    if not isinstance(raw, dict) or raw.get("operation") not in OPERATIONS:
        raise ValueError("Unknown reconciliation operation")
    raw = DecisionOutput.model_validate({"reason": "validated_program_decision", "requires_confirmation": False, **raw}).model_dump()
    op, target = raw["operation"], raw["target_id"]
    if target is not None and not isinstance(target, str):
        raise ValueError("Invalid target")
    old = next((row for row in matches if row["id"] == target and ":conflict:" not in row["id"]), None)
    if target is not None and old is None or op not in ("ADD", "NOOP", "RETRACT") and old is None:
        raise ValueError("Target must be an owned matching memory")
    if op == "NOOP" and old is None:
        raise ValueError("NOOP needs a matching memory")
    if old and (old["kind"], old["key"]) != (candidate["kind"], candidate["key"]):
        raise ValueError("Cannot change another attribute")
    if old and normalized(old["subject"]) != normalized(candidate["subject"]):
        raise ValueError("A semantic match cannot authorize changing another subject")
    value = raw.get("value")
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 1000:
        raise ValueError("Invalid reconciled value")
    quote = " ".join(item["quote"] for item in candidate["evidence"])
    if candidate["operation"] == "retract" and op != "RETRACT":
        raise ValueError("A forgetting request cannot create or confirm a fact")
    if raw["requires_confirmation"] and op != "CONFLICT":
        raise ValueError("An unconfirmed decision must be represented as a conflict")
    exact = any(normalized(row["subject"]) == normalized(candidate["subject"]) for row in matches)
    if op == "ADD" and (target is not None or exact or normalized(value) != normalized(candidate["value"])):
        raise ValueError("ADD must preserve an unmatched candidate")
    if op == "RETRACT" and (candidate["operation"] != "retract" or not re.search(r"忘记|删除|不再记录|forget|remove", quote, re.I)):
        raise ValueError("Retraction needs an explicit request")
    if op == "REPLACE":
        if candidate["kind"] != "communication" and not re.search(REPLACEMENT_CUE, quote, re.I):
            raise ValueError("Replacing a value needs an explicit change in user evidence")
        if re.search(ADDITIVE_CUE, quote) and not re.search(EXCLUSIVE_CUE, quote, re.I):
            raise ValueError("An additive statement cannot authorize replacement")
        if candidate["kind"] == "fact" and candidate["operation"] != "correct":
            raise ValueError("Replacing facts needs an explicit correction")
        if old["status"] == "retracted" and (candidate["operation"] != "correct" or not re.search(r"恢复|重新|再记住|记回|restore", quote, re.I)):
            raise ValueError("Restoring forgotten memory needs explicit evidence")
    if old and old["status"] == "retracted" and op not in ("NOOP", "REPLACE", "RETRACT"):
        raise ValueError("Cannot enrich or conflict with a forgotten memory")
    if op == "NOOP" and old:
        if old["status"] == "active" and normalized(candidate["value"]) != normalized(old["value"]) and re.search(r"只考虑|不再|改为|改成|纠正|更正", quote):
            raise ValueError("NOOP cannot discard an explicit change")
        value = old["value"]
        if candidate["key"] in {"target_city", "target_role", "industry"} and not _members(candidate["value"]).keys() <= _members(old["value"]).keys():
            raise ValueError("NOOP cannot discard new list members")
        if candidate["key"] == "constraint" and re.search(ADDITIVE_CUE, quote) and normalized(candidate["value"]) not in normalized(old["value"]):
            raise ValueError("NOOP cannot discard an explicit supported addition")
    if op in ("REPLACE", "CONFLICT") and normalized(value) != normalized(candidate["value"]):
        raise ValueError("Replacement and conflict must preserve the supported candidate value")
    if op == "ENRICH":
        if re.search(r"只考虑|不再|改为|改成|纠正|更正", quote):
            raise ValueError("Enrichment cannot retain an explicitly replaced or negated value")
        value = _enriched_value(old, candidate, value)
    if op in ("ENRICH", "REPLACE"):
        supported_numbers = set(re.findall(r"\d+(?:\.\d+)?", (old["value"] if old else "") + " " + quote))
        if not set(re.findall(r"\d+(?:\.\d+)?", value)) <= supported_numbers:
            raise ValueError("Reconciliation cannot invent numeric claims")
    if len(value) > 1000:
        raise ValueError("Enriched value exceeds the memory size limit")
    return {"operation": op, "target_id": target, "value": value.strip(), "reason": raw["reason"],
            "requires_confirmation": op == "CONFLICT"}
