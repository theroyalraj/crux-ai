import { Conversation } from '@elevenlabs/client'
import { useCallback, useEffect, useRef, useState } from 'react'

type Role = 'user' | 'agent' | 'narrator' | 'crux'

type Line = {
  id: string
  role: Role
  text: string
  ts: number
}

const apiBase = () => (import.meta.env.VITE_CRUX_BASE || '').replace(/\/$/, '')

/** WebSocket origin for /voice/ws (no path). Empty VITE_CRUX_BASE: bypass Vite WS proxy (fixes EPIPE / early close). */
function wsBaseUrl(): string {
  const override = (import.meta.env.VITE_CRUX_WS_ORIGIN || '').trim().replace(/\/$/, '')
  if (override) {
    return override
  }
  const b = import.meta.env.VITE_CRUX_BASE
  if (b) {
    const u = new URL(b)
    const proto = u.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${u.host}`
  }
  return 'ws://127.0.0.1:9090'
}

function voiceSecret(): string {
  return (import.meta.env.VITE_CRUX_VOICE_SECRET || '').trim()
}

export default function App() {
  const [lines, setLines] = useState<Line[]>([])
  const [status, setStatus] = useState<'idle' | 'connecting' | 'live' | 'error'>('idle')
  const [mode, setMode] = useState<string>('')
  const [micMuted, setMicMuted] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const [narrationWs, setNarrationWs] = useState<WebSocket | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [downflowBusy, setDownflowBusy] = useState(false)

  const convRef = useRef<Awaited<ReturnType<typeof Conversation.startSession>> | null>(null)
  const userTranscriptRef = useRef<string[]>([])

  const pushLine = useCallback((role: Role, text: string) => {
    const t = text.trim()
    if (!t) return
    setLines((prev) => [
      ...prev,
      { id: `${Date.now()}-${Math.random()}`, role, text: t, ts: Date.now() },
    ])
  }, [])

  const pushLineRef = useRef(pushLine)
  pushLineRef.current = pushLine

  /** One narration socket for app lifetime; empty deps avoid StrictMode / callback churn reconnect storms. */
  useEffect(() => {
    const sec = voiceSecret()
    const q = sec ? `?secret=${encodeURIComponent(sec)}` : ''
    const url = `${wsBaseUrl()}/voice/ws${q}`
    const ws = new WebSocket(url)
    let pingId: ReturnType<typeof setInterval> | null = null
    let closed = false

    ws.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data as string) as {
          type?: string
          text?: string
          persona?: string | null
        }
        if (d.type === 'narration' && d.text) {
          const label = d.persona ? `[${d.persona}] ` : ''
          pushLineRef.current('narrator', `${label}${d.text}`)
          const c = convRef.current
          if (c && 'sendContextualUpdate' in c && typeof c.sendContextualUpdate === 'function') {
            c.sendContextualUpdate(`Narrator: ${d.text}`)
          }
        }
      } catch {
        /* ignore */
      }
    }
    ws.onopen = () => {
      if (closed) return
      setErr(null)
      setNarrationWs(ws)
      pingId = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 25000)
    }
    ws.onerror = () => {
      if (!closed) setErr('Narration WebSocket error (check Crux on 9090 and voice secret)')
    }
    ws.onclose = (ev) => {
      closed = true
      if (pingId !== null) {
        window.clearInterval(pingId)
        pingId = null
      }
      setNarrationWs(null)
      if (ev.code === 4401) {
        setErr('Voice WebSocket rejected: set VITE_CRUX_VOICE_SECRET to match server CRUX_VOICE_WS_SECRET')
      }
    }

    return () => {
      closed = true
      if (pingId !== null) window.clearInterval(pingId)
      ws.close()
      setNarrationWs(null)
    }
  }, [])

  const startSession = async () => {
    setErr(null)
    setStatus('connecting')
    userTranscriptRef.current = []
    try {
      const r = await fetch(`${apiBase()}/voice/convai/signed-url`)
      if (!r.ok) throw new Error(await r.text())
      const { signed_url: signedUrl } = (await r.json()) as { signed_url: string }
      const conv = await Conversation.startSession({
        signedUrl: signedUrl,
        connectionType: 'websocket',
        onConnect: () => {
          setStatus('live')
          pushLine('agent', 'Connected to ElevenLabs agent.')
        },
        onDisconnect: () => {
          setStatus('idle')
          setMode('')
          convRef.current = null
        },
        onError: (msg) => setErr(String(msg)),
        onMessage: (props) => {
          const { message, role } = props
          if (role === 'user') {
            userTranscriptRef.current.push(message)
            pushLine('user', message)
          } else {
            pushLine('agent', message)
          }
        },
        onModeChange: ({ mode: m }) => setMode(m),
      })
      convRef.current = conv
    } catch (e) {
      setStatus('error')
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  const stopAndDownflow = async () => {
    setErr(null)
    const conv = convRef.current
    if (conv) {
      try {
        await conv.endSession()
      } catch {
        /* ignore */
      }
      convRef.current = null
    }
    setStatus('idle')
    setMode('')

    const transcript = userTranscriptRef.current.join('\n').trim()
    const history = lines.slice(-40).map((l) => ({
      role: l.role === 'crux' ? 'assistant' : l.role === 'narrator' ? 'system' : l.role,
      content: l.text,
    }))
    if (!transcript && history.length === 0) {
      setErr('Nothing to send — speak or type first.')
      return
    }

    setDownflowBusy(true)
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      const sec = voiceSecret()
      if (sec) headers['X-Crux-Voice-Secret'] = sec
      const r = await fetch(`${apiBase()}/voice/downflow`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          transcript,
          messages: history,
          source: 'voice-ui',
        }),
      })
      if (!r.ok) throw new Error(await r.text())
      const data = (await r.json()) as { response?: string }
      const out = data.response ?? JSON.stringify(data)
      pushLine('crux', out)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setDownflowBusy(false)
    }
  }

  const sendChat = () => {
    const t = chatInput.trim()
    if (!t) return
    const c = convRef.current
    if (c && 'sendUserMessage' in c && typeof c.sendUserMessage === 'function') {
      c.sendUserMessage(t)
      pushLine('user', t)
    } else {
      pushLine('user', t)
    }
    setChatInput('')
  }

  const toggleMic = () => {
    const c = convRef.current
    const next = !micMuted
    if (c && 'setMicMuted' in c && typeof c.setMicMuted === 'function') {
      c.setMicMuted(next)
    }
    setMicMuted(next)
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-white">Crux voice</h1>
            <p className="text-sm text-zinc-400">ElevenLabs agent + Crux narration + downflow</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                narrationWs?.readyState === WebSocket.OPEN
                  ? 'bg-emerald-500/20 text-emerald-300'
                  : 'bg-amber-500/20 text-amber-200'
              }`}
            >
              WS {narrationWs?.readyState === WebSocket.OPEN ? 'live' : '…'}
            </span>
            <span className="rounded-full bg-zinc-800 px-3 py-1 text-xs text-zinc-300">
              agent: {status}
              {mode ? ` · ${mode}` : ''}
            </span>
          </div>
        </header>

        {err && (
          <div className="rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-2 text-sm text-red-200">
            {err}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={startSession}
            disabled={status === 'connecting' || status === 'live'}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:opacity-40"
          >
            Start voice
          </button>
          <button
            type="button"
            onClick={toggleMic}
            disabled={status !== 'live'}
            className="rounded-lg bg-zinc-800 px-4 py-2 text-sm font-medium text-white ring-1 ring-zinc-700 hover:bg-zinc-700 disabled:opacity-40"
          >
            {micMuted ? 'Unmute mic' : 'Mute mic'}
          </button>
          <button
            type="button"
            onClick={stopAndDownflow}
            disabled={downflowBusy}
            className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-500 disabled:opacity-40"
          >
            {downflowBusy ? 'Crux…' : 'Stop → Crux'}
          </button>
        </div>

        <div className="h-[min(52vh,480px)] overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
          <ul className="flex flex-col gap-3">
            {lines.length === 0 && (
              <li className="text-center text-sm text-zinc-500">No messages yet.</li>
            )}
            {lines.map((l) => (
              <li
                key={l.id}
                className={`max-w-[90%] rounded-2xl px-4 py-2 text-sm leading-relaxed ${
                  l.role === 'user'
                    ? 'ml-auto bg-indigo-600/90 text-white'
                    : l.role === 'agent'
                      ? 'mr-auto bg-zinc-800 text-zinc-100'
                      : l.role === 'narrator'
                        ? 'mx-auto w-full border border-violet-900/40 bg-violet-950/30 text-violet-100'
                        : 'mr-auto border border-teal-900/40 bg-teal-950/40 text-teal-50'
                }`}
              >
                <span className="mb-1 block text-[10px] uppercase tracking-wider opacity-70">
                  {l.role}
                </span>
                {l.text}
              </li>
            ))}
          </ul>
        </div>

        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            sendChat()
          }}
        >
          <input
            className="flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm text-white placeholder:text-zinc-500 focus:border-indigo-500 focus:outline-none"
            placeholder="Type a message (sendUserMessage when session live)…"
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
          />
          <button
            type="submit"
            className="rounded-lg bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-white"
          >
            Send
          </button>
        </form>

        <p className="text-xs text-zinc-500">
          Set <code className="text-zinc-400">CRUX_VOICE_OUTPUT=browser</code> on Crux and open this UI
          before <code className="text-zinc-400">speak.sh</code> so narration routes here. Requires{' '}
          <code className="text-zinc-400">CRUX_ELEVENLABS_AGENT_ID</code> and API key on the server.
        </p>
      </div>
    </div>
  )
}
