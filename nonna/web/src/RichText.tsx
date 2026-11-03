import type { ReactNode } from 'react'

// Shows Nonna's replies with light formatting: **bold** and "- " bullet lists.
// Builds React elements directly (no HTML strings), so nothing in a reply can inject markup.

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4 ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      part
    ),
  )
}

export default function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let bullets: string[] = []

  function flushBullets() {
    if (bullets.length === 0) return
    blocks.push(
      <ul key={`list-${blocks.length}`}>
        {bullets.map((item, i) => (
          <li key={i}>{inline(item)}</li>
        ))}
      </ul>,
    )
    bullets = []
  }

  for (const line of text.split('\n')) {
    const bullet = line.match(/^\s*(?:[-•*])\s+(.*)$/)
    if (bullet) {
      bullets.push(bullet[1])
      continue
    }
    flushBullets()
    if (line.trim() !== '') {
      blocks.push(<p key={`p-${blocks.length}`}>{inline(line)}</p>)
    }
  }
  flushBullets()

  return <>{blocks}</>
}