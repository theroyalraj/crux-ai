import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// StrictMode double-mounts effects in dev and tears down WebSockets immediately, which breaks
// /voice/ws (closed before established, EPIPE in Vite). Voice UI is not wrapped in StrictMode.
createRoot(document.getElementById('root')!).render(<App />)
