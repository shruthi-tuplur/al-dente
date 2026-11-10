# Nonna web app

React + TypeScript frontend for [Nonna](../README.md), built with Vite.

## Views

- **Chat:** ask Nonna questions in plain English and upload contracts with the paperclip. Answers come back with cards that show the data and its source, including comparisons across every vendor. Uploads walk through confirming the contract details, then reviewing what Nonna extracted.
- **Library:** every vendor and everything on file for them.
  - **Contracts:** grouped by type (master agreements, SOWs, amendments, change orders, NDAs), with the full text and the original file.
  - **Clauses:** the key terms Nonna tracks, with every version, its review status, and a Fix value option, plus every clause from every contract filed by topic, word for word with a Copy button.
- **Review:** everything waiting for an attorney, grouped by vendor and contract. Each term is shown next to what's agreed right now, with a Matches or Different badge. Approve, reject, fix a value, or approve a whole contract at once.

## Run it

Start the backend first (see [Nonna's README](../README.md#run-it-locally)), then:

```bash
npm install
npm run dev
```

During development, requests to `/api/...` are proxied to the FastAPI backend at `http://127.0.0.1:8000` (see `vite.config.ts`).

## Where things live

| File | What it does |
|---|---|
| `src/App.tsx` | The page shell, the Chat / Library / Review switcher, and the chat |
| `src/nonnaApi.ts` | Every call to the backend, plus the shared types |
| `src/CardView.tsx` | The cards under Nonna's replies (profile, clause, history, vendors, and more) |
| `src/RichText.tsx` | Light formatting for replies (bold and bullet lists), built without injecting HTML |
| `src/IntakeCard.tsx` | The upload flow: confirm details, save, extract, review |
| `src/ReviewControls.tsx` | Approve, reject, approve as a change, and Approve all |
| `src/CorrectionForm.tsx` | Fixing a value Nonna extracted wrong |
| `src/Review.tsx` | The Review dashboard |
| `src/Library.tsx` | The Library: vendors, contracts, and clauses |
| `src/format.ts` | Labels and formatting for clause values and dates |

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Start the dev server |
| `npm run build` | Type-check and build for production |
| `npm run lint` | Lint the code |
