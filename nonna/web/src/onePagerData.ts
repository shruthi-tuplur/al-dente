// What goes on a vendor's one-pager: the deal in plain English for someone who won't read
// the contract. Every sentence is put together here in code from reviewed data, never by AI.
import { CLAUSE_LABELS, CLAUSE_MEANINGS, describeTerms, formatDate } from './format'
import type { ClauseType } from './format'
import type {
  CounterpartyLibrary,
  LibraryClause,
  LibraryContract,
  OnePagerDeadline,
  PlaybookAssessment,
} from './nonnaApi'

export interface TermRow {
  type: ClauseType
  label: string
  meaning: string // what the term means, for someone who isn't a lawyer
  value: string
  from: string | null // which contract it comes from
  playbook: PlaybookAssessment | null
}

export interface OnePagerContract {
  kind: string
  title: string
  date: string
  note: string | null
}

export interface OnePagerData {
  vendor: string
  legalNames: string[]
  shortVersion: string[]
  terms: TermRow[]
  headsUp: string[]
  contracts: OnePagerContract[]
}


const ABSENT: Partial<Record<ClauseType, string>> = {
  liability_cap: 'No cap',
  payment_terms: 'Not stated',
  governing_law: 'Not stated',
  indemnification: 'None',
}

const KIND: Record<string, string> = {
  MSA: 'Master agreement',
  SOW: 'Statement of work',
  amendment: 'Amendment',
  change_order: 'Change order',
  NDA: 'NDA',
}

// "STATEMENT OF WORK NO. 1 - Process Development Services" -> "SOW No. 1: Process Development Services"
export function friendlyTitle(title: string): string {
  const sow = title.match(/statement of work no\.?\s*(\d+)\s*[-–:]?\s*(.*)$/i)
  if (sow) return `SOW No. ${sow[1]}${sow[2] ? `: ${sow[2]}` : ''}`
  if (title === title.toUpperCase()) {
    return title.toLowerCase().replace(/\b([a-z])/g, (c) => c.toUpperCase())
  }
  return title
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}

function listWords(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

function valueOf(clause: LibraryClause): string {
  if (clause.presence === 'absent') return ABSENT[clause.clause_type as ClauseType] ?? 'None'
  return describeTerms(clause.clause_type, clause.terms) ?? 'See the contract'
}

function where(contract: LibraryContract, clause: LibraryClause): string {
  // An amendment's section number is the MSA section it changes, not a section of the amendment
  const section = !clause.section_number
    ? ''
    : contract.contract_type === 'amendment'
      ? ` (changes §${clause.section_number})`
      : ` §${clause.section_number}`
  return `${friendlyTitle(contract.title)}${section}, ${formatDate(contract.effective_date)}`
}

const reviewed = (clause: LibraryClause) => clause.review_status === 'approved' || clause.review_status === 'corrected'

export function buildOnePager(library: CounterpartyLibrary, deadlines: OnePagerDeadline[]): OnePagerData {
  const agreed = new Set(library.agreed_clause_ids)
  const all = library.contracts.flatMap(({ contract, clauses }) => clauses.map((clause) => ({ contract, clause })))
  const msas = library.contracts.filter(({ contract }) => contract.contract_type === 'MSA').map(({ contract }) => contract)
  const amendments = library.contracts.filter(({ contract }) => contract.contract_type === 'amendment')
  const sows = library.contracts.filter(({ contract }) => contract.contract_type === 'SOW')
  const headsUp: string[] = []

  // The deal-wide terms: what's agreed at the master-agreement level (an amendment counts)
  const masterLevel = (contract: LibraryContract) => contract.contract_type === 'MSA' || contract.contract_type === 'amendment'
  const terms: TermRow[] = []
  for (const type of Object.keys(CLAUSE_LABELS) as ClauseType[]) {
    const candidates = all.filter(({ clause }) => clause.clause_type === type)
    const pick =
      candidates.find(({ contract, clause }) => agreed.has(clause.id) && masterLevel(contract)) ??
      // Term and renewal is never a baseline, so use the reviewed one from the master agreement
      [...candidates].reverse().find(({ contract, clause }) => masterLevel(contract) && reviewed(clause)) ??
      candidates.find(({ clause }) => agreed.has(clause.id))
    if (!pick) continue
    terms.push({
      type,
      label: CLAUSE_LABELS[type],
      meaning: CLAUSE_MEANINGS[type],
      value: valueOf(pick.clause),
      from: pick.clause.presence === 'absent' ? `Not in ${friendlyTitle(pick.contract.title)}` : where(pick.contract, pick.clause),
      playbook: library.playbook[pick.clause.id] ?? null,
    })

    // SOWs that set their own version of this term. Not term and renewal: an SOW running
    // until its work is done is normal, not a difference worth flagging.
    if (type === 'term_renewal') continue
    for (const { contract, clause } of candidates) {
      if (contract.contract_type !== 'SOW' || !reviewed(clause) || clause.presence !== 'present') continue
      const own = valueOf(clause)
      if (own !== terms[terms.length - 1].value) {
        headsUp.push(
          `${friendlyTitle(contract.title)} sets its own ${CLAUSE_LABELS[type].toLowerCase()}: ${own} ` +
            `(the master agreement says ${terms[terms.length - 1].value}).`,
        )
      }
    }
  }

  // Dates to watch, from the deadlines Nonna works out in code
  const msaIds = new Set(msas.map((c) => c.id))
  const nextDeadline = deadlines
    .filter((d) => msaIds.has(d.source.id) && d.action_date && (d.status === 'upcoming' || d.status === 'notice_passed'))
    .sort((a, b) => (a.action_date ?? '').localeCompare(b.action_date ?? ''))[0]

  // The short version, for someone who reads nothing else
  const shortVersion: string[] = []
  if (msas.length > 0) {
    const msa = msas[0]
    const amended = amendments.length
      ? `, amended ${amendments.length === 1 ? 'once' : `${amendments.length} times`} (latest ${formatDate(
          amendments[amendments.length - 1].contract.effective_date,
        )})`
      : ''
    const extras = [sows.length ? plural(sows.length, 'statement of work', 'statements of work') : null].filter(Boolean)
    shortVersion.push(
      `We work with ${library.counterparty.name} under a master agreement signed ${formatDate(msa.effective_date)}${amended}` +
        (extras.length ? `, plus ${extras.join(' and ')}.` : '.'),
    )
  } else {
    shortVersion.push(`We have ${plural(library.contracts.length, 'contract')} with ${library.counterparty.name}, but no master agreement on file.`)
  }
  if (nextDeadline?.action_date) {
    const isNotice = nextDeadline.notice_deadline && nextDeadline.action_date === nextDeadline.notice_deadline
    shortVersion.push(
      isNotice
        ? `Next date to watch: ${formatDate(nextDeadline.action_date)}, the last day to tell them if we don't want the agreement to renew.`
        : `Next date to watch: ${formatDate(nextDeadline.action_date)}, when the agreement ends.`,
    )
  }
  const off = terms.filter((t) => t.playbook?.tier === 'outside').map((t) => t.label.toLowerCase())
  const below = terms.filter((t) => t.playbook?.tier === 'fallback').map((t) => t.label)
  const checked = terms.filter((t) => t.playbook && t.playbook.tier !== 'not_comparable')
  if (off.length > 0) {
    shortVersion.push(`Outside our standard positions: ${listWords(off)}. Talk to Legal before relying on these.`)
  } else if (below.length > 0) {
    shortVersion.push(
      `Every key term is within our playbook. ${listWords(below)} ${below.length === 1 ? 'is' : 'are'} at our fallback position, not our first ask.`,
    )
  } else if (checked.length > 0) {
    shortVersion.push('Every key term meets our standard positions.')
  }

  // Things in flight
  const pending = all.filter(({ clause }) => clause.review_status === 'pending')
  if (pending.length > 0) {
    const from = [...new Set(pending.map(({ contract }) => friendlyTitle(contract.title)))]
    headsUp.push(`${plural(pending.length, 'term')} from ${listWords(from)} ${pending.length === 1 ? 'is' : 'are'} still waiting for Legal's review, so ${pending.length === 1 ? "it isn't" : "they aren't"} included above.`)
  }
  if (nextDeadline?.status === 'notice_passed') {
    headsUp.push('The notice date for this term has already passed, so the agreement has renewed.')
  }

  const contracts: OnePagerContract[] = library.contracts.map(({ contract }) => ({
    kind: KIND[contract.contract_type] ?? contract.contract_type,
    title: friendlyTitle(contract.title),
    date: formatDate(contract.effective_date),
    note: contract.status !== 'active' ? contract.status : null,
  }))

  return {
    vendor: library.counterparty.name,
    legalNames: library.counterparty.entities.map((e) => e.legal_name),
    shortVersion,
    terms,
    headsUp,
    contracts,
  }
}