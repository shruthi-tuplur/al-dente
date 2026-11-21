// Links from chat to the library. A source line in a chat card ("MSA §11.2 · Mar 1, 2025")
// becomes a button that opens that contract in the Library with the section highlighted.
// Only chat provides the opener, so the same cards shown inside the Library stay plain text.
import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'

// Where to jump: a contract, and if we know it, the section and its exact wording
export interface LibraryTarget {
  contractId: number
  section: string | null
  quote: string | null // the clause's own text, the most reliable way to find it
}

export const OpenInLibrary = createContext<((target: LibraryTarget) => void) | null>(null)

export function SourceLink({ target, children }: { target: LibraryTarget; children: ReactNode }) {
  const open = useContext(OpenInLibrary)
  if (!open) return <>{children}</>
  return (
    <button type="button" className="source-link" title="Open this in the Library" onClick={() => open(target)}>
      {children}
      <span className="source-link-arrow" aria-hidden="true">
        →
      </span>
      <span className="visually-hidden"> (open in the Library)</span>
    </button>
  )
}