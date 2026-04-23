# Document Chat Context Analysis

## Summary
**YES** — When you select an uploaded document and chat, the chat ONLY has context with that document. It does NOT have context to other documents in the system.

---

## UI Code Flow (Frontend)

### File: [ui/web/src/app/page.tsx](ui/web/src/app/page.tsx#L650-L680)

**How document selection works:**

```typescript
// Line ~650: When user clicks on a claim card, it sets activeClaim
const [activeClaim, setActiveClaim] = useState<string | null>(null);

// User clicks on a claim card in the list
{claims.map((c) => (
  <div
    key={c.id}
    className={`claim-card ${activeClaim === c.id ? "active" : ""}`}
    onClick={() => {
      setActiveClaim(c.id);  // ← This stores the selected document/claim
      const fname = c.documents?.[0]?.file_name || "Untitled";
      setMessages([
        {
          role: "bot",
          text: `Viewing claim "${fname}". Ask me anything about it.`,
        },
      ]);
    }}
  >
```

### File: [ui/web/src/app/page.tsx](ui/web/src/app/page.tsx#L637-L667)

**When sending a message, it passes only the selected claim's ID:**

```typescript
// Line ~637: Chat handler
const sendMessage = async (e: FormEvent) => {
  e.preventDefault();
  const text = input.trim();
  if (!text) return;
  setInput("");
  setMessages((prev) => [...prev, { role: "user", text }]);
  setTyping(true);

  const sessionId = activeClaim || "general";

  /* ── Try streaming first, fallback to regular endpoint ── */
  try {
    const resp = await fetch(`${CHAT_API}/${sessionId}/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        message: text, 
        claim_id: activeClaim  // ← Only sends the SELECTED claim's ID
      }),
    });
```

---

## Backend Code Flow (Chat Service)

### File: [services/chat/app/main.py](services/chat/app/main.py#L470-L490)

**Streaming endpoint receives the claim_id:**

```python
@router.post("/{session_id}/stream")
async def stream_message(
    session_id: str,
    body: ChatRequest,  # Contains: { message, claim_id }
    request: Request,
    db: Session = Depends(get_db),
):
    import asyncio
    import json
    from services.chat.app.config import settings as llm_settings
    
    claim_id = None
    claim_context = None
    if body.claim_id:
        claim_id = _parse_uuid(body.claim_id)
        # ↓ This builds context ONLY for this specific claim
        claim_context = _get_claim_context(db, claim_id, user_query=body.message)
    
    # ... rest of handler
```

### File: [services/chat/app/main.py](services/chat/app/main.py#L249-L310)

**`_get_claim_context()` function - fetches context ONLY from the selected claim:**

```python
def _get_claim_context(db: Session, claim_id: uuid.UUID, user_query: str = "") -> dict[str, Any] | None:
    """Build comprehensive claim context with full document text and question-aware retrieval."""
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        return None

    # Get parsed fields for THIS claim ONLY
    pf = db.query(ParsedField).filter(ParsedField.claim_id == claim_id).all()
    fields: dict[str, Any] = {}
    for r in pf:
        if r.field_name not in fields:
            fields[r.field_name] = r.field_value

    # Get documents for THIS claim ONLY
    docs = db.query(Document).filter(Document.claim_id == claim_id).all()
    doc_ids = [d.id for d in docs]

    # ── Fetch ALL OCR pages for these documents (no limit) ──
    all_ocr_pages: list[dict[str, Any]] = []
    full_ocr_text = ""
    if doc_ids:
        # Only gets OCR results for THIS claim's documents
        rows = (
            db.query(OcrResult)
            .filter(OcrResult.document_id.in_(doc_ids))  # ← Filter by doc_ids from selected claim
            .order_by(OcrResult.page_number)
            .all()
        )
        for r in rows:
            if r.text and r.text.strip():
                all_ocr_pages.append({
                    "page": r.page_number or 0,
                    "text": r.text.strip(),
                    "confidence": r.confidence,
                })
        full_ocr_text = "\n\n".join(p["text"] for p in all_ocr_pages)

    # Get predictions for THIS claim ONLY
    preds = db.query(Prediction).filter(Prediction.claim_id == claim_id).all()
    
    # Get validations for THIS claim ONLY
    vals = db.query(Validation).filter(Validation.claim_id == claim_id).all()
    
    # Get medical codes for THIS claim ONLY
    mc = db.query(MedicalCode).filter(MedicalCode.claim_id == claim_id).all()
    
    # Get medical entities for THIS claim ONLY
    entities = db.query(MedicalEntity).filter(MedicalEntity.claim_id == claim_id).all()

    return {
        "claim_id": str(claim_id),
        "status": claim.status,
        "policy_id": claim.policy_id,
        "parsed_fields": fields,
        "full_ocr_text": full_ocr_text,
        "relevant_text": relevant_text,
        "ocr_page_count": len(all_ocr_pages),
        "predictions": predictions,
        "validations": validations,
        "medical_codes": codes,
        "medical_entities": entity_list,
    }
```

### File: [services/chat/app/models.py](services/chat/app/models.py#L109-L117)

**ChatMessage model stores claim association:**

```python
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)
    role = Column(Text, nullable=True)     # USER / SYSTEM / ASSISTANT
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

---

## Key Findings

| Aspect | Details |
|--------|---------|
| **Document Selection** | UI stores `activeClaim` state when user clicks a claim card |
| **Message Sending** | `claim_id: activeClaim` is sent in request body |
| **Backend Processing** | `_get_claim_context()` filters ALL queries by `claim_id` |
| **Context Scope** | OCR, parsed fields, predictions, validations, codes — ALL filtered to that one claim |
| **No Cross-Document Context** | Each query uses `.filter(Claim.id == claim_id)` or `.filter(Document.claim_id.in_(doc_ids))` where doc_ids come from that specific claim |
| **Chat History** | Messages are stored with `claim_id` so each claim has its own conversation history |

---

## Conclusion

✅ **The implementation is correct** — When a user selects a document and chats, the context is **isolated to that document only**. No leakage from other documents in the system.

The isolation is enforced at multiple levels:
1. **Frontend**: Only passes the selected `activeClaim` ID
2. **Backend**: `_get_claim_context()` explicitly filters all data queries by `claim_id`
3. **Database**: All entities (ParsedField, OcrResult, Prediction, Validation, MedicalCode) have `claim_id` or `document_id` foreign keys
