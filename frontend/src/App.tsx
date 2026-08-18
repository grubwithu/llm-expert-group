import { Routes, Route, Link } from 'react-router-dom'
import { Box, Container, Flex, Heading, Text } from '@radix-ui/themes'
import { UsersRound } from 'lucide-react'
import { HomePage } from './pages/HomePage'
import { SessionPage } from './pages/SessionPage'

export function App() {
  return (
    <Box>
      <header className="topbar">
        <Container size="4">
          <Flex align="center" gap="3" py="4">
            <UsersRound size={26} />
            <Link to="/" className="brand-link"><Heading size="5">LLM Expert Group</Heading></Link>
            <Text color="gray" size="2">Human-in-the-loop technical council</Text>
          </Flex>
        </Container>
      </header>
      <Container size="4" py="7">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/sessions/:id" element={<SessionPage />} />
        </Routes>
      </Container>
    </Box>
  )
}
