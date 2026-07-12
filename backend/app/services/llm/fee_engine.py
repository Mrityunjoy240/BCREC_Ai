"""FeeEngine — data-driven fee computation engine.

This engine loads fee structure data from JSON files and provides
deterministic computation of fees. It runs in VALIDATION-ONLY mode
by default — it NEVER modifies production responses.

Design principles:
  - Zero code changes for fee updates (only JSON edits)
  - Automatic fallback on validation failure
  - mtime-based cache invalidation (same pattern as _read_canonical_kb)
  - Component-based computation with versioned structures
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_FEE_STRUCTURES_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "fee_structures"
)

_CONFIG_PATH = _FEE_STRUCTURES_DIR / "_config.json"

# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


class ComponentCategory(Enum):
    COMPULSORY = "compulsory"
    REFUNDABLE = "refundable"
    OPTIONAL = "optional"
    SPECIAL = "special"


class ComponentType(Enum):
    ONE_TIME = "one_time"
    PER_SEMESTER = "per_semester"
    PER_MONTH = "per_month"


class StructureStatus(Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    DRAFT = "draft"


@dataclass
class FeeComponent:
    id: str
    label: str
    type: ComponentType
    category: ComponentCategory
    amount: int
    applicable_semesters: list[int] = field(default_factory=list)
    charged_in_semester: int | None = None
    refundable_at: str | None = None
    optional: bool = False
    effective_from_batch: str | None = None
    discontinued_from_batch: str | None = None
    notes: str | None = None
    months_per_year: int | None = None
    availability: str | None = None

    @property
    def is_optional(self) -> bool:
        return self.optional or self.category in (
            ComponentCategory.OPTIONAL,
            ComponentCategory.SPECIAL,
        )


@dataclass
class FeeComputed:
    total_course_fee: int
    first_semester_payable: int | None = None
    regular_semester_fee: int | None = None
    eighth_semester_fee: int | None = None



@dataclass
class FeeGroupData:
    group_key: str
    branches: list[str]
    components: list[FeeComponent]
    semester_overrides: dict[int, dict[str, Any]]
    computed: FeeComputed
    notes: str | None = None


@dataclass
class FeeStructure:
    version_id: str
    status: StructureStatus
    label: str | None = None
    admission_batches: list[str] = field(default_factory=list)
    effective_date: str | None = None
    published_date: str | None = None
    source: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    groups: dict[str, FeeGroupData] = field(default_factory=dict)


@dataclass
class ProgramFees:
    program: str
    display_name: str | None = None
    duration_semesters: int = 8
    groups: dict[str, list[str]] = field(default_factory=dict)
    structures: list[FeeStructure] = field(default_factory=list)


@dataclass
class HostelFees:
    structures: list[FeeStructure] = field(default_factory=list)


# Response types
@dataclass
class FeeQueryResult:
    branch: str
    program: str
    batch: str | None
    structure: FeeStructure | None = None
    group_data: FeeGroupData | None = None
    total_fee: int | None = None
    semester_fee: int | None = None
    semester: int | None = None
    component_breakdown: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    is_fallback: bool = False


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    file_path: str | None = None

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        return ValidationResult(
            is_valid=self.is_valid and other.is_valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# ---------------------------------------------------------------------------
# FeeEngine
# ---------------------------------------------------------------------------


class FeeEngine:
    """Loads fee structures from JSON and provides computation methods.

    This engine runs in shadow/validation mode. It does NOT modify any
    production response paths. It exists to:
      1. Validate fee data files on every load
      2. Provide correct fee calculations
      3. Enable migration testing against the current FEE_GROUP_MAP
    """

    def __init__(self, fee_dir: str | Path | None = None):
        self._fee_dir = Path(fee_dir) if fee_dir else _FEE_STRUCTURES_DIR
        self._config: dict[str, Any] = {}
        self._programs: dict[str, ProgramFees] = {}
        self._hostel: HostelFees = HostelFees()
        self._branch_to_program: dict[str, str] = {}
        self._load_errors: list[str] = []

        # mtime caches (same pattern as _read_canonical_kb)
        self._config_mtime: float | None = None
        self._program_mtimes: dict[str, float] = {}
        self._loaded: bool = False

    # ------------------------------------------------------------------
    # Loading & Validation
    # ------------------------------------------------------------------

    def load_all(self, force: bool = False) -> ValidationResult:
        """Load and validate all fee structure files.

        If validation fails for any file, that file's previous data is
        retained (fallback). Returns an aggregate ValidationResult.
        """
        result = ValidationResult(is_valid=True)
        config_result = self._load_config(force)
        result = result.merge(config_result)
        if not config_result.is_valid:
            result.errors.append("Config load failed — cannot load program files")
            return result

        program_files = self._config.get("program_files", {})
        branch_mapping = self._config.get("branch_mapping", {})

        for filename, meta in program_files.items():
            file_result = self._load_program_file(filename, force)
            result = result.merge(file_result)

        self._branch_to_program = branch_mapping
        self._loaded = True
        return result

    def _load_config(self, force: bool = False) -> ValidationResult:
        path = _CONFIG_PATH if self._fee_dir == _FEE_STRUCTURES_DIR else self._fee_dir / "_config.json"
        mtime = self._get_mtime(path)
        if not force and mtime == self._config_mtime and self._config:
            return ValidationResult(is_valid=True)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self._load_errors.append(f"Failed to load config: {e}")
            return ValidationResult(
                is_valid=False,
                errors=[f"Config file _config.json: {e}"],
            )

        required = ["current_academic_year", "program_files", "branch_mapping"]
        for key in required:
            if key not in data:
                return ValidationResult(
                    is_valid=False,
                    errors=[f"Config missing required key: {key}"],
                )

        self._config = data
        self._config_mtime = mtime
        return ValidationResult(is_valid=True)

    def _load_program_file(self, filename: str, force: bool = False) -> ValidationResult:
        path = self._fee_dir / filename
        if not path.exists():
            return ValidationResult(
                is_valid=False,
                errors=[f"Fee file not found: {filename}"],
            )

        mtime = self._get_mtime(path)
        if not force and mtime == self._program_mtimes.get(filename) and filename in self._get_program_cache_keys():
            return ValidationResult(is_valid=True)

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            self._load_errors.append(f"Failed to parse {filename}: {e}")
            return ValidationResult(
                is_valid=False,
                errors=[f"{filename}: JSON parse error — {e}"],
                file_path=str(path),
            )

        validate_result = self._validate_program_file(raw, filename)
        if not validate_result.is_valid:
            self._load_errors.extend(validate_result.errors)
            return validate_result

        self._parse_program_file(raw, filename, mtime)
        return validate_result

    def _get_program_cache_keys(self) -> list[str]:
        keys = []
        for prog_name, prog in self._programs.items():
            for struct in prog.structures:
                keys.append(f"{prog_name}_{struct.version_id}")
        return keys

    def _validate_program_file(self, raw: dict, filename: str) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        # _file_meta
        meta = raw.get("_file_meta", {})
        for key in ("program", "duration_semesters", "last_updated", "schema_version"):
            if key not in meta:
                errors.append(f"{filename}: missing _file_meta.{key}")

        # groups
        groups = raw.get("groups", {})
        if not groups:
            errors.append(f"{filename}: no groups defined")

        for gkey, gval in groups.items():
            if "branches" not in gval:
                errors.append(f"{filename}: group '{gkey}' missing 'branches'")

        # structures
        structures = raw.get("structures", [])
        if not structures:
            errors.append(f"{filename}: no structures defined")

        version_ids: set[str] = set()
        batch_map: dict[str, str] = {}

        for si, struct in enumerate(structures):
            vid = struct.get("version_id", f"<index {si}>")
            if vid in version_ids:
                errors.append(f"{filename}: duplicate version_id '{vid}'")
            version_ids.add(vid)

            status = struct.get("status", "unknown")
            if status not in ("active", "superseded", "archived", "draft"):
                errors.append(f"{filename}: structure '{vid}' has invalid status '{status}'")

            batches = struct.get("admission_batches", [])
            for batch in batches:
                if not re.match(r"^\d{4}-\d{2}$", batch):
                    errors.append(f"{filename}: '{vid}' invalid batch format '{batch}' (expected YYYY-YY)")
                if status == "active":
                    if batch in batch_map:
                        warnings.append(
                            f"{filename}: batch '{batch}' claimed by both '{batch_map[batch]}' and '{vid}'"
                        )
                    batch_map[batch] = vid

            effective = struct.get("effective_date", "")
            if effective and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(effective)):
                errors.append(f"{filename}: '{vid}' invalid effective_date '{effective}'")

            # Validate group components
            sgroups = struct.get("groups", {})
            for gkey, gdata in sgroups.items():
                if gkey not in groups:
                    errors.append(f"{filename}: '{vid}' references undefined group '{gkey}'")
                    continue

                components = gdata.get("components", [])
                if not components:
                    errors.append(f"{filename}: '{vid}' group '{gkey}' has no components")
                    continue

                comp_ids: set[str] = set()
                for ci, comp in enumerate(components):
                    cid = comp.get("id", f"<{ci}>")
                    if cid in comp_ids:
                        errors.append(f"{filename}: '{vid}' / '{gkey}' duplicate component id '{cid}'")
                    comp_ids.add(cid)

                    if not isinstance(comp.get("amount"), int) or comp["amount"] < 0:
                        errors.append(
                            f"{filename}: '{vid}' / '{gkey}' component '{cid}' amount must be non-negative integer"
                        )

                    ctype = comp.get("type")
                    if ctype not in ("one_time", "per_semester", "per_month"):
                        errors.append(
                            f"{filename}: '{vid}' / '{gkey}' component '{cid}' invalid type '{ctype}'"
                        )

                    cats = ("compulsory", "refundable", "optional", "special")
                    if comp.get("category") not in cats:
                        errors.append(
                            f"{filename}: '{vid}' / '{gkey}' component '{cid}' invalid category"
                        )

                    if ctype == "per_semester":
                        sems = comp.get("applicable_semesters", [])
                        duration = meta.get("duration_semesters", 8)
                        for s in sems:
                            if not isinstance(s, int) or s < 1 or s > duration:
                                errors.append(
                                    f"{filename}: '{vid}' / '{gkey}' component '{cid}' "
                                    f"semester {s} out of range [1, {duration}]"
                                )

                computed = gdata.get("computed", {})
                for ckey in ("total_course_fee",):
                    if ckey not in computed:
                        errors.append(f"{filename}: '{vid}' / '{gkey}' computed missing '{ckey}'")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            file_path=filename,
        )

    def _parse_program_file(self, raw: dict, filename: str, mtime: float) -> None:
        meta = raw["_file_meta"]
        program_name = meta["program"]

        # Build groups mapping
        raw_groups = raw.get("groups", {})
        groups_map: dict[str, list[str]] = {}
        for gkey, gval in raw_groups.items():
            groups_map[gkey] = gval.get("branches", [])

        # Parse structures
        structures: list[FeeStructure] = []
        for sdata in raw.get("structures", []):
            sgroups: dict[str, FeeGroupData] = {}
            for gkey, gdata in sdata.get("groups", {}).items():
                components = [
                    self._parse_component(c) for c in gdata.get("components", [])
                ]
                computed_raw = gdata.get("computed", {})
                computed = FeeComputed(
                    total_course_fee=computed_raw.get("total_course_fee", 0),
                    first_semester_payable=computed_raw.get("first_semester_payable"),
                    regular_semester_fee=computed_raw.get("regular_semester_fee"),
                    eighth_semester_fee=computed_raw.get("eighth_semester_fee"),
                )
                sems_override: dict[int, dict[str, Any]] = {}
                for sk, sv in gdata.get("semester_overrides", {}).items():
                    sems_override[int(sk)] = dict(sv)

                sgroups[gkey] = FeeGroupData(
                    group_key=gkey,
                    branches=groups_map.get(gkey, []),
                    components=components,
                    semester_overrides=sems_override,
                    computed=computed,
                    notes=gdata.get("notes"),
                )

            struct = FeeStructure(
                version_id=sdata["version_id"],
                status=StructureStatus(sdata.get("status", "active")),
                label=sdata.get("label"),
                admission_batches=sdata.get("admission_batches", []),
                effective_date=sdata.get("effective_date"),
                published_date=sdata.get("published_date"),
                source=sdata.get("source"),
                supersedes=sdata.get("supersedes"),
                superseded_by=sdata.get("superseded_by"),
                groups=sgroups,
            )
            structures.append(struct)

        prog = ProgramFees(
            program=program_name,
            display_name=meta.get("display_name"),
            duration_semesters=meta.get("duration_semesters", 8),
            groups=groups_map,
            structures=structures,
        )

        # Store program
        if program_name in ("Hostel",):
            self._hostel = HostelFees(structures=structures)
        else:
            self._programs[program_name] = prog

        self._program_mtimes[filename] = mtime

    def _parse_component(self, raw: dict) -> FeeComponent:
        return FeeComponent(
            id=raw["id"],
            label=raw.get("label", raw["id"]),
            type=ComponentType(raw["type"]),
            category=ComponentCategory(raw.get("category", "compulsory")),
            amount=raw["amount"],
            applicable_semesters=raw.get("applicable_semesters", []),
            charged_in_semester=raw.get("charged_in_semester"),
            refundable_at=raw.get("refundable_at"),
            optional=raw.get("optional", False),
            effective_from_batch=raw.get("effective_from_batch"),
            discontinued_from_batch=raw.get("discontinued_from_batch"),
            notes=raw.get("notes"),
            months_per_year=raw.get("months_per_year"),
            availability=raw.get("availability"),
        )

    @staticmethod
    def _get_mtime(path: Path) -> float | None:
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    # ------------------------------------------------------------------
    # Batch / Version Selection
    # ------------------------------------------------------------------

    def get_current_academic_year(self) -> str:
        return self._config.get("current_academic_year", "2026-27")

    def get_program_for_branch(self, branch: str) -> str | None:
        return self._branch_to_program.get(branch.upper())

    def get_structure_for_batch(
        self, branch: str, batch: str | None = None
    ) -> Tuple[Optional[FeeStructure], Optional[FeeGroupData], str]:
        """Resolve the best matching fee structure and group for a branch and batch.

        Returns (structure, group_data, batch_used).
        If no match, returns (None, None, batch_used).
        """
        program_name = self.get_program_for_branch(branch)
        if not program_name:
            return None, None, batch or "unknown"

        prog = self._programs.get(program_name)
        if not prog or not prog.structures:
            return None, None, batch or "unknown"

        target_batch = batch or self.get_current_academic_year()

        # Phase 1: exact match
        for struct in prog.structures:
            if struct.status.value not in ("active", "superseded"):
                continue
            if target_batch in struct.admission_batches:
                group = self._find_group_for_branch(struct, branch)
                if group:
                    return struct, group, target_batch

        # Phase 2: closest by start year
        target_year = self._parse_batch_year(target_batch)
        best: FeeStructure | None = None
        best_group: FeeGroupData | None = None
        best_diff = float("inf")

        for struct in prog.structures:
            if struct.status.value not in ("active", "superseded"):
                continue
            group = self._find_group_for_branch(struct, branch)
            if not group:
                continue
            for b in struct.admission_batches:
                by = self._parse_batch_year(b)
                diff = abs(by - target_year)
                if diff < best_diff:
                    best = struct
                    best_group = group
                    best_diff = diff

        return best, best_group, target_batch

    def _find_group_for_branch(
        self, struct: FeeStructure, branch: str
    ) -> FeeGroupData | None:
        for gkey, group in struct.groups.items():
            if branch.upper() in group.branches:
                return group
        return None

    @staticmethod
    def _parse_batch_year(batch: str) -> int:
        try:
            return int(batch.split("-")[0])
        except (ValueError, IndexError):
            return 0

    # ------------------------------------------------------------------
    # Fee Calculation
    # ------------------------------------------------------------------

    def get_total_fee(
        self,
        branch: str,
        batch: str | None = None,
        include_optional: bool = False,
    ) -> FeeQueryResult:
        """Compute the total course fee for a branch."""
        struct, group, batch_used = self.get_structure_for_batch(branch, batch)
        if not struct or not group:
            return FeeQueryResult(
                branch=branch,
                program=self.get_program_for_branch(branch) or "unknown",
                batch=batch_used,
                error=f"No fee structure found for {branch} (batch {batch_used})",
            )

        total = self._compute_total(group, include_optional)
        return FeeQueryResult(
            branch=branch,
            program=self.get_program_for_branch(branch) or "",
            batch=batch_used,
            structure=struct,
            group_data=group,
            total_fee=total,
            component_breakdown=self._get_breakdown(group, include_optional),
        )

    def get_semester_fee(
        self,
        branch: str,
        semester: int,
        batch: str | None = None,
        include_optional: bool = False,
    ) -> FeeQueryResult:
        """Compute the fee for a specific semester."""
        struct, group, batch_used = self.get_structure_for_batch(branch, batch)
        if not struct or not group:
            return FeeQueryResult(
                branch=branch,
                program=self.get_program_for_branch(branch) or "unknown",
                batch=batch_used,
                semester=semester,
                error=f"No fee structure found for {branch} (batch {batch_used})",
            )

        program_name = self.get_program_for_branch(branch) or ""
        prog = self._programs.get(program_name)
        duration = prog.duration_semesters if prog else 8

        if semester < 1 or semester > duration:
            return FeeQueryResult(
                branch=branch,
                program=program_name,
                batch=batch_used,
                semester=semester,
                error=f"Semester {semester} out of range [1, {duration}]",
            )

        sem_fee = self._compute_semester_total(group, semester, include_optional)
        return FeeQueryResult(
            branch=branch,
            program=program_name,
            batch=batch_used,
            structure=struct,
            group_data=group,
            semester=semester,
            semester_fee=sem_fee,
        )

    def get_first_semester_payable(
        self,
        branch: str,
        batch: str | None = None,
    ) -> FeeQueryResult:
        """Compute the amount payable at admission time (first semester)."""
        return self.get_semester_fee(branch, 1, batch, include_optional=False)

    def get_hostel_fee(
        self,
        room_type: str | None = None,
        batch: str | None = None,
    ) -> FeeQueryResult:
        """Get hostel fee information."""
        if not self._hostel.structures:
            return FeeQueryResult(
                branch="Hostel",
                program="Hostel",
                batch=batch,
                error="No hostel fee structure available",
            )

        target_batch = batch or self.get_current_academic_year()
        struct = self._hostel.structures[0]
        group = struct.groups.get("hostel")
        if not group:
            return FeeQueryResult(
                branch="Hostel",
                program="Hostel",
                batch=target_batch,
                error="No hostel group data",
            )

        breakdown = self._get_breakdown(group, include_optional=True)
        return FeeQueryResult(
            branch="Hostel",
            program="Hostel",
            batch=target_batch,
            structure=struct,
            group_data=group,
            component_breakdown=breakdown,
        )

    # ------------------------------------------------------------------
    # Internal Computation
    # ------------------------------------------------------------------

    def _compute_total(self, group: FeeGroupData, include_optional: bool) -> int:
        """Compute total course fee from components."""
        total = 0
        duration = 8  # default, will refine later

        for comp in group.components:
            if comp.is_optional and not include_optional:
                continue

            if comp.type == ComponentType.ONE_TIME:
                total += comp.amount
            elif comp.type == ComponentType.PER_SEMESTER:
                if not comp.applicable_semesters:
                    total += comp.amount * duration
                else:
                    count = 0
                    for sem in comp.applicable_semesters:
                        # Apply semester override if it modifies this component
                        override_amount = self._get_override_amount(
                            group, sem, comp.id, comp.amount
                        )
                        total += override_amount
                        count += 1
                    if count == 0:
                        total += comp.amount * duration
            elif comp.type == ComponentType.PER_MONTH:
                months = comp.months_per_year or 12
                total += comp.amount * months * (duration // 2)

        # If computed value exists, prefer it (it's the verified total)
        if not include_optional and group.computed.total_course_fee > 0:
            return group.computed.total_course_fee

        return total

    def _compute_semester_total(
        self, group: FeeGroupData, semester: int, include_optional: bool
    ) -> int:
        """Compute fee for a single semester."""
        total = 0
        for comp in group.components:
            if comp.is_optional and not include_optional:
                continue

            if comp.type == ComponentType.ONE_TIME:
                if comp.charged_in_semester is not None and comp.charged_in_semester == semester:
                    total += comp.amount
                elif comp.charged_in_semester is None and semester == 1:
                    pass  # one-time components without a fixed semester are only counted in total, not per-semester
            elif comp.type == ComponentType.PER_SEMESTER:
                if semester in comp.applicable_semesters:
                    override_amount = self._get_override_amount(
                        group, semester, comp.id, comp.amount
                    )
                    total += override_amount

        return total

    def _get_override_amount(
        self, group: FeeGroupData, semester: int, component_id: str, default: int
    ) -> int:
        """Check if there's a semester override for this component amount."""
        if semester in group.semester_overrides:
            sems_over = group.semester_overrides[semester]
            if component_id in sems_over:
                val = sems_over[component_id]
                if isinstance(val, (int, float)):
                    return int(val)
        return default

    def _get_breakdown(
        self, group: FeeGroupData, include_optional: bool
    ) -> list[dict[str, Any]]:
        """Return a human-readable breakdown of fee components."""
        items: list[dict[str, Any]] = []
        for comp in group.components:
            if comp.is_optional and not include_optional:
                continue

            item = {
                "id": comp.id,
                "label": comp.label,
                "type": comp.type.value,
                "category": comp.category.value,
                "amount": comp.amount,
                "is_optional": comp.is_optional,
            }
            if comp.applicable_semesters:
                item["applicable_semesters"] = comp.applicable_semesters
            if comp.charged_in_semester:
                item["charged_in_semester"] = comp.charged_in_semester
            if comp.notes:
                item["notes"] = comp.notes
            if comp.months_per_year:
                item["months_per_year"] = comp.months_per_year
            items.append(item)
        return items

    # ------------------------------------------------------------------
    # Error / Status
    # ------------------------------------------------------------------

    def get_load_errors(self) -> list[str]:
        return list(self._load_errors)

    def is_loaded(self) -> bool:
        return self._loaded

    def is_valid(self) -> bool:
        return len(self._load_errors) == 0

    def get_loaded_programs(self) -> list[str]:
        return list(self._programs.keys())

    def get_summary(self) -> dict[str, Any]:
        """Return a diagnostic summary of loaded fee data."""
        summary: dict[str, Any] = {
            "loaded": self._loaded,
            "errors": len(self._load_errors),
            "error_details": self._load_errors[:5],
            "programs": {},
            "hostel_structures": len(self._hostel.structures),
        }
        for pname, prog in self._programs.items():
            summary["programs"][pname] = {
                "duration": prog.duration_semesters,
                "groups": list(prog.groups.keys()),
                "structures": [
                    {
                        "version_id": s.version_id,
                        "status": s.status.value,
                        "batches": s.admission_batches,
                        "groups": list(s.groups.keys()),
                    }
                    for s in prog.structures
                ],
            }
        return summary

    # ------------------------------------------------------------------
    # Migration Verification
    # ------------------------------------------------------------------

    def verify_against_production(
        self, production_map: dict[str, tuple[int, int, int]]
    ) -> dict[str, Any]:
        """Verify FeeEngine computed totals match the production FEE_GROUP_MAP.

        Args:
            production_map: The FEE_GROUP_MAP dict from groq_service,
                mapping branch -> (total, admission, per_semester)

        Returns:
            Dict with 'matched', 'mismatched', and 'missing' keys.
        """
        matched: list[str] = []
        mismatched: list[dict[str, Any]] = []
        missing: list[str] = []

        for branch, (expected_total, expected_admission, expected_per_sem) in production_map.items():
            result = self.get_total_fee(branch)
            if result.error:
                missing.append(branch)
                continue

            if result.total_fee == expected_total:
                matched.append(branch)
            else:
                mismatched.append({
                    "branch": branch,
                    "expected": expected_total,
                    "got": result.total_fee,
                })

        return {
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
            "total": len(matched) + len(mismatched) + len(missing),
            "matched_count": len(matched),
            "mismatched_count": len(mismatched),
            "missing_count": len(missing),
            "all_match": len(mismatched) == 0 and len(missing) == 0,
        }
