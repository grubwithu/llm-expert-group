import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { Badge, Box, Button, Card, Flex, Grid, Heading, Text, TextArea, TextField } from '@radix-ui/themes'
import { ArrowRight, FolderGit2, Plus } from 'lucide-react'
import { api } from '../api'

export function HomePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: sessions = [] } = useQuery({ queryKey: ['sessions'], queryFn: api.sessions })
  const [title, setTitle] = useState('')
  const [topic, setTopic] = useState('')
  const [repoPath, setRepoPath] = useState('')

  const create = useMutation({
    mutationFn: api.createSession,
    onSuccess: async (session) => {
      await queryClient.invalidateQueries({ queryKey: ['sessions'] })
      navigate(`/sessions/${session.id}`)
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate({ title, topic, repo_path: repoPath })
  }

  return (
    <Grid columns={{ initial: '1', md: '2' }} gap="6">
      <Box>
        <Heading size="7" mb="2">Technical decisions, with dissent preserved.</Heading>
        <Text color="gray">A chairman reads the repository, opens a neutral agenda, independent models respond in parallel, then the chairman synthesizes evidence and disagreement. You decide whether the council continues.</Text>

        <Card mt="6">
          <form onSubmit={submit}>
            <Flex direction="column" gap="4">
              <Flex align="center" gap="2"><Plus size={18}/><Heading size="4">New council session</Heading></Flex>
              <label><Text as="div" size="2" mb="1">Title</Text><TextField.Root value={title} onChange={e => setTitle(e.target.value)} placeholder="SyncFuzz P1 planning" required /></label>
              <label><Text as="div" size="2" mb="1">Repository path on the backend host</Text><TextField.Root value={repoPath} onChange={e => setRepoPath(e.target.value)} placeholder="/home/me/src/syncfuzz" required /></label>
              <label><Text as="div" size="2" mb="1">Decision / question</Text><TextArea value={topic} onChange={e => setTopic(e.target.value)} rows={7} placeholder="What should the project do next, under the frozen P0 constraints?" required /></label>
              {create.error && <Text color="red">{create.error.message}</Text>}
              <Button type="submit" loading={create.isPending}>Create session</Button>
            </Flex>
          </form>
        </Card>
      </Box>

      <Box>
        <Heading size="5" mb="4">Recent sessions</Heading>
        <Flex direction="column" gap="3">
          {sessions.map(session => (
            <Card key={session.id} asChild>
              <Link to={`/sessions/${session.id}`} className="session-card">
                <Flex justify="between" align="center" gap="4">
                  <Box>
                    <Flex gap="2" align="center"><FolderGit2 size={16}/><Text weight="bold">{session.title}</Text></Flex>
                    <Text as="div" color="gray" size="2" mt="2">Round {session.current_round} · {session.repo_commit?.slice(0, 8) || 'no git commit'}</Text>
                  </Box>
                  <Flex align="center" gap="3"><Badge>{session.status}</Badge><ArrowRight size={18}/></Flex>
                </Flex>
              </Link>
            </Card>
          ))}
          {!sessions.length && <Text color="gray">No sessions yet.</Text>}
        </Flex>
      </Box>
    </Grid>
  )
}
