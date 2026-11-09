import type { ReactNode } from 'react'

// Shows Nonna's replies with light formatting: **bold** and "- " bullet lists,
// including indented sub-bullets.
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

interface Item {
  text: string
  children: Item[]
}

function List({ items }: { items: Item[] }) {
  return (
    <ul>
      {items.map((item, i) => (
        <li key={i}>
          {inline(item.text)}
          {item.children.length > 0 && <List items={item.children} />}
        </li>
      ))}
    </ul>
  )
}

export default function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let items: Item[] = []
  // The open list at each indent level, so a deeper bullet nests under the one above it
  let stack: { indent: number; items: Item[] }[] = []

  function flushList() {
    if (items.length === 0) return
    blocks.push(<List key={`list-${blocks.length}`} items={items} />)
    items = []
    stack = []
  }

  for (const line of text.split('\n')) {
    const bullet = line.match(/^(\s*)(?:[-•*])\s+(.*)$/)
    if (bullet) {
      const indent = bullet[1].replace(/\t/g, '  ').length
      const item: Item = { text: bullet[2], children: [] }
      if (stack.length === 0) {
        stack = [{ indent, items }]
      }
      while (stack.length > 1 && indent < stack[stack.length - 1].indent) stack.pop()
      const top = stack[stack.length - 1]
      if (indent > top.indent && top.items.length > 0) {
        const parent = top.items[top.items.length - 1]
        stack.push({ indent, items: parent.children })
      }
      stack[stack.length - 1].items.push(item)
      continue
    }
    flushList()
    if (line.trim() !== '') {
      blocks.push(<p key={`p-${blocks.length}`}>{inline(line)}</p>)
    }
  }
  flushList()

  return <>{blocks}</>
}