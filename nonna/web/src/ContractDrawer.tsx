// A contract that slides in from the right when you tap a source in chat.
// The chat stays put underneath, so you can read the clause and keep talking to Nonna.
import { useEffect, useRef, useState } from 'react'
import { formatDate } from './format'
import FullContract from './FullContract'
import type { LibraryTarget } from './LibraryLink'
import type { ContractText } from './nonnaApi'

export default function ContractDrawer({
  target,
  onClose,
  onOpenInLibrary,
}: {
  target: LibraryTarget
  onClose: () => void
  onOpenInLibrary: (target: LibraryTarget) => void
}) {
  const [contract, setContract] = useState<ContractText | null>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  // Escape closes it. Focus starts on the close button so keyboard users land inside.
  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const title = contract && contract.id === target.contractId ? contract : null

  return (
    <aside className="drawer" role="dialog" aria-modal="false" aria-label={title ? title.title : 'Contract'}>
      <div className="drawer-head">
        <div className="drawer-title">
          <p className="card-title">{title ? title.title : 'Loading…'}</p>
          {title && <p className="card-subtitle">{formatDate(title.effective_date)}</p>}
        </div>
        <button ref={closeRef} type="button" className="drawer-close" aria-label="Close the contract" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="drawer-actions">
        <button type="button" className="lib-tool" onClick={() => onOpenInLibrary(target)}>
          Open in Library →
        </button>
        {title?.has_file && (
          <a className="lib-tool" href={`/api/contracts/${target.contractId}/file`} target="_blank" rel="noreferrer">
            Original file ↗
          </a>
        )}
      </div>
      <div className="drawer-body">
        <FullContract contractId={target.contractId} target={target} onLoaded={setContract} />
      </div>
    </aside>
  )
}