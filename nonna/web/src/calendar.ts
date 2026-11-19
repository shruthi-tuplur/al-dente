// Turns Nonna's deadlines into a calendar file (.ics) that Google Calendar, Outlook,
// and Apple Calendar can all open. No calendar account or integration needed.
// Every date comes from the deadlines API, which works them out in code.

export interface CalendarDeadline {
    clause_id: number
    counterparty_name: string
    source: { id: number; title: string }
    status: string
    notice_deadline: string | null
    action_date: string | null
    summary: string
  }
  
  // Reminders before the deadline, so there's time to talk to the business first
  const REMINDERS = ['-P30D', '-P7D', '-P1D']
  
  import { todayISO } from './format'

// Only deadlines still ahead of us are worth a calendar entry
  export function canAddToCalendar(row: CalendarDeadline): boolean {
    if (!row.action_date || row.status === 'expired' || row.status === 'unknown') return false
    return row.action_date >= todayISO()
  }
  
  // Calendar text needs commas, semicolons, backslashes, and line breaks escaped
  function escapeText(text: string): string {
    return text.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n')
  }
  
  // Calendar lines longer than 75 characters have to wrap onto lines that start with a space
  function fold(line: string): string {
    const parts: string[] = []
    let rest = line
    while (rest.length > 75) {
      parts.push(rest.slice(0, 75))
      rest = ' ' + rest.slice(75)
    }
    parts.push(rest)
    return parts.join('\r\n')
  }
  
  function dateValue(iso: string): string {
    return iso.replace(/-/g, '')
  }
  
  function nextDay(iso: string): string {
    const d = new Date(`${iso}T00:00:00Z`)
    d.setUTCDate(d.getUTCDate() + 1)
    return d.toISOString().slice(0, 10)
  }
  
  function eventTitle(row: CalendarDeadline): string {
    return row.notice_deadline && row.action_date === row.notice_deadline
      ? `Last day to send non-renewal notice: ${row.counterparty_name}`
      : `Contract expires: ${row.counterparty_name}`
  }
  
  function event(row: CalendarDeadline, stamp: string): string[] {
    const day = row.action_date as string
    const description = [
      `${row.source.title}`,
      row.summary,
      'Worked out by Nonna from the reviewed term. Confirm against the contract before acting.',
    ].join('\n\n')
    return [
      'BEGIN:VEVENT',
      `UID:nonna-${row.clause_id}-${dateValue(day)}@al-dente`,
      `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${dateValue(day)}`,
      `DTEND;VALUE=DATE:${dateValue(nextDay(day))}`,
      `SUMMARY:${escapeText(eventTitle(row))}`,
      `DESCRIPTION:${escapeText(description)}`,
      'TRANSP:TRANSPARENT',
      ...REMINDERS.flatMap((trigger) => [
        'BEGIN:VALARM',
        'ACTION:DISPLAY',
        `DESCRIPTION:${escapeText(eventTitle(row))}`,
        `TRIGGER:${trigger}`,
        'END:VALARM',
      ]),
      'END:VEVENT',
    ]
  }
  
  export function buildCalendar(rows: CalendarDeadline[]): string {
    const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')
    const lines = [
      'BEGIN:VCALENDAR',
      'VERSION:2.0',
      'PRODID:-//Al Dente//Nonna//EN',
      'CALSCALE:GREGORIAN',
      ...rows.filter(canAddToCalendar).flatMap((row) => event(row, stamp)),
      'END:VCALENDAR',
    ]
    return lines.map(fold).join('\r\n') + '\r\n'
  }
  
  // Saves the .ics file; opening it adds the events to whatever calendar app is set up
  export function downloadCalendar(rows: CalendarDeadline[], filename: string): void {
    const blob = new Blob([buildCalendar(rows)], { type: 'text/calendar;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }