import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { Theme } from '@radix-ui/themes'
import '@radix-ui/themes/styles.css'
import './styles.css'
import { App } from './App'

const queryClient = new QueryClient()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Theme appearance="dark" accentColor="indigo" grayColor="slate" radius="large">
          <App />
        </Theme>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
