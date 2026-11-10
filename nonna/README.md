Optional: `NONNA_MODEL` to choose the Claude model.

**3. Backend** (from the repo root)
```bash
uv run uvicorn nonna.api:app --reload
```
API docs at http://127.0.0.1:8000/docs

**4. Frontend**
```bash
cd nonna/web
npm install
npm run dev
```
Open http://localhost:5173

**5. Try it.** Upload the sample contracts in `data/base/` in this order: the Lucca MSA, SOW No. 1, Amendment No. 1, then SOW No. 2 (it has a planted payment term drift). Then ask:
- "nonna what are the key details for lucca?"
- "what's our liability cap with lucca and has it changed?"
- "what was the exact indemnity clause we used for lucca?"
- "which vendors have a liability cap under $1M?"
- "what's the non-compete with lucca?" (there isn't one, and she won't invent one)

## Data

All contracts and companies are **fictional**, written for this project (Aurelia Therapeutics and its vendors: Lucca Biologics, Castellan Bioprocessing, and others). No confidential, client, or employer data is used anywhere. Testing on public SEC EDGAR exhibits is planned.

## Results

Formal evals are in progress. What's been tested by hand so far:

- **No invented clauses.** Asked about a non-compete that doesn't exist, Nonna searched several terms, cited what she found (and why it wasn't a non-compete), said keyword search could miss differently worded language, and didn't make one up.
- **Planted drift caught.** Lucca SOW No. 2 changes payment terms to net 60 without the language needed to override the MSA's net 45. Approval is blocked by the drift guard and the Review dashboard marks it as Different.
- **Amendments tracked.** The liability cap shows $2.5M as an earlier version and $3M as agreed after Amendment No. 1.
- **Currency honesty.** Asked to compare caps against €1M, Nonna declined to convert currencies and said so.
- **Correction audit.** Nonna noticed a corrected value that didn't match the clause text and pointed to the correction history.

**Coming next:** extraction accuracy per clause type on a labeled set, and a hallucination test set (questions about clauses that exist vs ones that don't).

## Limitations

- **Four tracked terms.** Only liability cap, payment terms, governing law, and indemnification have extracted values, review, and drift checks. Everything else is browsable verbatim but not compared.
- **Topic sorting uses headings.** Contracts with unusual headings can produce odd topic names in the catalog. They still show up, just sorted to the bottom.
- **Keyword search for untracked clauses.** Searching the catalog matches words, so a clause worded differently can be missed. Nonna says so when it matters.
- **USD only for cap comparisons.** Caps in other currencies are listed, never converted.
- **Clean sample contracts.** Extraction is built around the fictional samples. Real contracts with scanned pages, unusual numbering, or heavy redaction will need more work.
- **Nonna doesn't decide which term controls.** When an SOW and MSA conflict, she shows both and leaves the legal call to the attorney.
- **No login yet.** There's one demo user, so this isn't ready for a real team without authentication and access controls.
- **Can't add a clause Nonna missed.** Corrections fix values that were found. Adding a clause extraction missed entirely isn't built yet.

## Later

- Drafting a new SOW from a vendor's history, with each clause labeled verbatim, adapted, or new
- Tracking more terms with values (term length, auto-renewal, termination notice, confidentiality duration, insurance)
- Expiration and renewal deadline tracking
- A company playbook to compare each vendor's terms against your standard positions
- An "as amended" view that shows a contract as it reads today
- Counterparty one-page summary export
- [Too Many Cooks](../too_many_cooks/), the full drift detector built on Nonna's history
