"""
POV-4: Enums and constants for the domain layer.

All enum values are derived from the approved domain model and detection
framework documentation. Do not add values here without updating those
documents first.
"""

from enum import Enum


class IssueType(str, Enum):
    """
    Catalog of detectable performance issue types.

    Values are defined in docs/detection/v1_detection_catalog.md.
    Each value maps to a deterministic detection rule in the Issue Detection Engine.
    """

    REMOTE_SPILL = "REMOTE_SPILL"
    """High volume of data written to remote storage due to memory exhaustion."""

    LOCAL_SPILL = "LOCAL_SPILL"
    """Data written to local SSD during sort/join operations."""

    POOR_PARTITION_PRUNING = "POOR_PARTITION_PRUNING"
    """Excessive I/O scanning due to non-selective query predicates."""

    EXPENSIVE_JOIN = "EXPENSIVE_JOIN"
    """Join operator causing explosive multiplication of output rows."""

    CARTESIAN_JOIN = "CARTESIAN_JOIN"
    """Unintentional Cartesian product producing catastrophic row counts."""

    LONG_RUNNING_QUERY = "LONG_RUNNING_QUERY"
    """Query execution time significantly exceeding normal boundaries."""

    QUEUE_OVERLOAD = "QUEUE_OVERLOAD"
    """Query delayed in the overload queue due to warehouse capacity ceiling."""

    PROVISIONING_DELAY = "PROVISIONING_DELAY"
    """Wait time due to warehouse startup or resume provisioning."""

    TRANSACTION_BLOCKED = "TRANSACTION_BLOCKED"
    """DML statement blocked waiting for a lock held by another transaction."""

    HIGH_NETWORK_SHUFFLE = "HIGH_NETWORK_SHUFFLE"
    """Excessive inter-node data redistribution across multi-node warehouses."""

    COST_ANOMALY = "COST_ANOMALY"
    """Single query credit cost exceeds historical baseline plus stddev."""


class IssueSeverity(str, Enum):
    """
    Severity levels for detected issues and overall findings.

    Severity is computed deterministically by the Detection Engine.
    The overall PerformanceFinding severity inherits the highest
    individual DetectedIssue severity.

    Thresholds are defined in docs/detection-framework.md Section 3.
    """

    LOW = "LOW"
    """Below moderate threshold. Informational."""

    MEDIUM = "MEDIUM"
    """Moderate threshold breached, low cost impact."""

    HIGH = "HIGH"
    """Large threshold breached OR significant cost impact."""

    CRITICAL = "CRITICAL"
    """Extreme threshold breached, causing systemic slowdowns or massive cost overruns."""


class AlertDestination(str, Enum):
    """
    Supported notification destinations for AlertEvents.

    Defined in docs/domain-model/domain_model.md Section 6.
    """

    TEAMS = "TEAMS"
    """Microsoft Teams webhook."""

    EMAIL = "EMAIL"
    """SMTP / Email notification."""

    POV3_WEBHOOK = "POV3_WEBHOOK"
    """HTTP POST to the POV-3 performance-alert endpoint."""


class AlertStatus(str, Enum):
    """
    Delivery lifecycle states for an AlertEvent.

    Failed events are stored in the Dead Letter Queue (DLQ) and
    retried by the APScheduler sweeper cron job.
    """

    PENDING = "PENDING"
    """Alert has been created but not yet dispatched."""

    SENT = "SENT"
    """Alert successfully delivered to the destination."""

    FAILED = "FAILED"
    """Delivery failed. Event is queued for retry via DLQ."""


class EvidenceQuality(str, Enum):
    """
    Indicates the completeness of the telemetry collected.
    """
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    LIMITED = "LIMITED"
