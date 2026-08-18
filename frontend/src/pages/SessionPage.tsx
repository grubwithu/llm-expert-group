import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Badge, Box, Button, Callout, Card, Flex, Heading, Separator, Text, TextArea } from '@radix-ui/themes'
import { ArrowLeft, CircleStop, FlaskConical, Play, RefreshCw, Route } from 'lucide-react'
import { api } from '../api'
import { Markdown } from '../components/Markdown'
import { SecretaryTrace } from '../components/SecretaryTrace'

export function SessionPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const { data: session, isLoading, error } = useQuery({ queryKey: ['session', id], queryFn: () => api.session(id) })
  const [note, setNote] = useState('')

  const refresh = (data: unknown) => {
    queryClient.setQueryData(['session', id], data)
    queryClient.invalidateQueries({ queryKey: ['sessions'] })
  }
  const run = useMutation({ mutationFn: () => api.runRound(id), onSuccess: refresh })
  const act = useMutation({
    mutationFn: (action: string) => api.action(id, { action, note: note || undefined }),
    onSuccess: data => { setNote(''); refresh(data) },
  })

  if (isLoading) return <Text>Loading…</Text>
  if (error || !session) return <Callout.Root color="red"><Callout.Text>{error?.message || 'Session not found'}</Callout.Text></Callout.Root>
  const busyError = run.error?.message || act.error?.message

  return (
    <Box>
      <Link to="/" className="back-link"><Flex gap="2" align="center"><ArrowLeft size={16}/>Sessions</Flex></Link>
      <Flex justify="between" align="start" mt="4" mb="6" gap="4" wrap="wrap">
        <Box>
          <Heading size="7">{session.title}</Heading>
          <Text color="gray" as="div" mt="2">{session.repo_path}</Text>
          <Flex gap="2" mt="3"><Badge>{session.status}</Badge><Badge color="gray">round {session.current_round}</Badge>{session.repo_commit && <Badge color="gray">{session.repo_commit.slice(0, 10)}</Badge>}</Flex>
        </Box>
        {(session.status === 'ready' || session.status === 'error') && (
          <Button size="3" onClick={() => run.mutate()} loading={run.isPending}>
            <Play size={17}/>{session.status === 'error' ? 'Retry round' : session.current_round ? 'Run next round' : 'Start council'}
          </Button>
        )}
      </Flex>

      <Card mb="6"><Heading size="3" mb="2">Original question</Heading><Text>{session.topic}</Text></Card>
      {session.repo_context_truncated && <Callout.Root mb="5" color="amber"><Callout.Text>The initial repository provenance snapshot hit the configured size limit. Secretary queries still inspect the repository directly through bounded read-only tools.</Callout.Text></Callout.Root>}
      {busyError && <Callout.Root mb="5" color="red"><Callout.Text>{busyError}</Callout.Text></Callout.Root>}

      <Flex direction="column" gap="6">
        {session.rounds.map(round => (
          <Card key={round.id}>
            <Flex justify="between" align="center" mb="4"><Heading size="5">Round {round.number}</Heading><Badge color={round.kind === 'investigation' ? 'orange' : 'indigo'}>{round.kind}</Badge></Flex>
            <Heading size="3" mb="2">Chairman opening</Heading><Markdown>{round.opening_statement}</Markdown>
            <SecretaryTrace items={round.chairman_opening_secretary_queries || []} label="Chairman → Secretary" />
            <Separator size="4" my="5" />
            <Heading size="3" mb="3">Independent expert responses</Heading>
            <Flex direction="column" gap="4">
              {round.expert_responses.map(response => (
                <Card key={response.model_id} variant="surface">
                  <Flex justify="between" mb="2"><Text weight="bold">{response.display_name}</Text><Badge color={response.error ? 'red' : 'gray'}>{response.model_id}</Badge></Flex>
                  {response.error ? <Text color="red">Provider error: {response.error}</Text> : <Markdown>{response.content}</Markdown>}
                  <SecretaryTrace items={response.secretary_queries || []} label={`${response.display_name} → Secretary`} />
                  {response.protocol_warnings?.length > 0 && <Text size="1" color="orange" as="div" mt="3">Protocol warnings: {response.protocol_warnings.join('; ')}</Text>}
                </Card>
              ))}
            </Flex>
            <Separator size="4" my="5" />
            <Heading size="3" mb="2">Chairman synthesis</Heading><Markdown>{round.chairman_summary}</Markdown>
            <SecretaryTrace items={round.chairman_synthesis_secretary_queries || []} label="Chairman → Secretary" />
            {round.human_action && <Callout.Root mt="5"><Callout.Text>Human action: <strong>{round.human_action}</strong>{round.human_note ? ` — ${round.human_note}` : ''}</Callout.Text></Callout.Root>}
          </Card>
        ))}
      </Flex>

      {session.status === 'awaiting_human' && (
        <Card mt="7" className="human-gate">
          <Heading size="5">Human gate</Heading>
          <Text color="gray" as="div" mt="1" mb="4">Continue the narrowing discussion, redirect it, request an evidence-focused repository investigation, or stop.</Text>
          <TextArea value={note} onChange={e => setNote(e.target.value)} placeholder="Optional for Continue/Stop; required for Redirect/Investigate. Describe what the next round should focus on." rows={4} />
          <Flex gap="3" mt="4" wrap="wrap">
            <Button onClick={() => act.mutate('continue')} loading={act.isPending}><RefreshCw size={16}/>Continue</Button>
            <Button variant="soft" onClick={() => act.mutate('redirect')} loading={act.isPending}><Route size={16}/>Redirect</Button>
            <Button color="orange" variant="soft" onClick={() => act.mutate('investigate')} loading={act.isPending}><FlaskConical size={16}/>Investigate</Button>
            <Button color="red" variant="soft" onClick={() => act.mutate('stop')} loading={act.isPending}><CircleStop size={16}/>Stop</Button>
          </Flex>
        </Card>
      )}
    </Box>
  )
}
