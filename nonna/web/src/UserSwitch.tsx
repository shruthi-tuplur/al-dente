// Who's using Nonna. No login yet, so this demo switcher stands in for single sign-on.
// Business users get a read-only Nonna: the server refuses their changes, and the app hides the buttons.
import { CAN_EDIT, CURRENT_USER, DEMO_USERS, switchUser } from './nonnaApi'

export default function UserSwitch() {
  return (
    <label className="user-switch">
      <span className="user-switch-label">Viewing as</span>
      <select value={CURRENT_USER} onChange={(e) => switchUser(e.target.value)} aria-label="Viewing as (demo user)">
        {DEMO_USERS.map((user) => (
          <option key={user.name} value={user.name}>
            {user.name} · {user.label}
          </option>
        ))}
      </select>
      {!CAN_EDIT && <span className="badge user-switch-badge">Read-only</span>}
    </label>
  )
}

// Shown under the header for read-only users, so nobody wonders where the buttons went
export function ReadOnlyBanner() {
  if (CAN_EDIT) return null
  return (
    <p className="read-only-banner" role="note">
      Read-only view. You can look anything up and ask Nonna questions. Reviews, edits, notes, and drafts are for the
      legal team.
    </p>
  )
}