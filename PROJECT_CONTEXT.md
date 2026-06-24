# POV-4: Query Performance Monitoring & Alerting Agent

## Overview

This project implements POV-4, an AI-assisted Query Performance Monitoring & Alerting Agent for Snowflake environments.

The purpose of POV-4 is to continuously monitor Snowflake workloads, detect performance bottlenecks, perform root cause analysis (RCA), generate optimization recommendations, and provide structured findings that can be consumed by POV-3 (Query Auto-Optimization & PR Draft Agent).

POV-4 is an observability and intelligence system.

POV-4 DOES NOT perform query optimization.

POV-4 DOES NOT modify code.

POV-4 DOES NOT generate pull requests.

POV-4 identifies optimization opportunities and provides actionable findings.

POV-3 will consume these findings and perform optimization activities.

---

# Business Problem

Organizations running Snowflake workloads often encounter:

- Long-running queries
- Warehouse queue waits
- Remote spills
- Local spills
- Warehouse saturation
- Concurrency bottlenecks
- Excessive credit consumption
- Runtime regressions

These issues are usually identified manually and reactively.

This leads to:

- Increased operational costs
- Poor warehouse utilization
- Delayed root cause analysis
- Slow optimization cycles

The goal of POV-4 is to proactively detect these issues and provide explainable recommendations.

---

# High-Level Responsibilities

POV-4 is responsible for:

1. Monitoring Snowflake telemetry.
2. Detecting performance issues.
3. Performing root cause analysis.
4. Generating optimization recommendations.
5. Producing findings with LLM analysis and confidence scoring.
6. Sending notifications.
7. Forwarding findings to POV-3.

---

# Architecture

Snowflake Metadata

- QUERY_HISTORY
- WAREHOUSE_LOAD_HISTORY
- METERING_HISTORY
- GET_QUERY_OPERATOR_STATS

↓

Data Collection Layer

↓

Performance Knowledge Store

↓

Monitoring Engine

↓

Issue Detection Engine

↓

Performance Analysis Agent (LLM)

↓

Performance Findings Store

↓

Teams / Email Notifications

↓

POV-3 Integration Layer

↓

POST /performance-alert

↓

POV-3 Optimization Agent

---

# Design Principles

## Deterministic Monitoring

Monitoring and issue detection must be rule-based and deterministic.

LLMs must not be used for issue detection.

---

## AI-Assisted Analysis

LLMs are only used for:

- Root Cause Analysis
- Recommendation Generation

A single analysis agent should be used initially.

Avoid unnecessary multi-agent complexity.

---

## Explainability

Every finding must include:

- Supporting metrics
- RCA summary
- Recommendations
- AI Analysis Confidence score (within AnalysisResult)

The system should always explain why a recommendation was generated.

---

## Persistence

All findings must be stored.

Findings are considered the system's source of truth.

Historical findings will eventually support:

- Similar incident retrieval
- Organizational learning
- Future RAG implementations

---

## POV-3 Contract

POV-4 produces structured Performance Findings containing:
- Detected issues
- Evidence quality
- Supporting metrics
- RCA summaries, recommendations, and AI analysis confidence scores

POV-3 consumes these findings to perform downstream optimization activities.

POV-4 is upstream.

POV-3 is downstream.

POV-4 should never perform optimization.

---

# Performance Finding Contract

The primary output of POV-4 is a Performance Finding.

A Performance Finding represents one analyzed workload event and may contain one or more detected performance issues.

Performance Findings are:

- Persisted as the system source of truth.
- Used for alerting.
- Consumed by POV-3.
- Used for historical analysis and future learning systems.

Example structure:

{
  "finding_id": "...",
  "timestamp": "...",
  "query_id": "...",
  "warehouse": "...",
  "overall_severity": "...",
  "evidence_quality": "...",
  "issues": [
    {
      "type": "REMOTE_SPILL",
      "severity": "HIGH"
    }
  ],
  "metrics": {},
  "analysis": {
    "root_cause_summary": "...",
    "recommendations": [],
    "llm_metadata": {},
    "confidence": {
      "score": 0.87,
      "reason": "..."
    }
  }
}

The exact schema may evolve during implementation but must remain backward compatible for POV-3 consumers.

---

# Technology Stack

Language:
Python

Framework:
FastAPI

LLM Framework:
LangChain

LLM Provider:
Google Gemini API

Database:
Snowflake

Containerization:
Docker

Notifications:
Microsoft Teams
Email

---

# Documentation Requirements

Documentation is a first-class deliverable.

Every implementation must update:

- README.md
- Architecture documentation
- Module documentation

Documentation should explain:

- What was built
- Why it was built
- Design decisions
- Future enhancements

Assume a new engineer should be able to understand the project entirely from documentation.

---

# Required Design Documents

The project must maintain:

## HLD

High-Level Design document describing:

- Architecture
- Components
- Responsibilities
- Integration points

## LLD

Low-Level Design document describing:

- Data models
- APIs
- Module structure
- Processing flow
- Error handling

These documents must be updated throughout development.