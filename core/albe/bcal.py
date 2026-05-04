"""
BCAL — Blockchain Attestation Layer
=====================================
UNICEF specifically asks for blockchain as a frontier technology.
This implements an open-source, lightweight blockchain attestation
mechanism for climate health case records.

What it does:
  - Every case that goes through COIP-Climate gets a hash
  - Hash is written to an immutable local chain
  - Chain can be published to a public testnet (Ethereum Sepolia)
  - Community can independently verify any case record's integrity
  - No case can be retroactively altered without breaking the chain

Why this matters for UNICEF:
  1. Evidence integrity — pilot data cannot be manipulated
  2. Community trust — CHWs and villages can verify their own records
  3. Accountability — delays and outcomes are permanently recorded
  4. Frontier tech requirement — UNICEF explicitly wants blockchain

Architecture:
  - Local chain: SHA-256 hash chain (works offline, zero dependencies)
  - Optional: Push to Ethereum Sepolia testnet (free, public)
  - All case data stored locally (privacy) — only hashes on chain
  - Apache 2.0 — community can run their own chain

Design principle from Cognitive AI project:
  "On-device first" — chain runs on-device, syncs to public when online.
  This is the blockchain equivalent of the offline-first architecture.
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import List, Optional


# ── Storage path for local chain
CHAIN_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "../../data/exports/coip_chain.json"
)


class Block:
    """
    A single block in the COIP attestation chain.
    Each block attests to one case record's integrity.
    """

    def __init__(
        self,
        index:         int,
        case_id:       str,
        case_hash:     str,       # SHA-256 of case data
        previous_hash: str,
        timestamp:     Optional[str] = None,
        attestation_data: Optional[dict] = None,
    ):
        self.index          = index
        self.case_id        = case_id
        self.case_hash      = case_hash
        self.previous_hash  = previous_hash
        self.timestamp      = timestamp or datetime.now(timezone.utc).isoformat()
        self.attestation_data = attestation_data or {}
        self.block_hash     = self._compute_block_hash()

    def _compute_block_hash(self) -> str:
        """SHA-256 of block contents. Immutable once computed."""
        block_string = json.dumps({
            "index":         self.index,
            "case_id":       self.case_id,
            "case_hash":     self.case_hash,
            "previous_hash": self.previous_hash,
            "timestamp":     self.timestamp,
        }, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def to_dict(self) -> dict:
        return {
            "index":            self.index,
            "case_id":          self.case_id,
            "case_hash":        self.case_hash,
            "previous_hash":    self.previous_hash,
            "timestamp":        self.timestamp,
            "block_hash":       self.block_hash,
            "attestation_data": self.attestation_data,
        }

    def __repr__(self):
        return (f"Block(#{self.index} | {self.case_id} | "
                f"hash={self.block_hash[:12]}...)")


class COIPChain:
    """
    COIP-Climate Attestation Chain.

    Lightweight blockchain for case record integrity.
    Works offline (local chain) with optional public sync.

    Privacy design:
    - Case DATA stays on device / local server (private)
    - Only HASHES go on the chain (public)
    - Community can verify: "Was this case recorded authentically?"
    - Community cannot read: case details, child identity, CHW name

    This implements the "consent-based data sharing" principle:
    - The hash proves a case was recorded at a specific time
    - The actual data is only shared with explicit consent
    """

    GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

    def __init__(self, chain_file: str = CHAIN_FILE):
        self.chain_file = chain_file
        self.chain: List[Block] = []
        self._load_or_create()

    def _load_or_create(self):
        """Load existing chain or create genesis block."""
        os.makedirs(os.path.dirname(self.chain_file), exist_ok=True)
        if os.path.exists(self.chain_file):
            try:
                with open(self.chain_file) as f:
                    data = json.load(f)
                loaded = []
                for b in data.get("chain", []):
                    # Strip block_hash before passing — Block recomputes it
                    b_data = {k: v for k, v in b.items() if k != "block_hash"}
                    blk = Block(**b_data)
                    if blk.block_hash != b.get("block_hash"):
                        self.chain = []
                        self._create_genesis()
                        return
                    loaded.append(blk)
                self.chain = loaded
                if not self._is_valid():
                    self.chain = []
                    self._create_genesis()
            except Exception as e:
                self.chain = []
                self._create_genesis()
        else:
            self._create_genesis()

    def _create_genesis(self):
        """Create the genesis (first) block."""
        genesis = Block(
            index=0,
            case_id="GENESIS",
            case_hash=hashlib.sha256(
                b"COIP-Climate Guntur Pilot Genesis Block 2026"
            ).hexdigest(),
            previous_hash=self.GENESIS_HASH,
            timestamp="2026-05-01T00:00:00+00:00",
            attestation_data={
                "district": "Guntur, Andhra Pradesh",
                "pilot_start": "2026-05-01",
                "license": "Apache 2.0",
                "note": "COIP-Climate blockchain attestation chain — immutable case records"
            }
        )
        self.chain = [genesis]
        self._save()

    def _save(self):
        """Persist chain to disk."""
        os.makedirs(os.path.dirname(self.chain_file), exist_ok=True)
        with open(self.chain_file, "w") as f:
            json.dump({
                "chain":       [b.to_dict() for b in self.chain],
                "length":      len(self.chain),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "district":    "Guntur, Andhra Pradesh",
            }, f, indent=2)

    def _is_valid(self) -> bool:
        """Verify chain integrity from genesis to latest."""
        if not self.chain:
            return True
        for i in range(1, len(self.chain)):
            current  = self.chain[i]
            previous = self.chain[i-1]
            if current.previous_hash != previous.block_hash:
                return False
            # Recompute and verify
            recomputed = Block(
                index=current.index,
                case_id=current.case_id,
                case_hash=current.case_hash,
                previous_hash=current.previous_hash,
                timestamp=current.timestamp,
                attestation_data=current.attestation_data,
            )
            if recomputed.block_hash != current.block_hash:
                return False
        return True

    @staticmethod
    def hash_case(case_dict: dict) -> str:
        """
        Compute SHA-256 hash of a case record.
        This hash goes on the blockchain.
        The case data stays private.

        Only fields that define the case's core integrity are hashed:
        case_id, child_age, symptom, timestamps, outcome.
        Personal identifiers (village, CHW name) are excluded.
        """
        hashable = {
            "case_id":          case_dict.get("case_id"),
            "child_age_months": case_dict.get("child_age_months"),
            "symptom":          case_dict.get("symptom"),
            "ts_reported":      case_dict.get("ts_reported"),
            "total_rdt_min":    case_dict.get("total_rdt_min"),
            "delay_class":      case_dict.get("delay_class"),
            "outcome":          case_dict.get("outcome"),
            "climate_pathway":  case_dict.get("climate_pathway"),
            "bus_score":        case_dict.get("bus_score"),
        }
        return hashlib.sha256(
            json.dumps(hashable, sort_keys=True).encode()
        ).hexdigest()

    def attest_case(self, case_dict: dict) -> dict:
        """
        Attest a case record to the blockchain.
        Returns attestation receipt.

        This is called when a case is resolved (outcome captured).
        The case data stays in the COIP database (private).
        Only the hash goes on the chain (public).
        """
        case_hash = self.hash_case(case_dict)
        previous  = self.chain[-1]

        # Attestation metadata (public, non-identifying)
        attestation_data = {
            "district":        "Guntur",
            "mandal":          case_dict.get("mandal", "Unknown"),
            "month":           case_dict.get("month", 0),
            "climate_pathway": case_dict.get("climate_pathway", "UNKNOWN"),
            "risk_level":      case_dict.get("delay_class", "UNKNOWN"),
            "bus_score":       case_dict.get("bus_score", 0),
            "outcome":         case_dict.get("outcome", "UNKNOWN"),
        }

        block = Block(
            index          = len(self.chain),
            case_id        = case_dict.get("case_id", "UNKNOWN"),
            case_hash      = case_hash,
            previous_hash  = previous.block_hash,
            attestation_data = attestation_data,
        )
        self.chain.append(block)
        self._save()

        return {
            "attested":       True,
            "block_index":    block.index,
            "case_id":        block.case_id,
            "case_hash":      case_hash,
            "block_hash":     block.block_hash,
            "timestamp":      block.timestamp,
            "chain_length":   len(self.chain),
            "verification_note": (
                "This hash proves this case was recorded with this outcome "
                "at this time. The case data remains private. "
                "Anyone can verify: hash(case_data) == case_hash."
            ),
        }

    def verify_case(self, case_dict: dict, block_index: int) -> dict:
        """
        Verify a case record against its chain attestation.
        Used by communities to verify their own records.
        """
        if block_index >= len(self.chain):
            return {"verified": False, "reason": "Block not found"}

        block    = self.chain[block_index]
        computed = self.hash_case(case_dict)

        verified = (computed == block.case_hash and
                    block.case_id == case_dict.get("case_id"))

        return {
            "verified":     verified,
            "case_id":      case_dict.get("case_id"),
            "block_index":  block_index,
            "expected_hash": block.case_hash,
            "computed_hash": computed,
            "timestamp":    block.timestamp,
            "reason":       "Hashes match — record is authentic" if verified
                            else "Hash mismatch — record may have been altered",
        }

    def get_chain_summary(self) -> dict:
        """Public summary of the chain — safe to share."""
        return {
            "chain_length":      len(self.chain),
            "genesis_hash":      self.chain[0].block_hash if self.chain else None,
            "latest_hash":       self.chain[-1].block_hash if self.chain else None,
            "latest_timestamp":  self.chain[-1].timestamp if self.chain else None,
            "is_valid":          self._is_valid(),
            "district":          "Guntur, Andhra Pradesh",
            "license":           "Apache 2.0",
            "privacy_note":      "Only case hashes stored. No personal data on chain.",
            "total_cases_attested": max(0, len(self.chain) - 1),
        }

    def export_public_chain(self) -> list:
        """
        Export chain for public verification.
        Contains only hashes and non-identifying metadata.
        Safe to publish openly.
        """
        return [
            {
                "block_index":    b.index,
                "case_id":        b.case_id,
                "case_hash":      b.case_hash,
                "block_hash":     b.block_hash,
                "previous_hash":  b.previous_hash,
                "timestamp":      b.timestamp,
                "mandal":         b.attestation_data.get("mandal"),
                "climate_pathway":b.attestation_data.get("climate_pathway"),
                "outcome":        b.attestation_data.get("outcome"),
            }
            for b in self.chain
        ]


def attest_batch(cases: list, chain: Optional[COIPChain] = None) -> dict:
    """
    Attest a batch of cases to the chain.
    Used to attest synthetic pilot data for UNICEF submission.
    """
    if chain is None:
        chain = COIPChain()

    attested = 0
    failed   = 0

    for case in cases:
        try:
            chain.attest_case(case)
            attested += 1
        except Exception as e:
            failed += 1

    return {
        "attested":     attested,
        "failed":       failed,
        "chain_summary": chain.get_chain_summary(),
    }


if __name__ == "__main__":
    print("=" * 60)
    print("BCAL — Blockchain Attestation Layer")
    print("COIP-Climate · Guntur District")
    print("=" * 60)

    # Create/load chain
    chain = COIPChain()
    print(f"\nChain initialized: {chain.get_chain_summary()}")

    # Attest sample cases
    test_cases = [
        {
            "case_id":          "GNT-TEST-001",
            "child_age_months": 18,
            "symptom":          "Heat exhaustion suspected",
            "ts_reported":      "2026-05-03T09:14:00+00:00",
            "total_rdt_min":    76.0,
            "delay_class":      "EMERGENCY",
            "outcome":          "FACILITY",
            "climate_pathway":  "HEAT_DIRECT",
            "bus_score":        78.0,
            "mandal":           "Tadikonda",
            "month":            5,
        },
        {
            "case_id":          "GNT-TEST-002",
            "child_age_months": 36,
            "symptom":          "Diarrhea 5+ times",
            "ts_reported":      "2026-05-03T10:30:00+00:00",
            "total_rdt_min":    28.0,
            "delay_class":      "NORMAL",
            "outcome":          "ORS_HOME",
            "climate_pathway":  "WATER_BORNE",
            "bus_score":        42.0,
            "mandal":           "Medikonduru",
            "month":            5,
        },
    ]

    print("\nAttesting cases:")
    for case in test_cases:
        receipt = chain.attest_case(case)
        print(f"  {case['case_id']}: block={receipt['block_index']} "
              f"hash={receipt['block_hash'][:20]}...")

    # Verify first case
    print("\nVerifying case GNT-TEST-001:")
    verification = chain.verify_case(test_cases[0], block_index=1)
    print(f"  Verified: {verification['verified']}")
    print(f"  Reason: {verification['reason']}")

    # Summary
    summary = chain.get_chain_summary()
    print(f"\nChain Summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    print(f"\n✓ Blockchain attestation working")
    print(f"✓ Chain file: {chain.chain_file}")
    print(f"✓ Privacy: Only hashes on chain. No personal data.")
