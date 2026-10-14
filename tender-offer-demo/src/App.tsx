import { Navigate, Route, Routes } from 'react-router-dom'
import { Shell } from './components/Layout'
import { ClientHome } from './pages/client/Home'
import { NotificationDetail, Notifications } from './pages/client/Notifications'
import { ClientOfferDetail } from './pages/client/OfferDetail'
import { Recommendations } from './pages/client/Recommendations'
import { Watchlist } from './pages/client/Watchlist'
import { CompanyView } from './pages/internal/CompanyView'
import { AllFilings, Dashboard } from './pages/internal/Dashboard'
import { FilingDetail } from './pages/internal/FilingDetail'
import { History } from './pages/internal/History'
import { OfferRecord } from './pages/internal/OfferRecord'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/internal/dashboard" replace />} />

      <Route path="/internal" element={<Shell mode="internal" />}>
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="filings" element={<AllFilings />} />
        <Route path="filings/:filingId" element={<FilingDetail />} />
        <Route path="companies/:companyId" element={<CompanyView />} />
        <Route path="tender-offers/:offerId" element={<OfferRecord />} />
        <Route path="tender-offers/:offerId/history" element={<History />} />
      </Route>

      <Route path="/client" element={<Shell mode="client" />}>
        <Route index element={<Navigate to="home" replace />} />
        <Route path="home" element={<ClientHome />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="notifications/:notificationId" element={<NotificationDetail />} />
        <Route path="watchlist" element={<Watchlist />} />
        <Route path="tender-offers/:offerId" element={<ClientOfferDetail />} />
        <Route path="recommendations" element={<Recommendations />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
