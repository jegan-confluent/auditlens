# AuditLens Foundation Boundary

The following are not foundation-release components:

- full decision engine
- MCP-first workflows
- Flink as the default processing path
- Tableflow as the default analytics path
- smart-offset detection with local state files
- criticality-per-topic routing as the primary product contract

They may remain in the repository for reference, compatibility experiments, or
future work, but they are not part of the supported foundation path for Docker
or Kubernetes deployment.
