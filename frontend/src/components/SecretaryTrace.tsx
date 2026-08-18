import { Badge, Box, Card, Flex, Text } from '@radix-ui/themes'
import type { SecretaryInteraction } from '../types'

function statusColor(status: SecretaryInteraction['status']) {
  if (status === 'VERIFIED') return 'green' as const
  if (status === 'CONFLICTING_EVIDENCE') return 'orange' as const
  if (status === 'NOT_FOUND') return 'gray' as const
  if (status === 'UNSTRUCTURED') return 'red' as const
  return 'amber' as const
}

export function SecretaryTrace({ items, label = 'Secretary evidence' }: { items: SecretaryInteraction[]; label?: string }) {
  if (!items.length) return null
  return (
    <Box mt="4">
      <details className="secretary-trace">
        <summary>{label} ({items.length})</summary>
        <Flex direction="column" gap="3" mt="3">
          {items.map(item => (
            <Card key={item.id} variant="surface">
              <Flex justify="between" gap="3" align="start" wrap="wrap">
                <Text weight="bold">Q{item.sequence}: {item.question}</Text>
                <Badge color={statusColor(item.status)}>{item.status}</Badge>
              </Flex>
              <Text as="div" mt="2" size="2">{item.answer}</Text>
              {item.evidence.length > 0 && (
                <Box mt="3">
                  <Text size="2" weight="bold">Evidence</Text>
                  {item.evidence.map((evidence, index) => (
                    <Box key={`${item.id}-${evidence.path}-${index}`} mt="2" className="evidence-block">
                      <Text size="1" color="gray" as="div">
                        {evidence.path}:{evidence.start_line}-{evidence.end_line}{evidence.reason ? ` — ${evidence.reason}` : ''}
                      </Text>
                      {evidence.excerpt && <pre>{evidence.excerpt}</pre>}
                    </Box>
                  ))}
                </Box>
              )}
              {item.repo_commit && (
                <Text size="1" color="gray" as="div" mt="3">Observed commit: {item.repo_commit.slice(0, 12)}</Text>
              )}
              {item.limitations.length > 0 && (
                <Text size="1" color="gray" as="div" mt="2">Limitations: {item.limitations.join('; ')}</Text>
              )}
              {item.tool_trace.length > 0 && (
                <details className="secretary-tool-trace">
                  <summary>Repository tool trace</summary>
                  <pre>{item.tool_trace.join('\n')}</pre>
                </details>
              )}
            </Card>
          ))}
        </Flex>
      </details>
    </Box>
  )
}
