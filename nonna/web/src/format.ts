// Shared helpers for showing contract data in a readable way

export type ClauseType =
  | 'liability_cap'
  | 'payment_terms'
  | 'governing_law'
  | 'indemnification'
  | 'term_renewal'
  | 'termination_convenience'
  | 'confidentiality'
  | 'insurance'

export interface Term {
  term_key: string
  value: string | boolean | null
  unit: string | null
}

export const CLAUSE_LABELS: Record<ClauseType, string> = {
  liability_cap: 'Liability cap',
  payment_terms: 'Payment terms',
  governing_law: 'Governing law',
  indemnification: 'Indemnification',
  term_renewal: 'Term and renewal',
  termination_convenience: 'Termination for convenience',
  confidentiality: 'Confidentiality period',
  insurance: 'Insurance minimums',
}

// What each term means, for someone who isn't a lawyer (hover hints and the one-pager)
export const CLAUSE_MEANINGS: Record<ClauseType, string> = {
  liability_cap: 'The most either side has to pay the other if something goes wrong',
  payment_terms: 'How long we have to pay their invoices',
  governing_law: "Which state's law applies if there's a dispute",
  indemnification: "Who covers the other side's costs if someone else sues",
  term_renewal: 'How long the agreement lasts, and whether it renews on its own',
  termination_convenience: 'Who can end the agreement without giving a reason, and how much warning they have to give',
  confidentiality: 'How long both sides have to keep each other’s information secret after the agreement ends',
  insurance: 'The minimum insurance the vendor has to carry, so there’s money to cover it if something goes wrong',
}

export const CONTRACT_TYPE_LABELS: Record<string, string> = {
  NDA: 'NDA',
  MSA: 'MSA',
  SOW: 'SOW',
  amendment: 'Amendment',
  change_order: 'Change order',
}

export function clauseLabel(type: string): string {
  return CLAUSE_LABELS[type as ClauseType] ?? type
}

// Today's date where you are (toISOString would give London's date, which is tomorrow after 4pm in California)
export function todayISO(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export function formatDate(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

// Turn stored values into something readable, like "$2,500,000" or "Net 45"
export function describeTerms(clauseType: string, terms: Term[]): string | null {
  const term = (key: string) => terms.find((t) => t.term_key === key)
  switch (clauseType) {
    case 'liability_cap': {
      const cap = term('cap_amount')
      if (!cap || cap.value === null) return null
      return Number(cap.value).toLocaleString('en-US', {
        style: 'currency',
        currency: cap.unit || 'USD',
        maximumFractionDigits: 0,
      })
    }
    case 'payment_terms': {
      const days = term('net_days')
      if (!days || days.value === null) return null
      const structure = term('payment_structure')?.value
      return `Net ${Number(days.value)}${structure === 'milestone' ? ', milestone billing' : ''}`
    }
    case 'governing_law':
      return (term('jurisdiction')?.value as string | undefined) ?? null
    case 'indemnification': {
      const mutual = term('is_mutual')
      if (!mutual) return null
      const ip = term('covers_ip_infringement')?.value === true
      return `${mutual.value === true ? 'Mutual' : 'One-way'}${ip ? ', covers IP infringement' : ''}`
    }
    case 'term_renewal': {
        if (term('ends_on_event')?.value === true) return 'Ends when the work is done'
        const months = term('initial_term_months')?.value
        const end = term('end_date')?.value
        const length = months != null ? describeMonths(Number(months)) : typeof end === 'string' ? `Ends ${formatDate(end)}` : null
        if (!length) return null
        if (term('auto_renews')?.value !== true) return length
        const renewal = term('renewal_term_months')?.value
        const notice = term('notice_days')?.value
        const parts = [length, renewal != null ? `renews every ${describeMonths(Number(renewal))}` : 'renews automatically']
        if (notice != null) parts.push(`${Number(notice)} days' notice`)
        return parts.join(', ')
      }
      case 'termination_convenience': {
        const who = term('who_may_terminate')?.value
        const notice = term('notice_days')?.value
        const label =
          who === 'either' ? 'Either side' : who === 'aurelia' ? 'Only us' : who === 'vendor' ? 'Only the vendor' : null
        if (!label && notice == null) return null
        const days = notice == null ? null : Number(notice) === 0 ? 'immediately' : `${Number(notice)} days' notice`
        return [label ?? 'Termination for convenience', days].filter(Boolean).join(', ')
      }
      case 'confidentiality': {
        const years = term('survival_years')?.value
        const forever = term('perpetual')?.value === true
        if (!forever && years == null) return null
        const length = forever ? 'Forever' : `${Number(years)} ${Number(years) === 1 ? 'year' : 'years'} after it ends`
        return term('trade_secrets_indefinite')?.value === true
          ? `${length}, trade secrets for as long as they stay secret`
          : length
      }
      case 'insurance': {
        const money = (key: string) => {
          const t = term(key)
          if (!t || t.value === null) return null
          return Number(t.value).toLocaleString('en-US', {
            style: 'currency',
            currency: t.unit && t.unit.length === 3 ? t.unit : 'USD',
            maximumFractionDigits: 0,
          })
        }
        const occurrence = money('general_liability_per_occurrence')
        const aggregate = money('general_liability_aggregate')
        if (occurrence) return `General liability ${occurrence} per occurrence${aggregate ? ` / ${aggregate} aggregate` : ''}`
        if (aggregate) return `General liability ${aggregate} aggregate`
        const products = money('products_liability_limit')
        if (products) return `Products liability ${products}`
        const professional = money('professional_liability_limit')
        return professional ? `Professional liability ${professional}` : null
      }
      default:
        return null
    }
  }
  
  // "36" -> "3 years", "18" -> "18 months"
  export function describeMonths(months: number): string {
    if (months % 12 === 0) {
      const years = months / 12
      return years === 1 ? '1 year' : `${years} years`
    }
    return months === 1 ? '1 month' : `${months} months`
  }
  



// Contract text pulled from a PDF has line breaks in the middle of sentences.
// Join those back up, but keep a paragraph break before each numbered subsection.
export function tidyClauseText(text: string): string {
    return text
      .replace(/\r/g, '')
      .replace(/^.*\bPage \d+ of \d+.*$/gm, '')
      .replace(/[ \t]+\n/g, '\n')
      .replace(/\n+(?=\(?\d{1,2}(?:\.\d{1,2})*\)?[.)]?\s)/g, '\n\n')
      .replace(/([^\n])\n(?!\n)/g, '$1 ')
      .replace(/[ \t]{2,}/g, ' ')
      .trim()
  }