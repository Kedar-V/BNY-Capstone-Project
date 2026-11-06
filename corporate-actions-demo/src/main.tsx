import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import App from './App'
import { AmendmentProvider } from './state/AmendmentState'
import { AppProvider } from './state/AppState'
import { BriefProvider } from './state/BriefState'
import { ReconProvider } from './state/ReconState'
import './index.css'

// The standalone file (scripts/build_standalone.py) opens from disk, where a page cannot change its own path
const Router = window.location.protocol === 'file:' ? HashRouter : BrowserRouter

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Router>
      <AppProvider>
        <BriefProvider>
          <ReconProvider>
            <AmendmentProvider>
              <App />
            </AmendmentProvider>
          </ReconProvider>
        </BriefProvider>
      </AppProvider>
    </Router>
  </StrictMode>,
)
