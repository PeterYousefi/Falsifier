# docs/NEGATIVE_CLAIMS.md

> **Priority claim.** I am not aware of prior art in scientific APIs that
> transport a negative claim at the transport layer, in-band, on every
> response.  If you know of prior art, please open an issue or a PR — that
> phrasing is defensible; a priority claim without evidence is not.

---

## The problem

Scientific disclaimers live in prose.  Prose gets separated from data.

A paper publishes a measurement and includes a caveats section.  A data
product is derived from that measurement and distributed.  A pipeline reads
the data product and computes a secondary result.  A dashboard displays the
secondary result in a headline number.  By that point the caveat section of
the original paper is four steps upstream and invisible.

This problem is structural.  The disclaimer is authored once, at the source,
in a place that is rarely the place where the data is ultimately consumed.
Every hand-off between systems is an opportunity for the disclaimer to fall off.
The disclaimer does not travel with the data; it lives beside the data, in a
document that requires a deliberate act of navigation to find.

The problem is acute in scientific APIs because an API response is designed to
be consumed by machines.  A machine reading a JSON payload does not read the
README.  It does not follow the documentation link.  It reads the fields in the
response object.  If the disclaimer is not in the response object, the machine
does not receive it.

---

## The pattern: carry the disclaimer in-band

The disclaimer should travel with the payload, at the transport layer, on every
response, automatically.

An HTTP response header is an appropriate place.  It is:

- **In-band**: present in every response alongside the data
- **Automatic**: emitted by middleware without any per-route action
- **Impossible to strip accidentally**: a client that processes the body but
  ignores headers still receives the header; a client that logs all headers
  automatically records it
- **Legible in infrastructure**: it appears in every `curl -v` trace, in every
  proxy log, in every network capture; a developer debugging the API sees it
  without looking for it

The header does not replace prose documentation.  It is a machine-readable
signal that a consumer receives even if they never read the documentation.

---

## Our instance

### The transport header

Every response from the Falsifier API carries:

```
X-Non-Claim: Not a biosignature detector. No exoplanet biosignature has ever been confirmed.
```

This is set in [`falsifier/api/app.py`](falsifier/api/app.py) as ASGI middleware
on every response:

```python
_NON_CLAIM_VALUE = (
    "Not a biosignature detector. "
    "No exoplanet biosignature has ever been confirmed."
)

async def _non_claim_middleware(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Non-Claim"] = _NON_CLAIM_VALUE
    return response
```

It cannot be accidentally omitted on a new route.  A route added without a
non-claim header does not exist — the middleware attaches it regardless.

### The locked blockquote

The README opens with a byte-for-byte locked blockquote:

```
> **This project is not a biosignature detector.**
> **No exoplanet biosignature has ever been confirmed.**
> This claim is immutable. No generated code, comment, or UI copy contradicts it.
```

This is declared immutable in [`AGENTS.md`](AGENTS.md) under "Locked Claim."
Any AI assistant or code generator operating in this repository is required to
preserve it byte-for-byte.  It cannot be reworded, moved below the fold, or
absorbed into another section.

### The constructor-level rejection

`VetOutput` is the core output object of the vet stage.  Its Pydantic
`model_validator` in [`falsifier/pipeline/contracts/vet.py`](falsifier/pipeline/contracts/vet.py)
enforces that `disposition` is consistent with the seven test outcomes at
object-construction time.  An inconsistent disposition raises immediately; it
cannot be stored, committed, or returned by the API.

This is a negative claim enforced at the data-layer: the object model does not
permit a disposition that contradicts the evidence.  It is not a prose
disclaimer — it is a runtime constraint.

---

## Honest limits

### A header is advisory

An HTTP header is not a contract.  A consumer that reads the body and discards
all headers receives the data without the disclaimer.  Nothing in the HTTP
specification requires a client to read or act on a custom header.  A client
can silently ignore `X-Non-Claim` and pass the pipeline output downstream
without it.

### A consumer can re-label

A downstream system can read the `disposition` field of a `VetOutput`, apply
its own label, and publish the result.  The `X-Non-Claim` header travelled with
the response to that downstream system; it did not travel with what the
downstream system published.

### A screenshot is opaque

A screenshot of the UI or an API response shows numbers and dispositions.
It does not show headers.  A number extracted from a screenshot has no
attachment to any disclaimer at all.

### The pattern does not solve the problem of trust

If a consumer chooses to misrepresent the output of this API — to strip the
disclaimer, ignore the header, or relabel the result — no transport mechanism
prevents it.  The pattern reduces the probability of accidental misrepresentation
by making the disclaimer difficult to miss.  It does not reduce the probability
of deliberate misrepresentation.

---

## What would make it enforceable rather than advisory

### Signed disclaimer

The disclaimer could be signed with a project key and included in the response
body alongside the data.  A consumer could be required to verify the signature
before processing the response.  This would make the disclaimer
cryptographically attached to the data — it could not be stripped without
breaking the signature check.

**Cost:** requires key infrastructure; places a verification burden on
consumers; not standard in scientific APIs; would not prevent re-labelling
downstream.

### Content negotiation

The API could refuse to return a response to any client that does not
acknowledge the disclaimer in a request header.

**Cost:** incompatible with standard HTTP clients; breaks curl, browser-based
tools, and any consumer not specifically written for this API.

### Verifiable provenance in the payload

Every response body could include a `non_claim` field alongside the scientific
data:

```json
{
  "disposition": "candidate",
  "triggering_test": null,
  "non_claim": "Not a biosignature detector. No exoplanet biosignature has ever been confirmed.",
  ...
}
```

A consumer that persists the JSON payload retains the disclaimer in the stored
artifact.  This is achievable without changing the transport protocol.

**Cost:** increases payload size; requires every downstream system that serialises
the `VetOutput` to preserve the field; consumers can still strip it when publishing.

### The honest conclusion

A disclaimer that travels with the data is harder to lose than one that lives
in documentation.  It is not impossible to lose.  The gap between "harder to
lose" and "impossible to lose" cannot be closed by transport mechanisms alone.
It can only be narrowed.  The pattern is worth implementing because it narrows
the gap; it is worth disclosing its limits because the gap still exists.
