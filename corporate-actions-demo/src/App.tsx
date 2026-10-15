import { Navigate, Route, Routes } from 'react-router-dom'
import { Shell } from './components/Layout'
import { ClientHome } from './pages/client/Home'
import { Notifications } from './pages/client/Notifications'
import { Watchlist } from './pages/client/Watchlist'
import { Dashboard } from './pages/ops/Dashboard'
import { EventRecord } from './pages/ops/EventRecord'
import { Events } from './pages/ops/Events'
import { FilingDetail } from './pages/ops/FilingDetail'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/internal/dashboard" replace />} />

      <Route path="/internal" element={<Shell mode="internal" />}>
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="events" element={<Events />} />
        <Route path="events/:eventId" element={<EventRecord mode="internal" />} />
        <Route path="filings/:filingId" element={<FilingDetail />} />
      </Route>

      <Route path="/client" element={<Shell mode="client" />}>
        <Route index element={<Navigate to="home" replace />} />
        <Route path="home" element={<ClientHome />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="watchlist" element={<Watchlist />} />
        <Route path="events/:eventId" element={<EventRecord mode="client" />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
