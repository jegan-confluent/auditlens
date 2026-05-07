# AuditLens Security Notes

## Secret Handling

If `.env` credentials are ever exposed, rotate them immediately in the Confluent Cloud console and update all deployment environments. Do not rely on git history removal.
