// Optional Google Calendar sync, shown on the deadlines card.
// Nonna keeps her own "Nonna deadlines" calendar and can't see the rest of your Google Calendar.
// If Google isn't set up in .env, this shows nothing and the .ics download still works.
import { useEffect, useRef, useState } from 'react'
import {
  GOOGLE_CALENDAR_CONNECT_URL,
  disconnectGoogleCalendar,
  fetchCalendarStatus,
  syncGoogleCalendar,
} from './nonnaApi'
import type { CalendarStatus } from './nonnaApi'

export default function GoogleCalendarBar({ onConnectedChange }: { onConnectedChange?: (connected: boolean) => void }) {
  const [calendar, setCalendar] = useState<CalendarStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const waiting = useRef<number | null>(null)

  async function sync() {
    setBusy(true)
    setError('')
    try {
      setMessage((await syncGoogleCalendar()).message)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't sync Google Calendar.")
    } finally {
      setBusy(false)
    }
  }

  // Let the deadlines card know, so it can hide the one-time .ics downloads while Google is syncing
  useEffect(() => {
    onConnectedChange?.(calendar?.connected ?? false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calendar?.connected])

  function stopWaiting() {
    if (waiting.current !== null) window.clearInterval(waiting.current)
    waiting.current = null
  }

  // Once the popup says you're signed in, check, then fill the calendar straight away
  async function connected() {
    stopWaiting()
    const latest = await fetchCalendarStatus()
    setCalendar(latest)
    if (latest.connected) await sync()
  }

  useEffect(() => {
    fetchCalendarStatus()
      .then(setCalendar)
      .catch(() => setCalendar(null))

    function onMessage(event: MessageEvent) {
      if (event.data === 'nonna-calendar-connected') void connected()
    }
    window.addEventListener('message', onMessage)
    return () => {
      window.removeEventListener('message', onMessage)
      stopWaiting()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function connect() {
    setError('')
    setMessage('')
    window.open(GOOGLE_CALENDAR_CONNECT_URL, 'nonna-google', 'width=520,height=680')
    // Google's sign-in page can cut the popup off from this tab, so also check every
    // couple of seconds (for up to 3 minutes) in case the "done" message never arrives
    stopWaiting()
    let tries = 0
    waiting.current = window.setInterval(() => {
      tries += 1
      if (tries > 90) return stopWaiting()
      fetchCalendarStatus()
        .then((latest) => {
          if (latest.connected) void connected()
        })
        .catch(() => undefined)
    }, 2000)
  }

  async function disconnect() {
    setBusy(true)
    setError('')
    try {
      setCalendar(await disconnectGoogleCalendar())
      setMessage('Disconnected. The Nonna deadlines calendar stays in Google until you delete it.')
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't disconnect.")
    } finally {
      setBusy(false)
    }
  }

  if (!calendar?.configured) return null

  return (
    <div className="deadline-google">
      {calendar.connected ? (
        <>
          <button type="button" className="btn btn-sm btn-primary" onClick={sync} disabled={busy}>
            {busy ? 'Syncing…' : 'Sync to Google Calendar'}
          </button>
          <button type="button" className="lib-fix" onClick={disconnect} disabled={busy}>
            Disconnect
          </button>
        </>
      ) : (
        <button type="button" className="btn btn-sm btn-primary" onClick={connect}>
          Connect Google Calendar
        </button>
      )}
      {message && <p className="deadline-google-note">✓ {message}</p>}
      {error && <p className="intake-error">⚠ {error}</p>}
      {!message && !error && (
        <p className="deadline-google-note">
          {calendar.connected
            ? `Keeps your "${calendar.calendar_name}" calendar up to date. It also updates on its own when a term is approved or corrected.`
            : 'Nonna makes her own calendar and can only see that one, nothing else in your Google account.'}
        </p>
      )}
    </div>
  )
}