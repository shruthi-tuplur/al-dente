// Shared helpers for showing contract data in a readable way

export type ClauseType = 'liability_cap' | 'payment_terms' | 'governing_law' | 'indemnification' | 'term_renewal'

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