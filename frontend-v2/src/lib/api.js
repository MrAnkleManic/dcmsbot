const API_BASE = '/api';

export async function queryBot({ question, filters, debug, conversation_history }) {
  const payload = { question, filters, debug };
  if (conversation_history && conversation_history.length > 0) {
    payload.conversation_history = conversation_history;
  }
  const res = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Query failed (${res.status}): ${text}`);
  }

  return res.json();
}

export async function fetchStatus() {
  const res = await fetch(`${API_BASE}/status`);
  if (!res.ok) throw new Error(`Status check failed (${res.status})`);
  return res.json();
}

export async function fetchKbStats() {
  const res = await fetch(`${API_BASE}/kb-stats`);
  if (!res.ok) throw new Error(`KB stats fetch failed (${res.status})`);
  return res.json();
}

export async function fetchChunk(chunkId) {
  const res = await fetch(`${API_BASE}/chunk/${encodeURIComponent(chunkId)}`);
  if (!res.ok) throw new Error(`Chunk fetch failed (${res.status})`);
  return res.json();
}
