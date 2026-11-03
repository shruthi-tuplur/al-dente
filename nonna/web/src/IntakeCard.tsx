import { useState } from 'react'
import type { ContractType, IntakeProposal } from './nonnaApi'

const TYPE_LABELS: Record<ContractType, string> = {
  NDA: 'Nondisclosure Agreement (NDA)',
  MSA: 'Master Services Agreement (MSA)',
  SOW: 'Statement of Work (SOW)',
  amendment: 'Amendment',
  change_order: 'Change Order',
}

type Mode = 'review' | 'editing' | 'confirmed'

interface Details {
  title: string
  contractType: ContractType | ''
  effectiveDate: string
}

function formatDate(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

function withArticle(label: string): string {
  return /^[AEIOU]/.test(label) ? `an ${label}` : `a ${label}`
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? 'an unknown party'
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

export default function IntakeCard({ proposal }: { proposal: IntakeProposal }) {
  const [details, setDetails] = useState<Details>({
    title: proposal.title ?? '',
    contractType: proposal.contract_type ?? '',
    effectiveDate: proposal.effective_date ?? '',
  })
  const detected = proposal.parties.findIndex((p) => p.is_our_company)
  const [oursIndex, setOursIndex] = useState<number | null>(detected >= 0 ? detected : null)
  const [mode, setMode] = useState<Mode>('review')
  const [draft, setDraft] = useState<Details>(details)
  const [draftOurs, setDraftOurs] = useState<number | null>(oursIndex)
  const [edited, setEdited] = useState(false)
  const [error, setError] = useState('')

  const ours = oursIndex === null ? null : proposal.parties[oursIndex]
  const others = proposal.parties.filter((_, i) => i !== oursIndex)
  const typeLabel = details.contractType ? TYPE_LABELS[details.contractType] : 'contract'

  // Built from the extracted data, never written by the LLM
  const headline = ours
    ? `This looks like ${withArticle(typeLabel)} between ${ours.legal_name} (you) and ${joinNames(
        others.map((p) => p.legal_name),
      )}.`
    : `This looks like ${withArticle(typeLabel)} between ${joinNames(
        proposal.parties.map((p) => p.legal_name),
      )}.`

  function confirm() {
    if (ours === null) {
      setError('Pick which one is your company first.')
      return
    }
    setError('')
    setMode('confirmed')
  }

  function startEditing() {
    setDraft(details)
    setDraftOurs(oursIndex)
    setError('')
    setMode('editing')
  }

  function saveEdits() {
    setDetails(draft)
    setOursIndex(draftOurs)
    setEdited(true)
    setMode('review')
  }

  return (
    <section className="intake-card" aria-label="Uploaded contract details">
      <p className="intake-file">
        {proposal.filename}
        {proposal.page_count !== null && ` · ${proposal.page_count} pages`}
      </p>

      {mode === 'editing' ? (
        <div className="intake-form">
          <label>
            Title
            <input
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            />
          </label>
          <label>
            Contract type
            <select
              value={draft.contractType}
              onChange={(e) =>
                setDraft({ ...draft, contractType: e.target.value as ContractType | '' })
              }
            >
              <option value="">Not sure</option>
              {(Object.keys(TYPE_LABELS) as ContractType[]).map((type) => (
                <option key={type} value={type}>
                  {TYPE_LABELS[type]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Effective date
            <input
              type="date"
              value={draft.effectiveDate}
              onChange={(e) => setDraft({ ...draft, effectiveDate: e.target.value })}
            />
          </label>
          <label>
            Your company
            <select
              value={draftOurs ?? ''}
              onChange={(e) => setDraftOurs(e.target.value === '' ? null : Number(e.target.value))}
            >
              <option value="">Choose one</option>
              {proposal.parties.map((party, i) => (
                <option key={party.legal_name} value={i}>
                  {party.legal_name}
                </option>
              ))}
            </select>
          </label>
          <div className="intake-actions">
            <button type="button" className="btn btn-primary" onClick={saveEdits}>
              Save changes
            </button>
            <button type="button" className="btn btn-quiet" onClick={() => setMode('review')}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="intake-headline">{headline.replace(/\.\.$/, '.')}</p>

          <dl className="intake-details">
            <div>
              <dt>Title</dt>
              <dd>
                {details.title || 'Not found'}
                {!edited && proposal.quotes.title && (
                  <span className="quote">"{proposal.quotes.title}"</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Effective date</dt>
              <dd>
                {details.effectiveDate ? formatDate(details.effectiveDate) : 'Not found'}
                {!edited && proposal.quotes.effective_date && (
                  <span className="quote">"{proposal.quotes.effective_date}"</span>
                )}
              </dd>
            </div>
            {others.map((party) => (
              <div key={party.legal_name}>
                <dt>{ours ? 'Counterparty' : 'Party'}</dt>
                <dd>
                  {party.legal_name}
                  {party.defined_as && ` ("${party.defined_as}")`}
                  {ours &&
                    (party.matches.length > 0 ? (
                      <span className="match">
                        Matches {party.matches[0].name} in nonna ({party.matches[0].contract_count}{' '}
                        contracts)
                      </span>
                    ) : (
                      <span className="match match-new">New to nonna. I'll create her a profile.</span>
                    ))}
                </dd>
              </div>
            ))}
          </dl>

          {ours === null && mode === 'review' && (
            <div className="intake-choose">
              <p>Which one is your company?</p>
              <div className="intake-actions">
                {proposal.parties.map((party, i) => (
                  <button
                    key={party.legal_name}
                    type="button"
                    className="btn btn-quiet"
                    onClick={() => {
                      setOursIndex(i)
                      setError('')
                    }}
                  >
                    {party.legal_name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {proposal.already_uploaded_contract_id !== null && (
            <p className="intake-warning">⚠ You've uploaded this exact file before.</p>
          )}
          {proposal.redaction_count > 0 && (
            <p className="intake-warning">
              ⚠ {proposal.redaction_count} redactions found. Some terms may be hidden.
            </p>
          )}
          {proposal.unverified.length > 0 && (
            <p className="intake-warning">
              ⚠ Couldn't find a matching quote for: {proposal.unverified.join(', ')}. Please double
              check those.
            </p>
          )}

          {mode === 'review' ? (
            <>
              <p className="intake-question">Is that right?</p>
              <div className="intake-actions">
                <button type="button" className="btn btn-primary" onClick={confirm}>
                  Yes, looks right
                </button>
                <button type="button" className="btn btn-quiet" onClick={startEditing}>
                  Something's off
                </button>
              </div>
              {error && <p className="intake-error">{error}</p>}
            </>
          ) : (
            <p className="intake-confirmed">✓ Confirmed. Next, nonna saves it and pulls the key terms.</p>
          )}
        </>
      )}
    </section>
  )
}