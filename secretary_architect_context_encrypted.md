# Secretary Architect Context — multipart encrypted canonical

Format: SECRETARY-ARCHITECT-CONTEXT-v43-MULTIPART
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

The previous single-file v42 payload was superseded by this multipart v43 checkpoint.
