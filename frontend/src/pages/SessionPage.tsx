import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Badge, Box, Button, Callout, Card, Flex, Grid, Heading, Separator, Text, TextArea } from '@radix-ui/themes'
import { ArrowLeft, CircleStop, FlaskConical, Play, RefreshCw, Route, Radio } from 'lucide-react'
import { api, subscribeRoundEvents } from '../api'
import { Markdown } from '../components/Markdown'
import { SecretaryTrace } from '../components/SecretaryTrace'
import type { CouncilEvent, RoundRun } from '../types'

type LiveExpert = { modelId: string; displayName: string; content: string; status: 'waiting' | 'running' | 'completed' | 'failed'; error?: string; askingSecretary?: boolean }
type LiveRound = { id: string; number: number; kind: string; status: string; opening: string; synthesis: string; error?: string; chairmanAskingSecretary?: boolean; synthesisAskingSecretary?: boolean; experts: Record<string, LiveExpert> }

const text = (value: unknown) => typeof value === 'string' ? value : ''

function isSecretaryRequest(value: string) {
  try {
    return JSON.parse(value)?.action === 'ask_secretary'
  } catch {
    return false
  }
}

function displayActorContent(value: string) {
  const finalStart = value.lastIndexOf('{"action":"final"')
  if (finalStart < 0) return value
  try {
    const parsed = JSON.parse(value.slice(finalStart))
    return typeof parsed.content === 'string' ? parsed.content : value
  } catch {
    return value
  }
}

export function SessionPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const { data: session, isLoading, error } = useQuery({ queryKey: ['session', id], queryFn: () => api.session(id) })
  const [note, setNote] = useState('')
  const [live, setLive] = useState<LiveRound | null>(null)
  const sourceRef = useRef<EventSource | null>(null)

  const refresh = (data: unknown) => {
    queryClient.setQueryData(['session', id], data)
    queryClient.invalidateQueries({ queryKey: ['sessions'] })
  }
  const connect = useCallback((run: RoundRun) => {
    sourceRef.current?.close()
    setLive({
      id: run.id, number: run.number, kind: run.kind, status: run.status,
      opening: displayActorContent(run.opening_statement), synthesis: displayActorContent(run.chairman_summary), error: run.error || undefined,
      experts: Object.fromEntries(run.expert_responses.map(response => [response.model_id, {
        modelId: response.model_id, displayName: response.display_name, content: displayActorContent(response.content),
        status: response.error ? 'failed' : 'completed', error: response.error || undefined,
      }])),
    })
    sourceRef.current = subscribeRoundEvents(run.id, (event: CouncilEvent) => {
      const payload = event.payload
      setLive(current => {
        if (!current || current.id !== run.id) return current
        if (event.type === 'chairman.started') return { ...current, status: 'chairman' }
        if (event.type === 'chairman.delta') {
          const delta = text(payload.text)
          return isSecretaryRequest(delta)
            ? { ...current, status: 'chairman', chairmanAskingSecretary: true }
            : { ...current, status: 'chairman', chairmanAskingSecretary: false, opening: current.opening + delta }
        }
        if (event.type === 'chairman.secretary.started') return { ...current, status: 'chairman', chairmanAskingSecretary: true }
        if (event.type === 'chairman.secretary.completed') return { ...current, chairmanAskingSecretary: false }
        if (event.type === 'chairman.completed') return { ...current, status: 'experts', chairmanAskingSecretary: false, opening: displayActorContent(text(payload.opening_statement)) || current.opening }
        if (event.type === 'expert.started') {
          const modelId = text(payload.model_id)
          return { ...current, status: 'experts', experts: { ...current.experts, [modelId]: { modelId, displayName: text(payload.display_name) || modelId, content: '', status: 'running' } } }
        }
        if (event.type === 'expert.secretary.started' || event.type === 'expert.secretary.completed') {
          const modelId = text(payload.model_id); const expert = current.experts[modelId]
          return expert ? { ...current, experts: { ...current.experts, [modelId]: { ...expert, askingSecretary: event.type.endsWith('.started') } } } : current
        }
        if (event.type === 'expert.delta') {
          const modelId = text(payload.model_id); const expert = current.experts[modelId]; const delta = text(payload.text)
          return expert ? { ...current, experts: { ...current.experts, [modelId]: { ...expert, askingSecretary: isSecretaryRequest(delta), content: isSecretaryRequest(delta) ? expert.content : expert.content + delta } } } : current
        }
        if (event.type === 'expert.completed') {
          const modelId = text(payload.model_id); const expert = current.experts[modelId]
          return expert ? { ...current, experts: { ...current.experts, [modelId]: { ...expert, status: 'completed', content: displayActorContent(text(payload.content)) || expert.content } } } : current
        }
        if (event.type === 'expert.failed') {
          const modelId = text(payload.model_id); const expert = current.experts[modelId]
          return expert ? { ...current, experts: { ...current.experts, [modelId]: { ...expert, status: 'failed', error: text(payload.error) } } } : current
        }
        if (event.type === 'synthesis.started') return { ...current, status: 'synthesis' }
        if (event.type === 'synthesis.secretary.started') return { ...current, status: 'synthesis', synthesisAskingSecretary: true }
        if (event.type === 'synthesis.secretary.completed') return { ...current, synthesisAskingSecretary: false }
        if (event.type === 'synthesis.delta') {
          const delta = text(payload.text)
          return isSecretaryRequest(delta)
            ? { ...current, status: 'synthesis', synthesisAskingSecretary: true }
            : { ...current, status: 'synthesis', synthesisAskingSecretary: false, synthesis: current.synthesis + delta }
        }
        if (event.type === 'synthesis.completed') return { ...current, synthesisAskingSecretary: false, synthesis: displayActorContent(text(payload.chairman_summary)) || current.synthesis }
        if (event.type === 'human_gate') return { ...current, status: 'awaiting_human' }
        if (event.type === 'round.failed') return { ...current, status: 'failed', error: text(payload.error) }
        if (event.type === 'round.stopped') return { ...current, status: 'stopped', error: text(payload.reason) || 'Stopped by user.' }
        return current
      })
      if (event.type === 'human_gate' || event.type === 'round.failed' || event.type === 'round.stopped') {
        sourceRef.current?.close()
        queryClient.invalidateQueries({ queryKey: ['session', id] })
        queryClient.invalidateQueries({ queryKey: ['sessions'] })
      }
    })
  }, [id, queryClient])

  useEffect(() => () => sourceRef.current?.close(), [])
  useEffect(() => {
    if ((session?.status === 'running' || session?.status === 'error') && !live) {
      api.latestRoundRun(id).then(run => { if (run && ['queued', 'running', 'failed'].includes(run.status)) connect(run) }).catch(() => undefined)
    }
  }, [session?.status, id, live, connect])

  const run = useMutation({ mutationFn: () => api.startRound(id), onSuccess: connect })
  const stop = useMutation({
    mutationFn: () => api.stopRound(id),
    onSuccess: data => {
      sourceRef.current?.close()
      if (data) setLive(current => current?.id === data.id ? { ...current, status: 'stopped', error: 'Stopped by user.' } : current)
      queryClient.invalidateQueries({ queryKey: ['session', id] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })
  const act = useMutation({
    mutationFn: (action: string) => api.action(id, { action, note: note || undefined }),
    onSuccess: data => { setNote(''); refresh(data) },
  })

  if (isLoading) return <Text>Loading…</Text>
  if (error || !session) return <Callout.Root color="red"><Callout.Text>{error?.message || 'Session not found'}</Callout.Text></Callout.Root>
  const busyError = run.error?.message || stop.error?.message || act.error?.message || (live?.status === 'failed' ? live.error : undefined)
  const showLive = live && (!session.rounds.some(round => round.number === live.number) || session.status === 'running')

  return (
    <Box>
      <Link to="/" className="back-link"><Flex gap="2" align="center"><ArrowLeft size={16}/>Sessions</Flex></Link>
      <Flex justify="between" align="start" mt="4" mb="6" gap="4" wrap="wrap">
        <Box>
          <Heading size="7">{session.title}</Heading>
          <Text color="gray" as="div" mt="2">{session.repo_path}</Text>
          <Flex gap="2" mt="3"><Badge>{session.status}</Badge><Badge color="gray">round {session.current_round}</Badge>{session.repo_commit && <Badge color="gray">{session.repo_commit.slice(0, 10)}</Badge>}</Flex>
        </Box>
        <Flex gap="3" align="center" wrap="wrap">
          {(session.status === 'ready' || session.status === 'error') && (
            <Button size="3" onClick={() => run.mutate()} loading={run.isPending}>
              <Play size={17}/>{session.status === 'error' ? 'Retry round' : session.current_round ? 'Run next round' : 'Start council'}
            </Button>
          )}
          {session.status === 'running' && (
            <Button size="3" color="red" variant="soft" onClick={() => stop.mutate()} loading={stop.isPending}>
              <CircleStop size={17}/>Stop all
            </Button>
          )}
        </Flex>
      </Flex>

      <Card mb="6"><Heading size="3" mb="2">Original question</Heading><Text>{session.topic}</Text></Card>
      {session.repo_context_truncated && <Callout.Root mb="5" color="amber"><Callout.Text>The initial repository provenance snapshot hit the configured size limit. Secretary queries still inspect the repository directly through bounded read-only tools.</Callout.Text></Callout.Root>}
      {busyError && <Callout.Root mb="5" color="red"><Callout.Text>{busyError}</Callout.Text></Callout.Root>}

      {showLive && <Card mb="6" className="live-round">
        <Flex justify="between" align="center" mb="4"><Flex align="center" gap="2"><Radio size={17} className="live-signal"/><Heading size="5">Round {live.number} · live council</Heading></Flex><Badge color={live.status === 'failed' ? 'red' : 'indigo'}>{live.status}</Badge></Flex>
        <section className="live-stage">
          <Text size="1" weight="bold" color="gray">01 — CHAIRMAN OPENING </Text>
          {live.chairmanAskingSecretary && <Text size="2" className="secretary-status" as="div">Asking Secretary for repository evidence…</Text>}
          {live.opening ? <Markdown>{live.opening}</Markdown> : <Text color="gray">{live.chairmanAskingSecretary ? 'Asking Secretary for repository evidence…' : 'Chairman is preparing the neutral agenda…'}</Text>}
        </section>
        <Separator size="4" my="5" />
        <Text size="1" weight="bold" color="gray" as="div" mb="3">02 — INDEPENDENT EXPERTS </Text>
        <Grid columns={{ initial: '1', md: '2' }} gap="3">
          {Object.values(live.experts).map(expert => <Card key={expert.modelId} variant="surface" className="live-expert">
            <Flex justify="between" gap="2" mb="2"><Text weight="bold">{expert.displayName}</Text><Badge color={expert.status === 'failed' ? 'red' : expert.status === 'completed' ? 'gray' : 'indigo'}>{expert.status}</Badge></Flex>
            {expert.askingSecretary && <Text size="2" className="secretary-status" as="div">Asking Secretary for repository evidence…</Text>}
            <div className="expert-response-body">
              {expert.error ? <Text color="red" size="2">{expert.error}</Text> : expert.content ? <Markdown>{expert.content}</Markdown> : <Text color="gray" size="2">{expert.askingSecretary ? 'Asking Secretary for repository evidence…' : expert.status === 'waiting' ? 'Waiting for Chairman…' : 'Thinking…'}</Text>}
            </div>
          </Card>)}
        </Grid>
        <Separator size="4" my="5" />
        <section className="live-stage">
          <Text size="1" weight="bold" color="gray">03 — CHAIRMAN SYNTHESIS </Text>
          {live.synthesisAskingSecretary && <Text size="2" className="secretary-status" as="div">Asking Secretary to verify disputed evidence…</Text>}
          {live.synthesis ? <Markdown>{live.synthesis}</Markdown> : <Text color="gray">{live.synthesisAskingSecretary ? 'Asking Secretary to verify disputed evidence…' : 'Waiting for independent expert conclusions…'}</Text>}
        </section>
      </Card>}

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
                <Card key={response.model_id} variant="surface" className="expert-response">
                  <Flex justify="between" mb="2"><Text weight="bold">{response.display_name}</Text><Badge color={response.error ? 'red' : 'gray'}>{response.model_id}</Badge></Flex>
                  <div className="expert-response-body">{response.error ? <Text color="red">Provider error: {response.error}</Text> : <Markdown>{response.content}</Markdown>}</div>
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
