# First Chat Welcome Message – Spec

**Status:** Implemented. Request metadata accepts `isFirstChat`; when true, backend returns the welcome message.

---

## 1. Key for “first chat”

- Use **`isFirstChat`** in the request metadata.
- When `params.metadata.isFirstChat === true`, treat the request as first chat and return the welcome message (see below).

---

## 2. Welcome message content

- **First line (literal in response):**  
  `Welcome {user_name}! I am Cisco Uber Assistant. How can I help you today?`
- **`{user_name}`:** Return this placeholder as-is in the response. The **UI** will replace `{user_name}` with the actual user name. The backend does not need to receive or substitute the name.

- **Following lines (same as in the uploaded screenshot – action/button labels):**
  - Book a demo or trial
  - Chat with Sales
  - Get Support
  - Licensing
  - Get Cisco Certified
  - Velocity Hub

So the full welcome text returned by the backend should be:

```
Welcome {user_name}! I am Cisco Uber Assistant. How can I help you today?
Book a demo or trial
Chat with Sales
Get Support
Licensing
Get Cisco Certified
Velocity Hub
```

(Exact formatting—e.g. newlines vs line breaks—can follow the same convention as other multi-line content in A2A artifacts.)

---

## 3. When to return it

- When the request has **`params.metadata.isFirstChat === true`** (and any other “first turn” rule you define, e.g. no or minimal user query), the backend responds with this welcome message as the A2A result content (e.g. in `result.artifacts[].parts[].text`).

---

## 4. Response shape

- Unchanged: same A2A response structure.
- The welcome text above is the body of the response (e.g. single text part in the first artifact). No extra fields required for `{user_name}`; the UI performs the substitution.

---

## 5. Summary

| Item | Value |
|------|--------|
| Request key | **`isFirstChat`** in `params.metadata` |
| First line | `Welcome {user_name}! I am Cisco Uber Assistant. How can I help you today?` |
| `{user_name}` | Returned literally; UI replaces it |
| Following lines | Book a demo or trial, Chat with Sales, Get Support, Licensing, Get Cisco Certified, Velocity Hub (same as screenshot) |
