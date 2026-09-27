# Secretary Architect Context — multipart encrypted canonical

Format: SECRETARY-ARCHITECT-CONTEXT-v44-MULTIPART
Parts: 3
Order:
1. secretary_architect_context_encrypted_01.md
2. secretary_architect_context_encrypted_02.md
3. secretary_architect_context_encrypted_03.md

Each part is independently encrypted with:
- PBKDF2-HMAC-SHA256
- 600000 iterations
- gzip
- Fernet
- hex-of-base64url payload

Use the same architect password for all three parts.
Strategy-Supplement: secretary_architect_strategy_encrypted.md

The previous multipart v43 payload was superseded by this v44 checkpoint.
Snapshot authority at encryption time: main/HOLD eb37b81feea0b760277221fbad5e51c98c52bdac; G3A-R2 implementation 703a0a12ca236c328744cdbc2994ebc40e71ff42; production 489741540e30a775e2ea086f3976d7305512afe2; Alembic 0050.
