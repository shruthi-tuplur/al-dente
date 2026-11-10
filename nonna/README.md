# Nonna 👵🍝

**A counterparty clause library for in-house legal teams.** Nonna remembers what your team actually agreed to with every vendor, across every MSA, SOW, amendment, and change order, the way a nonna never forgets a recipe.

Part of [Al Dente](../README.md), a library of legal AI tools built to be clean, secure, and trustworthy enough for a whole legal team.

---

## The problem

Legal teams negotiate with the same companies over and over. But when someone asks "what did we agree to with this vendor last time?", the answer is usually buried across a stack of PDFs: an MSA, three SOWs, an amendment that changed one section, and a change order nobody remembers.

Most clause libraries store a company's **standard** positions. They don't store the history of what was **actually negotiated** with each counterparty. So terms quietly drift: a new SOW says net 60 when the MSA says net 45, a cap gets lowered, and nobody notices until it matters. Teams without API access to their CLM have even less visibility.

I saw this firsthand working with an in-house contracts team at a biotech. Nonna is the tool I wished they had.

## What Nonna does

- **Upload a contract** (PDF or Word). Nonna reads it, proposes the parties, contract type, effective date, and which MSA it falls under, and an attorney confirms before anything is saved.
- **Extracts key terms** (liability cap, payment terms, governing law, indemnification) and saves them as *pending* until an attorney reviews them.
- **Review dashboard** with every pending term grouped by vendor and contract, shown next to what's currently agreed, with a **Matches** or **Different** badge so drift is visible before anyone clicks Approve.
- **Drift guard.** Approving a term that differs from the agreed baseline is blocked unless the attorney approves it as an intentional change with a note.
- **Corrections.** Attorneys can fix values Nonna extracted wrong. The original value is kept in the decision log, and changing an agreed term still requires explicit confirmation.
- **Chat.** Ask in plain English: "what's our liability cap with Lucca and has it changed?", "what was the exact indemnity clause we used?", "which vendors have a cap under $1M?" Answers come with cards showing the data and its source.
- **Library.** Browse every vendor, every contract (grouped by type, with the full text and the original file), and every clause:
  - **Key terms Nonna tracks:** the four terms with values, review status, and version history (Agreed vs Earlier version)
  - **Every clause, as written:** every section of every contract, filed under about 20 topics (Confidentiality, IP, Termination, Force majeure, and so on), verbatim with a Copy button
- **Questions across all vendors.** Compare one agreed term across the whole vendor list, with filters. The math happens in code, never in the model.

## How it works
