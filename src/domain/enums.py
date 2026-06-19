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

    Values are defined in docs/detection-framework.md Section 1.
    Each value maps to a deterministic detection rule in the Issue Detection Engine.
    """

    REMOTE_SPILL = "REMOTE_SPILL"
    """High volume of data written to remote storage due to memory exhaustion."""

    LOCAL_SPILL = "LOCAL_SPILL"
    """Data written to local SSD during sort/join operations."""

    LONG_RUNNING_QUERY = "LONG_RUNNING_QUERY"
    """Query execution time significantly exceeding normal boundaries."""

    QUEUE_WAIT = "QUEUE_WAIT"
    """Query delayed due to warehouse overloading."""

    WAREHOUSE_SATURATION = "WAREHOUSE_SATURATION"
    """Cluster running at maximum concurrency."""

    COST_ANOMALY = "COST_ANOMALY"
    """Account or warehouse-level credit usage exceeds standard patterns."""

    HIGH_CREDIT_CONSUMPTION = "HIGH_CREDIT_CONSUMPTION"
    """Individual query compute cost is extremely high."""

    PROVISIONING_DELAY = "PROVISIONING_DELAY"
    """Wait time due to warehouse startup or resume."""

    CONCURRENCY_BOTTLENECK = "CONCURRENCY_BOTTLENECK"
    """Large number of queued queries despite cluster scaling limits."""


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
