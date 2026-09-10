# Evolution API contract

Skills, MCP integrations, and knowledge bases are versioned assets. One asset
can point to different immutable versions in the TEST, LIVESH, and LIVE channels.

## Invariants

- Versions are immutable; every modification creates a new version.
- Agent, monitor, and human feedback first creates a proposal.
- Accepting a proposal creates or links a TEST candidate and never writes
  directly to LIVESH or LIVE.
- Promotion is server-authoritative. The backend re-checks evidence and gates.
- LIVESH receives copied production traffic but cannot return output to users.
- Rollback moves a channel pointer to an earlier immutable version and is audited.
- Mutating endpoints should accept an Idempotency-Key header.

## Reserved endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | /api/evolution/overview | Assets, channel pointers, pending proposals |
| GET | /api/evolution/assets/:assetId | Complete asset and version detail |
| POST | /api/evolution/assets | Register a Skill, MCP, or knowledge-base asset |
| POST | /api/evolution/assets/:assetId/versions | Create an immutable TEST candidate |
| GET | /api/evolution/assets/:assetId/versions/:versionId/spec | Read the typed Skill, MCP, or knowledge configuration |
| PUT | /api/evolution/assets/:assetId/versions/:versionId/spec | Save a typed configuration to a draft version |
| POST | /api/evolution/assets/:assetId/versions/:versionId/evaluations | Evaluate one version |
| POST | /api/evolution/assets/:assetId/versions/:versionId/promote | Promote into LIVESH or LIVE |
| POST | /api/evolution/assets/:assetId/versions/:versionId/mcp-health-checks | Check MCP connectivity, authentication, and latency |
| POST | /api/evolution/assets/:assetId/versions/:versionId/index-runs | Rebuild a knowledge version's index |
| POST | /api/evolution/assets/:assetId/rollback | Move a channel pointer to a stable version |
| POST | /api/evolution/proposals/:proposalId/review | Accept or reject a proposal |

Every request carries x-workspace-id. Exact request and response types are in
src/services/evolution/index.ts.

## Promotion payload

    {
      "target": "livesh",
      "evidence_ids": ["gate-quality-01", "gate-safety-01"],
      "traffic_percent": 10
    }

The backend rejects promotion when evidence is stale, belongs to another
version, or fails the policy attached to the target channel.

## Feedback loop

    production trace / human edit / monitor incident
      -> proposal -> review -> immutable TEST version
      -> evaluation evidence -> LIVESH shadow comparison
      -> LIVE promotion -> continuous monitoring
      -> new proposal or rollback
